"""Replay the recorded refinement loops, and drive an unbounded cycle with a stub model."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk import Event, Workflow
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.adk.agents.run_config import RunConfig
from google.adk.models import BaseLlm, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from harness import ReplayLlm, run
from refine_entry import Entry, Feedback, MAX_CHARS, MAX_ROUNDS, build_workflow, lint_entry, load_change

HERE = Path(__file__).parent
logging.getLogger("google_adk").setLevel(logging.CRITICAL)
RECORD = json.loads((HERE / "refine-run.json").read_text())
RUNS = {(r["change"], r["reviser_sees_rules"]): r for r in RECORD["runs"]}


def routes(events):
    return [e["route"] for e in events if "route" in e]


class StubLlm(BaseLlm):
    """Always returns the same entry, which never passes the lint."""
    calls: int = 0
    text: str = "Changed things."

    async def generate_content_async(self, llm_request, stream=False):
        self.calls += 1
        yield LlmResponse(content=types.Content(
            role="model", parts=[types.Part(text=json.dumps({"text": self.text}))]))


class IterativeRefinement(unittest.TestCase):
    def test_replay_matches_every_recorded_run(self):
        for recorded in RECORD["runs"]:
            with self.subTest(recorded["change"], sees_rules=recorded["reviser_sees_rules"]):
                model = ReplayLlm(model=RECORD["environment"]["model"],
                                  calls=copy.deepcopy(recorded["model_calls"]))
                workflow = build_workflow(model, recorded["reviser_sees_rules"])
                text = (HERE / recorded["change"]).read_text()
                self.assertEqual(asyncio.run(run(workflow, text))[0], recorded["events"])

    def test_the_rename_converges_after_one_revision(self):
        events = RUNS[("change-rename.txt", True)]["events"]
        self.assertEqual(routes(events), ["revise", "done"])
        self.assertEqual(lint_entry(events[-2]["output"], load_change(
            (HERE / "change-rename.txt").read_text()).output.must_name), [])

    def test_the_config_change_stops_at_the_round_limit(self):
        recorded = RUNS[("change-config.txt", True)]
        self.assertEqual(routes(recorded["events"]), ["revise"] * MAX_ROUNDS + ["limit"])
        self.assertEqual(len(recorded["model_calls"]), 1 + MAX_ROUNDS)
        self.assertTrue(recorded["events"][-1]["message"].startswith("STOPPED"))

    def test_the_config_change_cannot_pass(self):
        names = load_change((HERE / "change-config.txt").read_text()).output.must_name
        shortest = sum(len(name) + 2 for name in names) + len(names) - 1 + len("Add ")
        self.assertGreater(shortest, MAX_CHARS)

    def test_the_recorded_blind_reviser_also_passes_the_lint(self):
        recorded = RUNS[("change-rename.txt", False)]
        self.assertEqual(routes(recorded["events"])[-1], "done")
        text = recorded["events"][-2]["output"]
        names = load_change((HERE / "change-rename.txt").read_text()).output.must_name
        self.assertEqual(lint_entry(text, names), [])

    def test_a_verb_prefix_or_multiline_entry_cannot_pass_the_workflow(self):
        for text in ("Added `flag`", "Fixation `flag`", "Add `flag`\nRemove things"):
            stub = StubLlm(model="stub", text=text)
            events, _ = asyncio.run(run(build_workflow(stub), "Change the flag\nname:flag"))
            self.assertEqual(routes(events)[-1], "limit", text)
            self.assertNotIn("done", routes(events), text)

    def test_a_cycle_without_a_counter_runs_until_max_llm_calls(self):
        stub = StubLlm(model="stub")
        loop = build_workflow(stub)
        nodes = {n.name: n for n in loop.graph.nodes}

        def check_forever(node_input: Entry):  # check_entry without the rounds bound
            return Event(route="revise", output=Feedback(
                entry=node_input.text, problems=lint_entry(node_input.text, [])))

        unbounded = Workflow(name="unbounded", edges=[
            ("START", nodes["load_change"], nodes["write_entry"], check_forever),
            (check_forever, {"revise": nodes["revise_entry"]}),
            (nodes["revise_entry"], check_forever),
        ])
        runner = InMemoryRunner(agent=unbounded, app_name="docs_assistant")

        async def go():
            session = await runner.session_service.create_session(app_name="docs_assistant",
                                                                   user_id="dev")
            message = types.Content(role="user", parts=[types.Part(text="Rename a flag\nname:x")])
            async for _ in runner.run_async(user_id="dev", session_id=session.id,
                                            new_message=message,
                                            run_config=RunConfig(max_llm_calls=6)):
                pass

        with self.assertRaisesRegex(LlmCallsLimitExceededError, "limit of `6` exceeded"):
            asyncio.run(go())
        self.assertEqual(stub.calls, 6)


if __name__ == "__main__":
    unittest.main()
