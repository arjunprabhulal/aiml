"""Replay the recorded Gemini reply through the real router; no API key needed."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk import Event, Workflow
from pydantic import ValidationError

from build_router import (PAGES, build_workflow, check_fixes, classify_build,
                          report_clean)
from harness import ReplayLlm, run

logging.getLogger("google_adk").setLevel(logging.CRITICAL)
HERE = Path(__file__).parent
RECORD = json.loads((HERE / "routes-run.json").read_text())
RUNS = {r["log"]: r for r in RECORD["runs"]}


class SeeingReplay(ReplayLlm):
    """A replay model that also keeps the system instruction it was sent."""
    seen: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.seen.append(llm_request.config.system_instruction)
        async for response in super().generate_content_async(llm_request, stream):
            yield response


def replay(calls, cls=ReplayLlm):
    return cls(model=RECORD["environment"]["model"], calls=copy.deepcopy(calls))


def run_log(workflow, name):
    return asyncio.run(run(workflow, (HERE / name).read_text()))[0]


from output_cap_check import assert_capped_wire

class BuildRouter(unittest.TestCase):

    def test_only_the_model_branch_serializes_one_capped_request(self):
        class ConfigReplay(ReplayLlm):
            configs: list = []
            wire_requests: list = []

            async def generate_content_async(self, llm_request, stream=False):
                self.wire_requests.append(llm_request)
                self.configs.append(llm_request.config.model_dump(
                    mode="json", by_alias=True, exclude_none=True, exclude={"response_schema"}))
                async for response in super().generate_content_async(llm_request, stream):
                    yield response
        for name, recorded in RUNS.items():
            with self.subTest(log=name):
                model = ConfigReplay(model=RECORD["environment"]["model"],
                                     calls=copy.deepcopy(recorded["model_calls"]), configs=[], wire_requests=[])
                run_log(build_workflow(model), name)
                assert_capped_wire(self, model.wire_requests)
                self.assertEqual(len(model.configs), 1 if name == "build-broken.log" else 0)
                for sent in model.configs:
                    self.assertEqual(sent["maxOutputTokens"], 1024)


    def test_each_log_replays_to_the_recorded_events(self):
        for name, recorded in RUNS.items():
            with self.subTest(name):
                self.assertEqual(run_log(build_workflow(replay(recorded["model_calls"])), name),
                                 recorded["events"])

    def test_only_the_broken_links_route_calls_the_model(self):
        self.assertEqual({n: len(r["model_calls"]) for n, r in RUNS.items()},
                         {"build-broken.log": 1, "build-clean.log": 0,
                          "build-incomplete.log": 0})

    def test_triage_instruction_gets_the_page_list_from_state(self):
        model = replay(RUNS["build-broken.log"]["model_calls"], SeeingReplay)
        run_log(build_workflow(model), "build-broken.log")
        self.assertIn(str(PAGES), model.seen[0])

    def test_unmatched_route_without_a_default_ends_silently(self):
        workflow = Workflow(name="no_default", edges=[
            ("START", classify_build),
            (classify_build, {"clean": report_clean}),
        ])
        events = run_log(workflow, "build-incomplete.log")
        self.assertEqual([e.get("route") for e in events], ["incomplete"])
        self.assertNotIn("message", events[-1])

    def test_a_boolean_route_does_not_match_a_string_key(self):
        def passed(node_input: str):
            return Event(route=True)
        workflow = Workflow(name="typed_routes", edges=[
            ("START", passed), (passed, {"True": report_clean})])
        events = asyncio.run(run(workflow, "x"))[0]
        self.assertEqual(len(events), 1)

    def test_a_list_route_runs_every_matching_target(self):
        def both(node_input: str):
            return Event(route=["clean", "rerun"])
        def clean(node_input=None):
            return Event(message="clean")
        def rerun(node_input=None):
            return Event(message="rerun")
        workflow = Workflow(name="fan_out", edges=[
            ("START", both), (both, {"clean": clean, "rerun": rerun})])
        events = asyncio.run(run(workflow, "x"))[0]
        self.assertEqual(sorted(e["message"] for e in events[1:]), ["clean", "rerun"])

    def test_a_back_edge_is_not_bounded_by_the_workflow(self):
        runs = []
        def again(node_input=None):
            runs.append(1)
            if len(runs) == 20:
                raise RuntimeError("stopped by the node's own counter")
            return Event(route="again")
        workflow = Workflow(name="cycle", edges=[("START", again), (again, {"again": again})])
        with self.assertRaisesRegex(RuntimeError, "own counter"):
            asyncio.run(run(workflow, "x"))
        self.assertEqual(len(runs), 20)

    def test_an_unreachable_node_fails_when_the_workflow_is_built(self):
        with self.assertRaisesRegex(ValidationError, "unreachable from START"):
            Workflow(name="orphan", edges=[("START", classify_build), (report_clean, check_fixes)])

    def test_a_replacement_page_that_does_not_exist_is_flagged(self):
        calls = copy.deepcopy(RUNS["build-broken.log"]["model_calls"])
        part = calls[0]["reply"]["content"]["parts"][0]
        fixes = json.loads(part["text"])
        fixes["fixes"][1]["replacement"] = "reference/sources.md"
        part["text"] = json.dumps(fixes)
        events = run_log(build_workflow(replay(calls)), "build-broken.log")
        self.assertIn("reference/sources.md (needs a person: page does not exist)",
                      events[-1]["message"])


if __name__ == "__main__":
    unittest.main()
