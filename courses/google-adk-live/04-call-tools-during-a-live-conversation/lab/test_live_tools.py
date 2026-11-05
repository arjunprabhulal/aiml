"""Replay the recorded tool calls through ADK's run_live loop; ADK runs the real tools. No network."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

import live_harness
import live_tools
from live_harness import ReplayLive, read_pcm, say_audio, say_text, talk, wait_for_turn
from live_tools import build_agent, search_docs
from record import RUN_CONFIG, LOOKUP_CONFIG, page_reader, push_to_talk

HERE = Path(__file__).parent
RECORD = json.loads((HERE / "tools-run-historical.json").read_text())
RUNS = {run["name"]: run for run in RECORD["runs"]}
CURRENT = json.loads((HERE / "tools-run.json").read_text())
CURRENT_RUNS = {run["name"]: run for run in CURRENT["runs"]}
BEFORE_ACTIVITY = json.loads((HERE / "tools-run-before-activity-signals.json").read_text())
live_harness.PACE = 0
live_tools.SLOW_S = 0.05
logging.disable(logging.CRITICAL)


def converse(name, turns, agent_factory=build_agent, timeout=10, runs=RUNS, run_config=RUN_CONFIG):
    model = ReplayLive(model=runs[name]["connections"][0]["model"],
                       connections=copy.deepcopy(runs[name]["connections"]), opened=[])

    async def run():
        runner = Runner(app_name="voice_docs", agent=agent_factory(model), session_service=InMemorySessionService())
        session = await runner.session_service.create_session(app_name="voice_docs", user_id="dev")
        return await talk(runner, session.id, run_config, turns, timeout=timeout)
    return asyncio.run(run()), model


def tool_results(model, name):
    return [part.function_response.response for _, connection in model.opened for kind, item in connection.received
            if kind == "content" for part in item.parts or [] if part.function_response and part.function_response.name == name]


def finished_lines(run):
    return [r["output_transcription"]["text"] for r in run["events"]
            if "output_transcription" in r and not r.get("partial")]


def calls(run):
    return [call["name"] for row in run["events"] for call in row.get("calls", [])]


class LiveTools(unittest.TestCase):
    def test_push_to_talk_marks_both_activity_boundaries(self):
        async def check():
            queue = LiveRequestQueue()
            await push_to_talk(bytes(320))(queue)
            requests = [await asyncio.wait_for(queue.get(), 0.1) for _ in range(3)]
            self.assertIsNotNone(requests[0].activity_start)
            self.assertEqual(requests[1].blob.mime_type, "audio/pcm;rate=16000")
            self.assertIsNotNone(requests[2].activity_end)
        asyncio.run(check())

    def test_activity_signals_complete_the_recorded_lookup(self):
        failed = BEFORE_ACTIVITY["runs"][0]
        self.assertEqual(BEFORE_ACTIVITY["environment"]["model"], "gemini-3.8-live")
        self.assertIn("TimeoutError", failed["error"])
        self.assertFalse(calls(failed))
        current = CURRENT_RUNS["blocking lookup"]
        self.assertEqual(CURRENT["environment"]["tools_model"], "gemini-3.8-live")
        self.assertNotIn("error", current)
        [connection] = current["connections"]
        controls = [e.get("mime_type") for e in connection["traffic"] if e.get("sent") == "realtime"]
        self.assertIn("ActivityStart", controls)
        self.assertIn("ActivityEnd", controls)
        self.assertTrue(connection["config"]["realtime_input_config"]["automatic_activity_detection"]["disabled"])
        behaviors = {tool["name"]: tool["behavior"] for tool in connection["tools"]}
        self.assertEqual(behaviors["search_docs"], "BLOCKING")
        _, model = converse("blocking lookup", [push_to_talk(read_pcm(HERE / "lookup.wav"))], runs=CURRENT_RUNS, run_config=LOOKUP_CONFIG)
        results = tool_results(model, "search_docs")
        self.assertTrue(any("10 minutes" in hit["line"] for result in results for hit in result["hits"]))

    def test_lookup_explicitly_declares_blocking_for_current_live_model(self):
        lookup = build_agent().tools[0]
        self.assertIsInstance(lookup, FunctionTool)
        self.assertEqual(lookup.name, "search_docs")
        self.assertEqual(lookup.behavior, types.Behavior.BLOCKING)

    def test_adk_runs_the_lookup_and_sends_the_result_back(self):
        _, model = converse("blocking lookup", [say_audio(read_pcm(HERE / "lookup.wav"))])
        [result] = tool_results(model, "search_docs")
        self.assertTrue(any("10 minutes" in hit["line"] for hit in result["hits"]))

    def test_search_reports_a_miss_instead_of_inventing_a_hit(self):
        self.assertEqual(search_docs("kubernetes helm chart")["hits"], [])

    def test_async_tools_are_declared_non_blocking(self):
        behaviors = {t["name"]: t["behavior"] for t in RUNS["blocking lookup"]["connections"][0]["tools"]}
        self.assertEqual(behaviors, {"search_docs": None, "export_page_index": "NON_BLOCKING",
                                     "check_links": "NON_BLOCKING", "stop_streaming": None})

    def test_each_streamed_update_goes_back_to_the_model(self):
        turns = [say_text("Check the links in the docs pages."), wait_for_turn(), say_text("Never mind, stop the link check.")]
        _, model = converse("streaming link check, then stop", turns)
        updates = [r["result"] for r in tool_results(model, "check_links") if "result" in r]
        self.assertTrue(updates[0].startswith("Checked "), updates)
        self.assertEqual(updates[-1], "Done: 3 pages checked.")

    def test_the_pending_status_is_spoken_as_its_own_turn(self):
        lines = finished_lines(RUNS["streaming link check, then stop"])
        self.assertEqual(lines[0].lower(), "async return")

    def test_streamed_updates_reach_the_model_but_are_not_narrated(self):
        run = RUNS["streaming link check, then stop"]
        sent = [e for e in run["connections"][0]["traffic"] if e.get("function_responses") == ["check_links"]]
        self.assertGreaterEqual(len(sent), 4)  # the pending status, then each yield
        before_stop = finished_lines(run)[:2]
        self.assertFalse(any("of 3" in line or "Checked" in line for line in before_stop), before_stop)

    def test_a_stop_after_the_stream_finished_finds_nothing(self):
        run = RUNS["streaming link check, then stop"]
        [stop] = [r["response"] for row in run["events"] for r in row.get("responses", []) if r["name"] == "stop_streaming"]
        self.assertIn("No active streaming function", stop["status"])

    def test_a_raising_tool_ends_the_whole_live_session(self):
        with self.assertRaises(FileNotFoundError):
            converse("tool raises an exception", [say_text("Read the page deploy.md.")], agent_factory=page_reader)
        self.assertTrue(RUNS["tool raises an exception"]["error"].startswith("FileNotFoundError"))

    def test_scheduled_result_on_gemini_3_1_is_never_announced(self):
        run = RUNS["scheduled export on Gemini 3.1 Flash Live"]
        self.assertIn("export_page_index", [r["name"] for row in run["events"] for r in row.get("responses", [])])
        self.assertIn("TimeoutError", run["error"])

    def test_gemini_2_5_tool_calls_never_reach_adk(self):
        self.assertEqual(calls(RUNS["tools on Gemini 2.5 Flash Live"]), [])
        raw = {r["model"]: r["messages"] for r in RECORD["raw_tool_call"]}
        self.assertEqual(raw[RECORD["environment"]["model"]][0], "tool_call")
        self.assertNotIn("turn_complete", raw[RECORD["environment"]["model"]])


if __name__ == "__main__":
    unittest.main()
