"""Show what happens when a request is longer than the context window. Python 3.11+.

    python3 context_probe.py            # replay the recorded answer
    python3 context_probe.py --record   # ask the local Ollama server

Sends 1,500 numbered words with num_ctx set to 512 and asks for the first
word. The recorded answer is not the first word, the reply still ends with
done_reason "stop", and no error is returned. rag.check() therefore treats a
reply whose prompt and output reach num_ctx as incomplete.
"""
import argparse
import json
from pathlib import Path

from answer_model import AnswerModel
from rag import check

ROOT = Path(__file__).resolve().parent
WORDS = 1500
NUM_CTX = 512


def probe(mode='replay'):
    manifest = json.loads((ROOT / 'model-manifest.json').read_text())
    options = {**manifest['generation_options'], 'num_ctx': NUM_CTX, 'num_predict': 20}
    model = AnswerModel(manifest['vision'], options, ROOT / 'answer-recordings.json', mode)
    user = ' '.join(f'word{i}' for i in range(WORDS)) + '\nWhat is the first word above? Answer with that word only.'
    reply = model.chat('Answer briefly.', user, [], None)
    status, _, flags = check(reply, {}, NUM_CTX)
    return {'words_sent': WORDS, 'first_word': 'word0', 'num_ctx': NUM_CTX, 'answer': reply['text'].strip(),
            'prompt_tokens_reported': reply['prompt_tokens'], 'done_reason': reply['done_reason'],
            'check_status': status, 'check_flags': flags}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    result = probe('record' if args.record else 'replay')
    (ROOT / 'context-probe.json').write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
