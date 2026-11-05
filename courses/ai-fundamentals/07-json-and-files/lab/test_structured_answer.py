"""Offline tests for the schema and the request. Run: python -m pytest -q"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from structured_answer import DocsAnswer, ask

RECORDED = Path(__file__).with_name("run-output.txt").read_text()
GOOD = json.loads(RECORDED.split("\n\n")[0])


class FakeClient:
    def __init__(self, content):
        self.content, self.request = content, None

    def chat(self, **request):
        self.request = request
        return SimpleNamespace(message=SimpleNamespace(content=self.content))


def test_the_recorded_answer_validates():
    assert DocsAnswer.model_validate(GOOD).source == "rollback.md"


def test_the_json_schema_is_sent_as_the_format():
    client = FakeClient(json.dumps(GOOD))
    ask(client, "q")
    assert client.request["format"]["properties"]["source"]["enum"] == ["config.md", "deploy.md", "rollback.md", "tokens.md"]


def test_a_page_that_does_not_exist_is_rejected():
    with pytest.raises(ValidationError) as error:
        DocsAnswer.model_validate({**GOOD, "source": "rollbacks.md"})
    assert error.value.errors()[0]["type"] == "literal_error"


def test_prose_instead_of_json_is_rejected():
    with pytest.raises(ValidationError, match="json_invalid"):
        ask(FakeClient("To roll back production, run docuctl rollback."), "q", schema=False)


def test_a_reply_cut_off_by_the_output_limit_is_rejected():
    with pytest.raises(ValidationError, match="EOF while parsing"):
        ask(FakeClient('{\n  "answer": "To roll back production to release r41, you w'), "q", num_predict=20)


def test_valid_json_can_still_leave_out_what_you_needed():
    answer = DocsAnswer.model_validate(GOOD)
    assert answer.command is None and "docuctl rollback --env production --to r41" in answer.answer
