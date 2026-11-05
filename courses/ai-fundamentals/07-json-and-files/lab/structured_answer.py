"""Ask for a typed answer and validate it with Pydantic. Run: python structured_answer.py"""
from pathlib import Path
from typing import Literal

import ollama
from pydantic import BaseModel, Field, ValidationError

MODEL = "gemma4:e2b"
DOCS = {page.name: page.read_text() for page in sorted((Path(__file__).parent / "docs").glob("*.md"))}
Page = Literal["config.md", "deploy.md", "rollback.md", "tokens.md"]


class DocsAnswer(BaseModel):
    """What the docs assistant returns to the application."""
    answer: str = Field(min_length=1, max_length=400)
    source: Page = Field(description="The docs page the answer comes from.")
    command: str | None = Field(default=None, description="A docuctl command to run, if the answer has one.")


def prompt(question: str) -> list[dict]:
    pages = "\n\n".join(f"<page name={name!r}>\n{text}</page>" for name, text in DOCS.items())
    return [{"role": "system", "content": f"Answer from these docuctl docs pages.\n\n{pages}"},
            {"role": "user", "content": question}]


def ask(client: ollama.Client, question: str, schema: bool = True, num_predict: int = 300) -> DocsAnswer:
    """With schema=True the runtime constrains decoding to the JSON schema; Pydantic still checks the result."""
    reply = client.chat(model=MODEL, messages=prompt(question), think=False,
                        format=DocsAnswer.model_json_schema() if schema else None,
                        options={"temperature": 0, "num_predict": num_predict})
    return DocsAnswer.model_validate_json(reply.message.content)


def main() -> None:
    client = ollama.Client()
    question = "How do I roll back production to release r41?"
    print(ask(client, question).model_dump_json(indent=2))

    for label, kwargs in [("no schema in the request", {"schema": False}), ("num_predict=20", {"num_predict": 20})]:
        try:
            ask(client, question, **kwargs)
        except ValidationError as error:
            first = error.errors()[0]
            print(f"\n{label} -> {error.error_count()} validation error(s): {first['type']}: {first['msg'][:70]}")
            print("   input started:", repr(str(first["input"])[:60]))


if __name__ == "__main__":
    main()
