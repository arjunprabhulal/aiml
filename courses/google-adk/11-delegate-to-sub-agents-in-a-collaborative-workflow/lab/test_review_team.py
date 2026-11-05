"""Replay the recorded Gemini turns through the real review team; no API key needed."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk import Agent
from pydantic import ValidationError

from harness import ReplayLlm, run
from review_team import build_team, delegations, find_long_sentences

logging.getLogger("google_adk").setLevel(logging.CRITICAL)
HERE = Path(__file__).parent
RECORD = json.loads((HERE / "review-run.json").read_text())
TRANSFER = json.loads((HERE / "review-run-transfer.json").read_text())
MESSAGE = f"Review this docs pull request:\n\n{RECORD['diff']}"


class ToolSeeingReplay(ReplayLlm):
    """A replay model that also keeps the tool names each request declared."""
    tools: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.tools.append(sorted(llm_request.tools_dict))
        async for response in super().generate_content_async(llm_request, stream):
            yield response


def replay(calls=None, cls=ReplayLlm):
    return cls(model=RECORD["environment"]["model"],
               calls=copy.deepcopy(calls or RECORD["model_calls"]))


def review(model):
    return asyncio.run(run(build_team(model), MESSAGE))[0]


def canonical(events):
    return sorted(json.dumps(event, sort_keys=True) for event in events)


class ReviewTeam(unittest.TestCase):
    def test_replay_produces_the_recorded_events(self):
        self.assertEqual(canonical(review(replay())), canonical(RECORD["events"]))

    def test_the_coordinator_calls_both_sub_agents_in_one_turn(self):
        first = RECORD["events"][0]
        self.assertEqual(first["author"], "docs_reviewer")
        self.assertEqual([c["name"] for c in first["calls"]], ["pr_summarizer", "style_checker"])

    def test_isolated_sub_agents_are_not_offered_transfer_to_agent(self):
        model = replay(cls=ToolSeeingReplay)
        review(model)
        offered = {name for names in model.tools for name in names}
        self.assertIn("pr_summarizer", offered)
        self.assertNotIn("transfer_to_agent", offered)

    def test_recorded_transfer_failure_without_isolation(self):
        calls = [(e["author"], c["name"]) for e in TRANSFER["events"] for c in e.get("calls", [])]
        self.assertIn(("pr_summarizer", "transfer_to_agent"), calls)
        errors = [r["response"] for e in TRANSFER["events"] for r in e.get("responses", [])
                  if "Error running sub-agent" in str(r["response"])]
        self.assertTrue(errors)
        self.assertGreater(len(TRANSFER["model_calls"]), len(RECORD["model_calls"]))

    def test_a_sub_agent_can_have_only_one_parent(self):
        team = build_team(replay())
        with self.assertRaisesRegex(ValidationError, "already has a parent agent"):
            Agent(name="second_reviewer", model=team.model, sub_agents=[team.sub_agents[0]])

    def test_a_root_agent_cannot_be_single_turn(self):
        root = Agent(name="solo", model=replay(), mode="single_turn", instruction="Review.")
        with self.assertRaisesRegex(ValueError, "must have mode='chat' or 'task'"):
            asyncio.run(run(root, MESSAGE))

    def test_an_answer_without_delegation_is_detected(self):
        calls = copy.deepcopy(RECORD["model_calls"][:1])
        calls[0]["reply"]["content"]["parts"] = [{"text": "Looks good to me."}]
        events = review(replay(calls))
        self.assertEqual(delegations(events), [])
        self.assertEqual(delegations(RECORD["events"]), ["pr_summarizer", "style_checker"])

    def test_the_style_tool_reads_only_added_lines(self):
        self.assertEqual(len(find_long_sentences(RECORD["diff"])["long_sentences"]), 1)
        self.assertEqual(find_long_sentences("-" + "word " * 40 + ".")["long_sentences"], [])


if __name__ == "__main__":
    unittest.main()
