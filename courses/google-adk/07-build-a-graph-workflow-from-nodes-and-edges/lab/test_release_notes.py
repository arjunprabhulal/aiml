"""Replay the recorded Gemini reply through the real workflow; no API key needed."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk import Event, Workflow
from google.adk.workflow._errors import WorkflowDataError

from harness import ReplayLlm, run
from release_notes import ReleaseGroups, build_workflow, parse_log, render_notes

HERE = Path(__file__).parent
# ADK logs each failed node with its traceback; the tests assert on the exception instead.
logging.getLogger("google_adk").setLevel(logging.CRITICAL)
RECORD = json.loads((HERE / "workflow-run.json").read_text())


def replay(calls=None):
    return ReplayLlm(model=RECORD["environment"]["model"],
                     calls=copy.deepcopy(calls or RECORD["model_calls"]))


def run_workflow(workflow, text):
    return asyncio.run(run(workflow, text))[0]


from output_cap_check import assert_capped_wire

class ReleaseNotesWorkflow(unittest.TestCase):

    def test_default_and_low_thinking_nodes_serialize_the_response_cap(self):
        class ConfigReplay(ReplayLlm):
            configs: list = []
            wire_requests: list = []

            async def generate_content_async(self, llm_request, stream=False):
                self.wire_requests.append(llm_request)
                self.configs.append(llm_request.config.model_dump(
                    mode="json", by_alias=True, exclude_none=True, exclude={"response_schema"}))
                async for response in super().generate_content_async(llm_request, stream):
                    yield response
        for level in (None, "low"):
            with self.subTest(thinking_level=level):
                calls = RECORD["low_thinking"]["model_calls"] if level else RECORD["model_calls"]
                model = ConfigReplay(model=RECORD["environment"]["model"],
                                     calls=copy.deepcopy(calls), configs=[], wire_requests=[])
                run_workflow(build_workflow(model, thinking_level=level), RECORD["input"])
                assert_capped_wire(self, model.wire_requests)
                self.assertEqual(len(model.configs), 1)
                self.assertEqual(model.configs[0]["maxOutputTokens"], 1024)
                if level:
                    self.assertEqual(model.configs[0]["thinkingConfig"]["thinkingLevel"], "LOW")


    def test_replay_matches_the_recorded_events(self):
        events = run_workflow(build_workflow(replay()), RECORD["input"])
        self.assertEqual(events, RECORD["events"])

    def test_low_thinking_replays_to_the_same_notes(self):
        low = RECORD["low_thinking"]
        events = run_workflow(build_workflow(replay(low["model_calls"]), thinking_level="low"),
                              RECORD["input"])
        self.assertEqual(events, low["events"])
        self.assertEqual(events[-1]["message"], RECORD["events"][-1]["message"])

    def test_each_node_emits_one_event_under_its_path(self):
        paths = [event["node_info"]["path"] for event in RECORD["events"]]
        self.assertEqual(paths, ["release_notes@1/parse_log@1",
                                 "release_notes@1/group_changes@1",
                                 "release_notes@1/render_notes@1"])

    def test_every_commit_is_listed_once(self):
        notes = RECORD["events"][-1]["message"]
        for subject in RECORD["events"][0]["output"]["subjects"]:
            self.assertEqual(notes.count(subject), 1, subject)

    def test_a_line_that_is_not_git_log_stops_the_run(self):
        with self.assertRaisesRegex(ValueError, "not a git log --oneline line"):
            run_workflow(build_workflow(replay()), "Bump version to 2.1\n")

    def test_a_dropped_commit_is_refused(self):
        calls = copy.deepcopy(RECORD["model_calls"])
        groups = json.loads(calls[0]["reply"]["content"]["parts"][0]["text"])
        groups["docs"].pop()
        calls[0]["reply"]["content"]["parts"][0]["text"] = json.dumps(groups)
        with self.assertRaisesRegex(ValueError, "groups do not match the log: missing="):
            run_workflow(build_workflow(replay(calls)), RECORD["input"])

    def test_a_state_parameter_with_no_writer_fails(self):
        def groups(node_input: str):
            return Event(output=ReleaseGroups(features=["a"], fixes=[], docs=[]))
        workflow = Workflow(name="no_parse", edges=[("START", groups, render_notes)])
        with self.assertRaisesRegex(WorkflowDataError, 'parameter "subjects"'):
            run_workflow(workflow, "x")

    def test_a_node_can_emit_only_one_output(self):
        def twice(node_input: str):
            yield Event(output=1)
            yield Event(output=2)
        with self.assertRaisesRegex(ValueError, "at most one output"):
            run_workflow(Workflow(name="twice", edges=[("START", twice)]), "x")


if __name__ == "__main__":
    unittest.main()
