"""Inspect a local model, then run inference with and without the docuctl docs. Run: python inference.py"""
from pathlib import Path

import ollama

MODEL = "gemma4:e2b"
QUESTION = "What does `docuctl rollback --to r41` do? Answer in two sentences."
DOCS = Path(__file__).parent / "docs"


def describe(client: ollama.Client, model: str = MODEL) -> dict:
    """The facts about the weight file that matter to an application."""
    info = client.show(model)
    return {
        "family": info.details.family,
        "parameters": info.details.parameter_size,
        "quantization": info.details.quantization_level,
        "context_length": info.modelinfo[f"{info.details.family}.context_length"],
    }


def ask(client: ollama.Client, question: str, page: str | None = None, model: str = MODEL) -> str:
    """One inference request. The page, if any, travels in the prompt; the weights never change."""
    prompt = question if page is None else f"Answer from this page only.\n\n{page}\n\nQuestion: {question}"
    reply = client.chat(model=model, messages=[{"role": "user", "content": prompt}],
                        think=False, options={"temperature": 0, "seed": 7})
    return reply.message.content.strip()


def main() -> None:
    client = ollama.Client()
    for key, value in describe(client).items():
        print(f"{key:<15} {value}")
    print("\n--- without the docs")
    print(ask(client, QUESTION))
    print("\n--- with docs/rollback.md in the prompt")
    print(ask(client, QUESTION, (DOCS / "rollback.md").read_text()))


if __name__ == "__main__":
    main()
