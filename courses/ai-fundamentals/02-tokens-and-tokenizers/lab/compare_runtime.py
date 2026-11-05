"""Compare local counts with what Ollama actually processed. Run: TOKENIZER_PATH=... python compare_runtime.py"""
import json
from pathlib import Path

import ollama

from count_tokens import SAMPLES, count, load


def processed(client: ollama.Client, model: str, text: str, chat: bool) -> int:
    """prompt_eval_count: the tokens the runtime fed to the model for this request."""
    options = {"num_predict": 1, "temperature": 0}
    if chat:
        reply = client.chat(model=model, messages=[{"role": "user", "content": text}], think=False, options=options)
    else:
        reply = client.generate(model=model, prompt=text, raw=True, options=options)
    return reply.prompt_eval_count


def main() -> None:
    tokenizer, client, rows = load(), ollama.Client(), {}
    print(f"{'sample':<8} {'local':>5} {'gemma raw':>9} {'gemma chat':>10} {'qwen raw':>8}")
    for name, text in SAMPLES.items():
        row = {"local": count(tokenizer, text),
               "gemma_raw": processed(client, "gemma4:e2b", text, chat=False),
               "gemma_chat": processed(client, "gemma4:e2b", text, chat=True),
               "qwen_raw": processed(client, "qwen3.5:0.8b", text, chat=False)}
        rows[name] = row
        print(f"{name:<8} {row['local']:>5} {row['gemma_raw']:>9} {row['gemma_chat']:>10} {row['qwen_raw']:>8}")
    output = Path(__file__).parent / "runs/local-docuctl"
    output.mkdir(parents=True, exist_ok=True)
    (output / "counts.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
