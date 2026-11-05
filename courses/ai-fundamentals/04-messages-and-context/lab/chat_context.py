"""Send chat messages to a local model and watch what fits in the context window. Run: python chat_context.py"""
from pathlib import Path

import ollama

MODEL = "gemma4:e2b"
DOCS = "\n\n".join(page.read_text() for page in sorted((Path(__file__).parent / "docs").glob("*.md")))
SYSTEM = {"role": "system", "content": f"You answer questions about docuctl. Use only these docs:\n\n{DOCS}"}
BUILD_LOG = "\n".join(f"compiled module m{i} in 0.{i % 10}s" for i in range(400))


def chat(client: ollama.Client, messages: list[dict], num_ctx: int = 16384) -> tuple[str, int]:
    """Submit this message history; the runtime may truncate an oversized request."""
    reply = client.chat(model=MODEL, messages=messages, think=False,
                        options={"temperature": 0, "num_ctx": num_ctx, "num_predict": 80})
    return reply.message.content.strip(), reply.prompt_eval_count


def main() -> None:
    client = ollama.Client()
    history = [SYSTEM, {"role": "user", "content": "Our service is named search-api. Which environment variable holds its CI deploy token?"}]
    answer, used = chat(client, history)
    print(f"turn 1 ({used} prompt tokens): {answer}")

    history += [{"role": "assistant", "content": answer},
                {"role": "user", "content": "Write the command that creates that token for our service, scoped to staging. Command only."}]
    answer, used = chat(client, history)
    print(f"turn 2 ({used} prompt tokens): {answer}")

    answer, used = chat(client, [SYSTEM, history[-1]])
    print(f"turn 2 without the history ({used} prompt tokens): {answer}")

    long = [SYSTEM, {"role": "user", "content": f"My build log:\n{BUILD_LOG}"},
            {"role": "assistant", "content": "Noted."},
            {"role": "user", "content": "Which module did my build log compile last? Reply with the module name only."}]
    for num_ctx in (16384, 4096):
        answer, used = chat(client, long, num_ctx)
        print(f"build log, num_ctx={num_ctx} ({used} prompt tokens): {answer}")


if __name__ == "__main__":
    main()
