"""Replay the recorded Gemini drafts and reviews through the real workflow; no API key needed."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk import Workflow

from harness import ReplayLlm, run
from review_gate import build_workflow
from importlib import import_module
historical_workflow = import_module("review_gate").build_workflow

HERE = Path(__file__).parent
logging.getLogger("google_adk").setLevel(logging.CRITICAL)
RECORD = json.loads((HERE / "review-run.json").read_text())
RUNS = {(r["changelog"], r["style"], r["version_in_facts"]): r for r in RECORD["runs"]}


def replay(calls):
    return ReplayLlm(model=RECORD["environment"]["model"], calls=copy.deepcopy(calls))


def announce(recorded, calls=None):
    workflow = historical_workflow(replay(calls or recorded["model_calls"]),
                              recorded["style"], recorded["version_in_facts"])
    return asyncio.run(run(workflow, (HERE / recorded["changelog"]).read_text()))[0]


class GenerateAndReview(unittest.TestCase):
    def test_replay_matches_every_recorded_run(self):
        for recorded in RECORD["runs"]:
            with self.subTest(recorded["changelog"], style=recorded["style"]):
                self.assertEqual(announce(recorded), recorded["events"])

    def test_the_upbeat_draft_is_rejected_and_never_published(self):
        events = RUNS[("changelog-3.5.0.md", "upbeat", True)]["events"]
        self.assertEqual([e.get("route") for e in events if "route" in e], ["reject"])
        self.assertTrue(events[-1]["message"].startswith("REJECTED"))
        self.assertNotIn("APPROVED", json.dumps(events))

    def test_the_factual_drafts_are_approved(self):
        for changelog in ["changelog-3.5.0.md", "changelog-3.4.0.md"]:
            events = RUNS[(changelog, "factual", True)]["events"]
            self.assertTrue(events[-1]["message"].startswith("APPROVED"), changelog)

    def test_a_reviewer_without_the_version_rejects_a_true_sentence(self):
        events = RUNS[("changelog-3.4.0.md", "factual", False)]["events"]
        self.assertEqual(events[-1]["message"].splitlines()[1:],
                         ["- docuctl version 3.4.0 is now available."])

    def test_an_approval_that_lists_findings_is_overruled(self):
        recorded = RUNS[("changelog-3.5.0.md", "factual", True)]
        calls = copy.deepcopy(recorded["model_calls"])
        calls[1]["reply"]["content"]["parts"][0]["text"] = json.dumps(
            {"verdict": "approve", "unsupported": ["docuctl 3.5.0 is twice as fast."]})
        events = announce(recorded, calls)
        self.assertEqual(events[-2]["route"], "reject")
        self.assertIn("twice as fast", events[-1]["message"])

    def test_a_changelog_without_a_heading_stops_before_the_model(self):
        model = replay([])
        with self.assertRaisesRegex(ValueError, "must start with a '## <version>' heading"):
            asyncio.run(run(build_workflow(model), "- Add a flag\n"))

    def test_a_reviewer_run_without_the_state_it_templates_fails(self):
        reviewer = build_workflow(replay([])).graph.nodes
        review = next(n for n in reviewer if n.name == "review_announcement")
        alone = Workflow(name="review_only", edges=[("START", review)])
        draft = json.dumps({"title": "docuctl 3.5.0", "body": "It is out."})
        with self.assertRaisesRegex(KeyError, "Context variable not found: `changelog`"):
            asyncio.run(run(alone, draft))


class CurrentDocuctlGate(unittest.TestCase):
    def test_current_gate_refuses_findings_even_with_approve_verdict(self):
        from review_gate import gate,Review
        event=gate(Review(verdict="approve",unsupported=["Unstated claim"]),{"title":"docuctl","body":"Unstated claim"})
        self.assertEqual(event.actions.route,"reject")
    def test_current_parser_adds_the_current_cli_version_fact(self):
        from review_gate import parse_changelog
        event=parse_changelog("## 3.5.0\n- Add a flag")
        self.assertIn("docuctl 3.5.0",event.actions.state_delta["changelog"] if hasattr(event,"actions") else event.state["changelog"])

if __name__ == "__main__":
    unittest.main()
