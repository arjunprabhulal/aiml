"""Run the generation loop one token at a time and record the model's top candidates.
Run: python generation_loop.py"""
import json
import math
from pathlib import Path

import ollama

MODEL = "gemma4:e2b"
HERE = Path(__file__).parent
PROMPT = "To roll back production to release r41, run:\n\n    docuctl"


def step(client: ollama.Client, text: str, top: int = 3) -> dict:
    """One forward pass: score the next token, pick the most likely one (temperature 0)."""
    reply = client.generate(model=MODEL, prompt=text, raw=True, logprobs=True, top_logprobs=top,
                            options={"temperature": 0, "num_predict": 1})
    if not reply.logprobs:  # the model chose its end-of-sequence token, so nothing new was generated
        return {"chosen": "", "candidates": [], "done_reason": reply.done_reason}
    scored = reply.logprobs[0]
    return {"chosen": scored.token,
            "candidates": [(c.token, round(math.exp(c.logprob), 3)) for c in scored.top_logprobs]}


def generate(client: ollama.Client, context: str, steps: int = 8, stop: str = "\n") -> list[dict]:
    """Append each chosen token to the context and score again, until the stop text or the step limit."""
    trace = []
    for _ in range(steps):
        result = step(client, context)
        trace.append(result)
        if not result["chosen"] or stop in result["chosen"]:
            break
        context += result["chosen"]
    return trace


def show(label: str, trace: list[dict]) -> None:
    print(f"--- {label}")
    for i, row in enumerate(trace, 1):
        others = "  ".join(f"{token!r} {p:.3f}" for token, p in row["candidates"]) or "(end of sequence)"
        print(f"{i}. chose {row['chosen']!r:<12} candidates: {others}")
    print("text:", "docuctl" + "".join(row["chosen"] for row in trace).rstrip())


def main() -> None:
    client = ollama.Client()
    page = (HERE / "docs/rollback.md").read_text()
    runs = {"without docs": generate(client, PROMPT),
            "with rollback.md": generate(client, f"{page}\n\n{PROMPT}")}
    for label, trace in runs.items():
        show(label, trace)
    output = HERE / "runs/local-docuctl"
    output.mkdir(parents=True, exist_ok=True)
    (output / "trace.json").write_text(json.dumps(runs, indent=1) + "\n")


if __name__ == "__main__":
    main()
