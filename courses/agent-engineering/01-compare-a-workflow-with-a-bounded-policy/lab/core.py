"""Small document tools and a provider-independent decision loop."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Callable

ROOT = Path(__file__).resolve().parent
STOP = frozenset('a an and are can do for how i in is it me my of on the to what with'.split())


def load(name):
    return json.loads((ROOT / name).read_text())


def words(text):
    return set(re.findall(r'[a-z0-9]+', text.casefold())) - STOP


@dataclass(frozen=True)
class Task:
    id: str
    family: str
    question: str
    version: str = 'v2'
    environment: str = 'staging'

    def __post_init__(self):
        if any(not isinstance(v, str) or not v.strip() or len(v) > 100
               for v in (self.id, self.family, self.version, self.environment)):
            raise ValueError('task metadata must contain bounded strings')
        if self.version not in {'v1', 'v2'}:
            raise ValueError('unsupported documentation version')
        if self.environment != 'staging':
            raise ValueError('this assistant only covers staging')
        if not isinstance(self.question, str) or not self.question.strip() or len(self.question) > 500:
            raise ValueError('question must contain 1..500 characters')


class Documents:
    def __init__(self):
        self.pages = load('documents.json')
        self.aliases = load('glossary.json')

    def search(self, query, version, *, expand=False, top_k=1):
        if version not in {'v1', 'v2'} or type(top_k) is not int or top_k not in {1, 2, 3}:
            raise ValueError('invalid search configuration')
        terms = words(query)
        if expand:
            terms |= {self.aliases[t] for t in tuple(terms) if t in self.aliases}
        ranked = []
        for page in self.pages:
            if page['version'] != version:
                continue
            score = len(terms & words(page['title'] + ' ' + page['text']))
            if score:
                ranked.append((-score, page['id'], page['title']))
        return [{'id': id, 'title': title} for _, id, title in sorted(ranked)[:top_k]]

    def read(self, id, version):
        page = next((p for p in self.pages if p['id'] == id), None)
        if page is None or page['version'] != version:
            raise ValueError('page does not exist in the requested version')
        return dict(page)


def validate_decision(value):
    """Reject unknown fields and actions before dispatching a tool."""
    if not isinstance(value, dict):
        raise ValueError('decision must be an object')
    action = value.get('action')
    keys = {'search': {'action', 'query'}, 'read': {'action', 'id'},
            'final': {'action', 'answer', 'citation'}}
    if not isinstance(action, str) or action not in keys or set(value) != keys[action]:
        raise ValueError('unknown action or unexpected fields')
    if any(not isinstance(v, str) or len(v) > 2000 for v in value.values()):
        raise ValueError('decision values must be bounded strings')
    if action == 'final' and not value['answer'].strip():
        raise ValueError('answer must not be empty')
    if action in {'search', 'read'} and not value['query' if action == 'search' else 'id'].strip():
        raise ValueError('tool argument must not be empty')
    return value


def run(task: Task, decide: Callable, *, max_turns=4, max_tools=3):
    """The policy chooses; this runtime validates, executes and stops."""
    if type(max_turns) is not int or not 1 <= max_turns <= 8:
        raise ValueError('max_turns must be 1..8')
    if type(max_tools) is not int or not 0 <= max_tools <= 6:
        raise ValueError('max_tools must be 0..6')
    docs, trace, seen, observations = Documents(), [], {}, []
    tools = 0
    for turn in range(1, max_turns + 1):
        try:
            decision = validate_decision(decide(task, list(observations)))
        except (ValueError, TypeError, KeyError) as error:
            return {'stop': 'invalid_decision', 'detail': str(error), 'trace': trace,
                    'turns': turn, 'tool_calls': tools}
        except OSError as error:
            return {'stop': 'provider_error', 'detail': type(error).__name__, 'trace': trace,
                    'turns': turn, 'tool_calls': tools}
        action = decision['action']
        if action == 'final':
            citation = decision['citation']
            # A citation is accepted only after that page was read in this run.
            if citation and citation not in seen:
                return {'stop': 'unread_citation', 'trace': trace, 'turns': turn,
                        'tool_calls': tools}
            trace.append({'turn': turn, 'decision': decision})
            return {'stop': 'final', 'answer': decision['answer'], 'citation': citation,
                    'trace': trace, 'turns': turn, 'tool_calls': tools}
        if tools == max_tools:
            return {'stop': 'tool_limit', 'trace': trace, 'turns': turn,
                    'tool_calls': tools}
        try:
            if action == 'search':
                result = docs.search(decision['query'], task.version, expand=True, top_k=2)
            else:
                result = docs.read(decision['id'], task.version)
                seen[result['id']] = result
        except ValueError as error:
            result = {'error': str(error)}
        tools += 1
        observations.append({'action': action, 'result': result})
        trace.append({'turn': turn, 'decision': decision, 'result': result})
    return {'stop': 'turn_limit', 'trace': trace, 'turns': max_turns,
            'tool_calls': tools}


def scripted(task, observations):
    """A transparent offline policy for testing the loop, not a model."""
    if not observations:
        return {'action': 'search', 'query': task.question}
    last = observations[-1]
    if last['action'] == 'search':
        hits = last['result']
        if not hits:
            return {'action': 'final', 'answer': 'No matching page was found.', 'citation': ''}
        return {'action': 'read', 'id': hits[0]['id']}
    page = last['result']
    if 'error' in page:
        return {'action': 'final', 'answer': page['error'], 'citation': ''}
    return {'action': 'final', 'answer': page['command'], 'citation': page['id']}


def task_from(case):
    return Task(**{k: case[k] for k in ('id', 'family', 'question', 'version')})


def outcome(case, result):
    """Independent task expectation; a final stop alone never passes."""
    return (result.get('stop') == 'final'
            and result.get('citation') == case['expected_doc']
            and result.get('answer') == case['expected_command'])
