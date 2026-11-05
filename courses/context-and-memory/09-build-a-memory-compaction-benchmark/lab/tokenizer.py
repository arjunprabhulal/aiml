"""Count tokens with the pinned Gemma 4 E2B tokenizer and chat template.

Loads tokenizer files only, never model weights. The same files and pins as
the context budget build. count_request() counts a complete request as the
template renders it, with the generation prefix; count_text() counts one
piece of text without special tokens.
"""
import hashlib
import json
import os
from pathlib import Path
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / 'tokenizer-manifest.json').read_text())


class GemmaCounter:
    def __init__(self):
        local = Path(os.environ.get('TOKENIZER_PATH', ROOT / '.tokenizer'))
        for name, expected in MANIFEST['files'].items():
            path = local / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f'Tokenizer file missing or changed: {name}. Run prepare.py.')
        self.tokenizer = AutoTokenizer.from_pretrained(local, local_files_only=True, trust_remote_code=False)

    def count_request(self, messages: list[dict], tools: list[dict] = ()) -> int:
        # The Gemma template needs tool-call arguments as a mapping, not the
        # JSON string that chat-completions APIs use; convert a copy for counting.
        rendered = [dict(m, tool_calls=[{**c, 'function': {**c['function'],
                                                            'arguments': json.loads(c['function']['arguments'])}}
                                        for c in m['tool_calls']])
                    if m.get('tool_calls') else m for m in messages]
        return len(self.tokenizer.apply_chat_template(
            rendered, tools=list(tools) or None, tokenize=True, add_generation_prompt=True,
            enable_thinking=False, return_dict=False))

    def count_text(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def profile(self) -> dict:
        return {'model': MANIFEST['model'], 'revision': MANIFEST['revision'],
                'template_sha256': MANIFEST['files']['chat_template.jinja'], 'enable_thinking': False,
                'count_scope': 'chat template with generation prefix; tokenizer files only, no inference'}


_COUNTER = None


def counter() -> GemmaCounter:
    global _COUNTER
    if _COUNTER is None:
        _COUNTER = GemmaCounter()
    return _COUNTER


def count_request(messages: list[dict], tools: list[dict] = ()) -> int:
    return counter().count_request(messages, tools)


def count_text(text: str) -> int:
    return counter().count_text(text)


if __name__ == '__main__':
    print(json.dumps(counter().profile(), indent=2))
