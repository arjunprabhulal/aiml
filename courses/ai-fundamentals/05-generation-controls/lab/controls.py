"""Sampling, output limits and streaming against a local model. Run: python controls.py"""
import time

import httpx
import ollama

MODEL = "gemma4:e2b"
TASK = "Write a one-line commit message for a change that adds a --dry-run flag to `docuctl rollback`."
EXPLAIN = "Explain in about 150 words what `docuctl rollback --env production --to r41` does and when to use it."


def complete(client: ollama.Client, prompt: str, **options) -> tuple[str, str]:
    reply = client.chat(model=MODEL, messages=[{"role": "user", "content": prompt}], think=False, options=options)
    return reply.message.content.strip(), reply.done_reason


def stream(client: ollama.Client, prompt: str) -> dict:
    """Count content chunks and time the first one against the whole reply."""
    start, first, chunks = time.perf_counter(), None, 0
    for chunk in client.chat(model=MODEL, messages=[{"role": "user", "content": prompt}], think=False,
                             stream=True, options={"temperature": 0, "num_predict": 400}):
        if chunk.message.content:
            first = time.perf_counter() - start if first is None else first
            chunks += 1
        if chunk.done:
            return {"chunks": chunks, "first_chunk_s": None if first is None else round(first, 2),
                    "total_s": round(time.perf_counter() - start, 2), "done_reason": chunk.done_reason}

    raise RuntimeError("stream ended without a final status; reply is incomplete")


def main() -> None:
    client = ollama.Client()
    print("temperature 0, three runs:")
    for _ in range(3):
        print("  ", complete(client, TASK, temperature=0)[0])
    print("temperature 1.0, seeds 1-3:")
    for seed in (1, 2, 3):
        print("  ", complete(client, TASK, temperature=1.0, seed=seed)[0])
    print("temperature 1.0, seed 1 again:\n  ", complete(client, TASK, temperature=1.0, seed=1)[0])

    text, reason = complete(client, EXPLAIN, temperature=0, num_predict=40)
    print(f"\nnum_predict=40 -> done_reason={reason!r}\n   ...{text[-60:]!r}")

    print("\nstreaming:", stream(client, EXPLAIN))

    try:  # a client timeout shorter than the generation
        complete(ollama.Client(timeout=0.5), EXPLAIN, temperature=0, num_predict=200)
    except httpx.ReadTimeout as error:
        print("timeout=0.5s ->", type(error).__name__, error)


if __name__ == "__main__":
    main()
