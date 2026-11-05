"""Send one docs question to a local model (Ollama) and a hosted API (Gemini). Run: python ask_both.py
Needs Ollama with gemma4:e2b pulled, and GOOGLE_API_KEY in the environment for the hosted call."""
import os
import time
from pathlib import Path

import ollama
from google import genai
from google.genai import types

SYSTEM = "Answer from this docuctl page only, in one sentence.\n\n" + (Path(__file__).parent / "docs/rollback.md").read_text()
QUESTION = "Does a rollback undo database migrations?"


def ask_local(question: str, model: str = "gemma4:e2b") -> dict:
    start = time.perf_counter()
    reply = ollama.chat(model=model, think=False, options={"temperature": 0},
                        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}])
    return {"where": f"local {model}", "seconds": round(time.perf_counter() - start, 2),
            "prompt_tokens": reply.prompt_eval_count, "output_tokens": reply.eval_count,
            "answer": reply.message.content.strip()}


def ask_hosted(question: str, model: str | None = None) -> dict:
    model = model or os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    client = genai.Client()  # reads GOOGLE_API_KEY
    start = time.perf_counter()
    reply = client.models.generate_content(
        model=model, contents=question,
        config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0))
    usage = reply.usage_metadata
    return {"where": f"hosted {model}", "seconds": round(time.perf_counter() - start, 2),
            "prompt_tokens": usage.prompt_token_count, "output_tokens": usage.candidates_token_count,
            "thinking_tokens": usage.thoughts_token_count, "answer": reply.text.strip()}


def main() -> None:
    for result in (ask_local(QUESTION), ask_hosted(QUESTION)):
        print(result)


if __name__ == "__main__":
    main()
