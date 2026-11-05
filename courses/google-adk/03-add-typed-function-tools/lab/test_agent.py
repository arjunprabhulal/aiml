"""Replay the recorded Gemini turns through the real agent, tools, callback and approval loop.

Run: python -m unittest -v test_agent.py
"""
import asyncio
import copy
from unittest.mock import patch
import json
import logging
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk import Runner  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.adk.tools import FunctionTool  # noqa: E402
from google.genai import types  # noqa: E402

import agent  # noqa: E402
import docs_tools  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
RUNS = {r["scenario"]: r for r in RECORD["runs"]}


class ReplayLlm(BaseLlm):
    """Answers each request with the next recorded model turn and keeps the requests."""
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def replay(scenario: str, **update) -> tuple[dict, ReplayLlm]:
    docs_tools.ISSUES.clear()
    run = RUNS[scenario]
    model = ReplayLlm(model="replay", turns=list(run["model_turns"]), requests=[])
    sessions = InMemorySessionService()
    runner = Runner(app_name="docs", agent=agent.build_agent(model).clone(update=update), session_service=sessions)
    asked = []

    def approve(tool, args):
        asked.append({"tool": tool, "args": args, "approved": run["approve"]})
        return run["approve"]

    async def go():
        session = await sessions.create_session(app_name="docs", user_id="dev")
        events = await agent.ask(runner, session.id, run["prompt"], approve)
        await runner.close()
        return events

    events = asyncio.run(go())
    calls = [c.name for e in events for c in e.get_function_calls()]
    return {"asked": asked, "issues": list(docs_tools.ISSUES), "calls": calls}, model


class TypedTools(unittest.TestCase):
    def test_the_model_gets_json_schema_with_the_constraints(self):
        _, model = replay("approved")
        sent = {d.name: d.model_dump(mode="json", exclude_none=True)
                for t in model.requests[0].config.tools for d in t.function_declarations}
        self.assertEqual(sent, RECORD["declarations"])
        self.assertEqual(sent["search_docs"]["parameters_json_schema"]["properties"]["limit"]["maximum"], 5)

    def test_every_model_request_keeps_the_output_limit(self):
        _, model = replay("approved")
        self.assertGreater(len(model.requests), 1)
        for request in model.requests:
            config = request.config.model_dump(mode="json", by_alias=True, exclude_none=True)
            self.assertEqual(config["maxOutputTokens"], 1024)

    def test_an_approved_write_files_one_issue(self):
        result, _ = replay("approved")
        self.assertEqual(result["asked"], RUNS["approved"]["approvals"])
        self.assertEqual(result["issues"], RUNS["approved"]["issues"])

    def test_a_declined_write_files_nothing(self):
        result, _ = replay("declined")
        self.assertEqual(len(result["asked"]), 1)
        self.assertEqual(result["issues"], [])

    def test_each_retry_of_a_rejected_call_asks_again(self):
        # Controlled retry: the fresh provider run stopped after one rejection.
        # Duplicate its write proposal only inside this test to exercise a second
        # approval boundary, independently of stochastic model behavior.
        retry = copy.deepcopy(RUNS["declined-retry"])
        proposal = next(turn for turn in retry["model_turns"]
                        if any(part.get("function_call", {}).get("name") == "file_docs_issue"
                               for part in turn["parts"]))
        repeated = copy.deepcopy(proposal)
        repeated["parts"][0]["function_call"]["id"] = "controlled-second-proposal"
        retry["model_turns"].insert(-1, repeated)
        with patch.dict(RUNS, {"controlled-retry": retry}):
            result, _ = replay("controlled-retry", instruction=agent.INSTRUCTION.rsplit("\n", 1)[0])
        self.assertEqual(len(result["asked"]), 2)
        self.assertEqual(result["issues"], [])

    def test_a_field_constraint_is_refused_before_approval_is_asked(self):
        result, _ = replay("short-summary")
        self.assertEqual([a["args"]["summary"] for a in result["asked"]], ["Token expiry details are unclear."])
        self.assertEqual(result["issues"], RUNS["short-summary"]["issues"])

    def test_adk_alone_does_not_enforce_field_constraints(self):
        result, _ = replay("short-summary", before_tool_callback=None)
        self.assertEqual(result["asked"][0]["args"]["summary"], "expiry?")  # a person is asked to approve it

    def test_an_unknown_or_missing_argument_is_refused(self):
        tool = FunctionTool(docs_tools.file_docs_issue)
        error = agent.check_arguments(tool, {"page": "rollback", "summary": "The 1.x command is gone.", "owner": "dana"}, None)
        self.assertIn("kind: Field required", error["error"])
        self.assertIn("owner: Extra inputs are not permitted", error["error"])
        self.assertIsNone(agent.check_arguments(tool, {"page": "rollback", "kind": "outdated", "summary": "The 1.x command is gone."}, None))


if __name__ == "__main__":
    unittest.main()
