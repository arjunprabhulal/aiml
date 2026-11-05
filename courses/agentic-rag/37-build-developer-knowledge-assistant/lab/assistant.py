"""Versioned, permission-aware retrieval and cited answers for the capstone."""
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Literal
import hashlib
import json
import math
import re
import time
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).parent
STOP = set('a an and are as at be can do does for from how i in is it of on or the to what when where which with you your'.split())
ALIASES = {'undo': 'rollback', 'revert': 'rollback', 'credential': 'token', 'release': 'deploy'}
GRANTS = {'reader': {'handbook'}, 'maintainer': {'handbook', 'operations'}}

def terms(text):
    return [t for t in re.findall(r'[a-z0-9_]+', text.lower()) if t not in STOP]

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

class Ask(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=1, max_length=512)
    version: Literal['3.4', '3.5'] = '3.5'
    collection: Literal['handbook', 'operations'] = 'handbook'

class Citation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=800)

class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: Literal['answered', 'abstain']
    answer: str = Field(min_length=1, max_length=2500)
    citations: list[Citation] = Field(max_length=3)

class Denied(Exception): pass
class Busy(Exception): pass
class BadAnswer(Exception): pass

@dataclass(frozen=True)
class Passage:
    id: str
    document: str
    title: str
    version: str
    collection: str
    text: str
    start: int
    end: int

class Corpus:
    def __init__(self, root=ROOT / 'docs'):
        self.documents = {}
        self.passages = []
        records = json.loads((root / 'manifest.json').read_text())
        seen = set()
        for row in records:
            if row['id'] in seen: raise ValueError('Duplicate document ID')
            seen.add(row['id'])
            path = root / row['file']
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Document leaves corpus directory')
            text = path.read_text(encoding='utf-8')
            if len(text.encode()) > 16000: raise ValueError('Document too large')
            self.documents[row['id']] = {**row, 'text': text}
            for n, match in enumerate(re.finditer(r'\S[^\n]*(?:\n(?!\s*\n)[^\n]*)*', text)):
                paragraph = match.group().strip()
                if paragraph.startswith('#'): continue
                if len(paragraph)>800: raise ValueError('Split document paragraphs longer than 800 characters')
                self.passages.append(Passage(f"{row['id']}:p{n}", row['id'], row['title'],
                    row['version'], row['collection'], paragraph, match.start(), match.start()+len(paragraph)))
        self.snapshot = digest(self.documents)
        if not self.passages: raise ValueError('Empty corpus')

    def eligible(self, role, version, collection):
        if collection not in GRANTS.get(role, set()): raise Denied('Collection access denied')
        return [p for p in self.passages if p.collection == collection and p.version == version]

    def document(self, role, document_id):
        row = self.documents.get(document_id)
        if not row or row['collection'] not in GRANTS.get(role, set()):
            raise Denied('Source unavailable')
        return row


def rank(query, passages):
    """BM25 over eligible paragraphs; private passages never enter its statistics."""
    query = set(query)
    if not query or not passages: return []
    bags = [Counter(terms(p.text)) for p in passages]
    average = sum(sum(b.values()) for b in bags) / len(bags) or 1
    frequency = Counter(t for b in bags for t in b)
    scored = []
    for p, bag in zip(passages, bags):
        score = 0.0
        for t in query:
            tf = bag[t]
            if tf:
                idf = math.log(1+(len(bags)-frequency[t]+0.5)/(frequency[t]+0.5))
                score += idf * tf * 2.2 / (tf + 1.2*(0.25+0.75*sum(bag.values())/average))
        if score > 0: scored.append((score, p))
    return [p for _, p in sorted(scored, key=lambda r: (-r[0], r[1].id))]


class Extractive:
    name = 'extractive'
    def generate(self, question, passages):
        # A useful offline baseline: quote the selected evidence, without paraphrasing.
        selected = passages[:2]
        return Answer(status='answered', answer='\n\n'.join(p.text for p in selected),
            citations=[Citation(source_id=p.id, quote=p.text) for p in selected])


def validate_answer(answer, passages):
    answer = Answer.model_validate(answer) if isinstance(answer, dict) else Answer.model_validate(answer.model_dump())
    by_id = {p.id: p for p in passages}
    if answer.status == 'answered' and not answer.citations: raise BadAnswer('Answer has no citations')
    if answer.status == 'abstain' and answer.citations: raise BadAnswer('Abstention has citations')
    if len({c.source_id for c in answer.citations}) != len(answer.citations): raise BadAnswer('Duplicate citation')
    for citation in answer.citations:
        if citation.source_id not in by_id or citation.quote not in by_id[citation.source_id].text:
            raise BadAnswer('Citation is not an exact quote from admitted context')
    return answer

class Assistant:
    def __init__(self, corpus=None, provider=None, *, capacity=2, ttl=60, context_bytes=2400, clock=time.monotonic):
        self.corpus = corpus or Corpus()
        self.provider = provider or Extractive()
        self.slots = BoundedSemaphore(capacity)
        self.lock = Lock()
        self.cache = OrderedDict()
        self.ttl, self.context_bytes, self.clock = ttl, context_bytes, clock

    def retrieve(self, principal, role, request):
        eligible = self.corpus.eligible(role, request.version, request.collection)  # Before cache lookup.
        question = request.question.strip()
        if not terms(question): raise ValueError('Ask a question containing a word')
        key = (principal, role, request.version, request.collection, question, self.corpus.snapshot)
        now = self.clock()
        with self.lock:
            old = self.cache.get(key)
            if old and old[0] > now:
                self.cache.move_to_end(key)
                return list(old[1]), {'cache_hit': True, 'searches': 0, 'refined': False}
        query = terms(question)
        hits = rank(query, eligible)
        refined = False
        if not hits:
            expanded = query + [ALIASES[t] for t in query if t in ALIASES]
            if expanded != query: hits = rank(expanded, eligible); refined = True
        with self.lock:
            self.cache[key] = (now+self.ttl, tuple(hits[:3]))
            self.cache.move_to_end(key)
            while len(self.cache) > 32: self.cache.popitem(last=False)
        return hits[:3], {'cache_hit': False, 'searches': 2 if refined else 1, 'refined': refined}

    def ask(self, principal, role, request):
        # Authorize before admission too: denied requests do not consume model capacity.
        self.corpus.eligible(role, request.version, request.collection)
        if not self.slots.acquire(blocking=False): raise Busy('Assistant is busy; try later')
        try:
            passages, trace = self.retrieve(principal, role, request)
            admitted, used = [], 0
            for p in passages:
                size = len(json.dumps({'id': p.id, 'text': p.text}, ensure_ascii=False).encode())
                if used+size <= self.context_bytes:
                    admitted.append(p); used += size
            trace.update(context_bytes=used, source_reads=len(admitted), snapshot=self.corpus.snapshot,
                         provider=self.provider.name, model_requests=int(bool(admitted) and self.provider.name!='extractive'))
            if not admitted:
                answer = Answer(status='abstain', answer='I could not find supporting documentation for that question in this collection and version.', citations=[])
            else:
                answer = validate_answer(self.provider.generate(request.question, admitted), admitted)
            return {**answer.model_dump(), 'sources': [{'id':p.id,'document':p.document,'title':p.title,
                'version':p.version,'quote':p.text,'start':p.start,'end':p.end} for p in admitted], 'trace':trace}
        finally:
            self.slots.release()
