"""Answer a question from page and figure sources, then check every citation. Python 3.11+.

    python3 rag.py "Which model size has the lowest p95 latency?"
    python3 rag.py --mode text "Which model size has the lowest p95 latency?"
    python3 rag.py --record "..."      # ask the local Ollama server for anything not recorded

Steps: retrieve the top sources, label them S1..Sk, send page text and
figure images (or, in text mode, figure descriptions) to the model, and
check the reply: every claim must cite a supplied label, quote words that
appear in that source, and point at pixels that still match their hashes.
"""
import argparse
import json
import math
from pathlib import Path

from answer_model import AnswerModel
from embed_model import Embedder
from pngio import decode_png
from sources import SourceError, load_sources, resolve, search_text

ROOT = Path(__file__).resolve().parent
TOP_K = 4
MODES = ('images', 'text')
SYSTEM = ('Answer the question using only the numbered sources. Reply in JSON with the keys answer, claims and '
          'not_in_sources. answer is one short sentence. Each claim has text, source (a label such as S1) and quote: '
          'words copied exactly from that source; for an image source, copy words printed in the image. '
          'If the sources do not answer the question, set not_in_sources to true, give an empty claims list, '
          'and say so in answer.')
SCHEMA = {'type': 'object', 'required': ['answer', 'claims', 'not_in_sources'],
          'properties': {'answer': {'type': 'string'}, 'not_in_sources': {'type': 'boolean'},
                         'claims': {'type': 'array', 'items': {'type': 'object', 'required': ['text', 'source', 'quote'],
                                                               'properties': {'text': {'type': 'string'},
                                                                              'source': {'type': 'string'},
                                                                              'quote': {'type': 'string'}}}}}}


def flat(text):
    return ' '.join(text.split())


def retrieve(embedder, sources, question, k=TOP_K):
    """Exact cosine over every source; ties keep source order."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError('The question must contain text.')
    query = embedder.query(question)
    scored = [(math.fsum(a * b for a, b in zip(query, embedder.document(search_text(s)))), i, s)
              for i, s in enumerate(sources)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(s, round(score, 6)) for score, _, s in scored[:k]]


def assemble(question, ranked, mode, root=ROOT):
    """Label sources S1..Sk. In images mode a figure is sent as its image, not as its description."""
    if mode not in MODES:
        raise ValueError(f'mode must be one of {", ".join(MODES)}.')
    parts, images, labels = [], [], {}
    for n, (source, _) in enumerate(ranked, 1):
        label = f'S{n}'
        # A quote is checked against the words the model was given for this source:
        # the page text, the figure's printed words (images mode) or its whole text (text mode).
        shown = source['text'] if source['kind'] == 'page' or mode == 'text' else source['printed_text']
        labels[label] = {**source, 'shown_text': shown}
        if source['kind'] == 'page':
            parts.append(f'[{label}] page text from {source["id"]}, page {", ".join(map(str, source["pages"]))}:\n{source["text"]}')
        elif mode == 'images':
            images.append(decode_png((Path(root) / source['image']).read_bytes()))
            parts.append(f'[{label}] figure {source["id"]}: image {len(images)} attached.')
        else:
            parts.append(f'[{label}] figure {source["id"]}, described in words:\n{source["text"]}')
    user = 'Sources:\n\n' + '\n\n'.join(parts) + f'\n\nQuestion: {question}'
    return user, images, labels


def check(reply, labels, num_ctx, root=ROOT):
    """Return (status, parsed, flags). status is verified, flagged or incomplete.

    incomplete: the reply is not the requested JSON, stopped at the output limit, or the request
    filled the context window. flagged: a claim cites an unknown label, quotes words its source does
    not contain, or cites a source whose pixels changed; or the reply has no claims and does not say
    the sources lack the answer; or it says so and still makes claims.
    """
    if reply['done_reason'] != 'stop':
        return 'incomplete', None, ['output_cut_off']
    if reply['prompt_tokens'] is None or reply['prompt_tokens'] + (reply['output_tokens'] or 0) >= num_ctx:
        return 'incomplete', None, ['context_window_full']
    try:
        parsed = json.loads(reply['text'])
        claims = parsed['claims']
        ok = (isinstance(parsed['answer'], str) and isinstance(parsed['not_in_sources'], bool)
              and isinstance(claims, list) and all(isinstance(c, dict) and all(isinstance(c.get(f), str)
                                                                              for f in ('text', 'source', 'quote'))
                                                   for c in claims))
    except (json.JSONDecodeError, KeyError, TypeError):
        ok = False
    if not ok:
        return 'incomplete', None, ['not_the_requested_json']
    flags = []
    if parsed['not_in_sources'] and claims:
        flags.append('claims_without_an_answer')
    if not parsed['not_in_sources'] and not claims:
        flags.append('answer_without_citations')
    for n, claim in enumerate(claims, 1):
        source = labels.get(claim['source'].strip().strip('[]'))
        if source is None:
            flags.append(f'claim_{n}_cites_unknown_source')
            continue
        if not claim['quote'].strip() or flat(claim['quote']) not in flat(source['shown_text']):
            flags.append(f'claim_{n}_quote_not_in_source')
        try:
            resolve(source, root)
        except SourceError:
            flags.append(f'claim_{n}_source_pixels_changed')
    return ('flagged' if flags else 'verified'), parsed, flags


def answer(question, mode, embedder, model, sources, root=ROOT):
    ranked = retrieve(embedder, sources, question)
    user, images, labels = assemble(question, ranked, mode, root)
    reply = model.chat(SYSTEM, user, images, SCHEMA)
    status, parsed, flags = check(reply, labels, model.options['num_ctx'], root)
    return {'question': question, 'mode': mode,
            'retrieved': [{'label': label, 'id': s['id'], 'kind': s['kind'], 'score': score}
                          for (label, s), (_, score) in zip(labels.items(), ranked)],
            'status': status, 'flags': flags, 'reply': parsed, 'raw': None if parsed else reply['text'],
            'model': {k: reply[k] for k in ('prompt_tokens', 'output_tokens', 'total_ms')}}


def models(mode):
    manifest = json.loads((ROOT / 'model-manifest.json').read_text())
    return (Embedder(manifest['embedding'], ROOT / 'embed-recordings.json', mode),
            AnswerModel(manifest['vision'], manifest['generation_options'], ROOT / 'answer-recordings.json', mode))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('question')
    parser.add_argument('--mode', default='images', choices=MODES)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    embedder, model = models('record' if args.record else 'replay')
    result = answer(args.question, args.mode, embedder, model, load_sources())
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
