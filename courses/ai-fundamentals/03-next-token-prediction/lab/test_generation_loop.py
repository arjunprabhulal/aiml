"""Offline tests: a fake client replays the recorded steps. Run: python -m pytest -q"""
import json
import math
from pathlib import Path
from types import SimpleNamespace

from generation_loop import PROMPT, generate

TRACE = json.loads(Path(__file__).with_name("trace.json").read_text())


class Replay:
    """Returns the recorded token for each step and remembers every context it was sent."""
    def __init__(self, steps):
        self.steps, self.prompts = list(steps), []

    def generate(self, prompt, **_):
        self.prompts.append(prompt)
        row = self.steps.pop(0)
        if not row["chosen"]:
            return SimpleNamespace(logprobs=None, done_reason="stop")
        top = [SimpleNamespace(token=t, logprob=math.log(max(p, 1e-9))) for t, p in row["candidates"]]
        return SimpleNamespace(logprobs=[SimpleNamespace(token=row["chosen"], top_logprobs=top)])


def test_each_chosen_token_is_appended_before_the_next_step():
    client = Replay(TRACE["without docs"])
    trace = generate(client, PROMPT)
    assert client.prompts[1] == PROMPT + trace[0]["chosen"]
    assert client.prompts[-1] == PROMPT + "".join(row["chosen"] for row in trace[:-1])


def test_the_loop_stops_at_end_of_sequence():
    trace = generate(Replay(TRACE["without docs"]), PROMPT)
    assert trace[-1]["chosen"] == "" and len(trace) == 5


def test_the_step_limit_can_cut_a_command_short():
    trace = generate(Replay(TRACE["with rollback.md"]), "ctx", steps=8)
    assert len(trace) == 8 and "".join(row["chosen"] for row in trace).endswith("--to r4")


def test_a_confident_guess_without_docs_has_the_wrong_syntax():
    text = "".join(row["chosen"] for row in TRACE["without docs"])
    first_choice = TRACE["without docs"][1]["candidates"][0]
    assert text == " rollback r41" and "--env" not in text and first_choice == [" r", 0.714]


def test_fresh_trace_leaves_original_recording_unchanged(tmp_path, monkeypatch):
    import generation_loop as app
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/rollback.md").write_text("current docuctl manual")
    original = tmp_path / "trace.json"
    original.write_text("original recording")
    monkeypatch.setattr(app, "HERE", tmp_path)
    monkeypatch.setattr(app.ollama, "Client", lambda: object())
    monkeypatch.setattr(app, "generate", lambda *_args: [])
    app.main()
    assert original.read_text() == "original recording"
    assert json.loads((tmp_path / "runs/local-docuctl/trace.json").read_text()) == {"without docs": [], "with rollback.md": []}
