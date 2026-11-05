"""Issue triage. TRIAGE_MODEL and TRIAGE_PROMPT select the components under test:
a Gemini model through the API, or any other name (gemma4:e2b) through a local Ollama server."""
import os
from functools import cache
from typing import Literal

from pydantic import BaseModel, Field

MODEL = os.environ.get("TRIAGE_MODEL", "gemini-3.8-flash")
PROMPT_VERSION = os.environ.get("TRIAGE_PROMPT", "v1")
V1 = """You triage GitHub issues for `tracker`, an open-source task-tracker CLI.
Choose one label:
- bug: the program behaves wrongly, crashes, loses data or leaks secrets.
- feature: a request for new behavior.
- docs: the documentation is wrong or missing.
- question: the reporter asks how something works.
Set priority to p0 for data loss or a leaked secret, p1 for other bugs and p2 otherwise.
Write a summary of at most 20 words that keeps the command or file the issue names."""
V2 = V1 + """
Tasks that are dropped, deleted or lost without the user asking count as data loss.
The summary also keeps the reporter's goal when the issue states one."""
PROMPTS = {"v1": V1, "v2": V2}


class Triage(BaseModel):
    label: Literal["bug", "feature", "docs", "question"]
    priority: Literal["p0", "p1", "p2"]
    summary: str = Field(min_length=1)


@cache
def gemini():
    from google import genai
    return genai.Client()  # reads GOOGLE_API_KEY from the environment


def triage(issue: str, model: str = MODEL, prompt: str = PROMPT_VERSION) -> str:
    """Return the model's raw JSON reply; the caller validates it against Triage."""
    if model.startswith("gemini"):
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=PROMPTS[prompt],
            response_mime_type="application/json",
            response_schema=Triage,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        )
        return gemini().models.generate_content(model=model, contents=issue, config=config).text
    from ollama import chat
    response = chat(
        model=model,
        messages=[{"role": "system", "content": PROMPTS[prompt]}, {"role": "user", "content": issue}],
        format=Triage.model_json_schema(),
        options={"temperature": 0, "seed": 7},
        think=False,
    )
    return response.message.content


if __name__ == "__main__":
    import sys
    print(triage(sys.argv[1]))
