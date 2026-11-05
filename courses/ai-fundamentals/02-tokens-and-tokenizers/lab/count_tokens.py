"""Count tokens in docuctl docs text with Gemma's own tokenizer. Run: TOKENIZER_PATH=... python count_tokens.py"""
import os
import sys
from pathlib import Path

from tokenizers import Tokenizer

HERE = Path(__file__).parent
SAMPLES = {
    "prose": "docuctl rollback moves an environment back to an earlier release.",
    "command": "docuctl rollback --env production --to r41",
    "config": '[service]\nname = "docs-api"\nbuild = "make build"',
    "id": "ci-docs-api-2026-10-21T09:14:03Z",
    "page": (HERE / "docs/rollback.md").read_text(),
}


def load(folder: str | None = None) -> Tokenizer:
    path = Path(folder or os.environ.get("TOKENIZER_PATH", "gemma-tokenizer")) / "tokenizer.json"
    if not path.is_file():
        sys.exit(f"no tokenizer.json in {path.parent}; set TOKENIZER_PATH to the Gemma tokenizer folder")
    return Tokenizer.from_file(str(path))


def count(tokenizer: Tokenizer, text: str) -> int:
    """Tokens in the raw text, without the BOS token a runtime adds in front."""
    return len(tokenizer.encode(text, add_special_tokens=False).ids)


def pieces(tokenizer: Tokenizer, text: str) -> list[tuple[str, int]]:
    encoding = tokenizer.encode(text, add_special_tokens=False)
    return list(zip(encoding.tokens, encoding.ids))


def main() -> None:
    tokenizer = load()
    print(f"vocabulary size {tokenizer.get_vocab_size()}\n")
    print(f"{'sample':<8} {'chars':>5} {'words':>5} {'tokens':>6}")
    for name, text in SAMPLES.items():
        print(f"{name:<8} {len(text):>5} {len(text.split()):>5} {count(tokenizer, text):>6}")
    print("\npieces of the command:")
    for piece, token_id in pieces(tokenizer, SAMPLES["command"]):
        print(f"  {piece!r:<14} {token_id}")


if __name__ == "__main__":
    main()
