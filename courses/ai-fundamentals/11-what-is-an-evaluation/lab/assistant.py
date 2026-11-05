"""The docs assistant under test: the typed-answer code from the structured output lesson."""
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


class DocsAnswerV2(DocsAnswer):
    """Version 2: the assistant may say that no page covers the question."""
    source: Page | None = Field(description="The docs page the answer comes from, or null if no page covers it.")


NULL_RULE = " If no page answers the question, set source to null and say that the docs do not cover it."


def prompt(question: str, rules: str = "") -> list[dict]:
    pages = "\n\n".join(f"<page name={name!r}>\n{text}</page>" for name, text in DOCS.items())
    return [{"role": "system", "content": f"Answer from these docuctl docs pages.{rules}\n\n{pages}"},
            {"role": "user", "content": question}]


def ask(client: ollama.Client, question: str, schema: bool = True, num_predict: int = 300,
        answer_type: type[DocsAnswer] = DocsAnswer, rules: str = "", **options) -> DocsAnswer:
    """With schema=True the runtime constrains decoding to the JSON schema; Pydantic still checks the result."""
    reply = client.chat(model=MODEL, messages=prompt(question, rules), think=False,
                        format=answer_type.model_json_schema() if schema else None,
                        options={"temperature": 0, "num_predict": num_predict, **options})
    return answer_type.model_validate_json(reply.message.content)
