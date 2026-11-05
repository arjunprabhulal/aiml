"""Offline tests: a fake client records what each request carried. Run: python -m pytest -q"""
import re
from pathlib import Path
from types import SimpleNamespace

from chat_context import BUILD_LOG, SYSTEM, chat


class FakeClient:
    def __init__(self):
        self.sent = []

    def chat(self, model, messages, think, options):
        self.sent.append({"messages": [dict(m) for m in messages], "options": options})
        return SimpleNamespace(message=SimpleNamespace(content="ok"), prompt_eval_count=10)


def test_a_request_carries_only_the_messages_you_pass():
    client = FakeClient()
    chat(client, [SYSTEM, {"role": "user", "content": "q"}])
    assert [m["role"] for m in client.sent[0]["messages"]] == ["system", "user"]


def test_the_context_size_is_set_explicitly():
    client = FakeClient()
    chat(client, [SYSTEM], num_ctx=4096)
    assert client.sent[0]["options"]["num_ctx"] == 4096


def test_the_system_message_holds_every_docs_page():
    assert all(title in SYSTEM["content"] for title in ("# Configure docuctl", "# Roll back a release", "# Authenticate docuctl in CI"))
    assert BUILD_LOG.splitlines()[-1] == "compiled module m399 in 0.9s"


def recorded():
    return Path(__file__).with_name("run-output.txt").read_text()


def test_without_history_the_model_falls_back_to_the_docs_example():
    lines = dict(line.split(": ", 1) for line in recorded().splitlines())
    with_history = next(v for k, v in lines.items() if k.startswith("turn 2 (")).strip("`")
    without = next(v for k, v in lines.items() if k.startswith("turn 2 without"))
    assert "ci-search-api" in with_history and "ci-docs-api" in without


def test_a_small_context_dropped_the_build_log_without_an_error():
    runs = {n: (int(t), a) for n, t, a in re.findall(r"num_ctx=(\d+) \((\d+) prompt tokens\): (.+)", recorded())}
    assert runs["16384"] == (5579, "m399")
    assert runs["4096"][0] < 4096 and "m399" not in runs["4096"][1]
