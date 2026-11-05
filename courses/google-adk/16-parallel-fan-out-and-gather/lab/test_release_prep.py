"""Replay the recorded fan-out runs, and drive branch failures and concurrency with a stub model."""
import asyncio
import copy
import json
import logging
import unittest
from importlib import import_module
HISTORICAL = import_module("release_prep")
from pathlib import Path

from google.adk.models import BaseLlm, LlmResponse
from google.genai import types

from harness import ReplayLlm, run
from release_prep import build_graph, build_partial

HERE = Path(__file__).parent
logging.getLogger("google_adk").setLevel(logging.CRITICAL)
RECORD = json.loads((HERE / "prep-run.json").read_text())
RUNS = {(r["workflow"], r["release"]): r for r in RECORD["runs"]}
REPLY = {"write_highlights": {"bullets": ["stub"]}, "write_upgrade_steps": {"steps": []}}


class StubLlm(BaseLlm):
    """Waits `delay` seconds per call, or raises; counts started, finished and peak in-flight calls."""
    delay: float = 0.0
    fail: bool = False
    started: int = 0
    finished: int = 0
    in_flight: int = 0
    peak: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        self.started += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            if self.fail:
                raise ConnectionError("503 UNAVAILABLE")
        finally:
            self.in_flight -= 1
        self.finished += 1
        name = "write_highlights" if "bullet" in str(llm_request.config.system_instruction) \
            else "write_upgrade_steps"
        yield LlmResponse(content=types.Content(
            role="model", parts=[types.Part(text=json.dumps(REPLY[name]))]))


def prepare(workflow, release):
    return asyncio.run(run(workflow, (HERE / release).read_text()))[0]


def by_path(events):
    return sorted(events, key=lambda e: (e["node_info"]["path"], json.dumps(e)))


class FanOutAndGather(unittest.TestCase):
    def test_replay_matches_the_recorded_runs(self):
        for key, build in [(("graph", "release-3.5.0.md"), HISTORICAL.build_graph),
                           (("partial", "release-3.6.0.md"), HISTORICAL.build_partial)]:
            recorded = RUNS[key]
            model = ReplayLlm(model=RECORD["environment"]["model"],
                              calls=copy.deepcopy(recorded["model_calls"]))
            with self.subTest(key):
                events = asyncio.run(run(build(model), (HERE / key[1]).read_text()))[0]
                self.assertEqual(by_path(events), by_path(recorded["events"]))

    def test_the_two_model_branches_overlapped(self):
        recorded = RUNS[("graph", "release-3.5.0.md")]
        latencies = [call["latency_s"] for call in recorded["model_calls"]]
        self.assertEqual(len(latencies), 2)
        self.assertLess(recorded["run_seconds"], sum(latencies))

    def test_the_join_keys_outputs_by_branch_name(self):
        gather = next(e for e in RUNS[("graph", "release-3.5.0.md")]["events"]
                      if e["node_info"]["path"].endswith("/gather@1"))
        self.assertEqual(set(gather["output"]),
                         {"write_highlights", "write_upgrade_steps", "check_links"})

    def test_one_failed_branch_fails_the_whole_graph(self):
        model = StubLlm(model="stub", delay=0.5)
        with self.assertRaisesRegex(FileNotFoundError, "build the site first"):
            prepare(build_graph(model), "release-3.6.0.md")
        self.assertEqual((model.started, model.finished), (2, 0))  # in-flight calls cancelled
        self.assertEqual(RUNS[("graph", "release-3.6.0.md")]["model_calls"], [])

    def test_the_dynamic_parent_keeps_partial_results(self):
        events = prepare(build_partial(StubLlm(model="stub")), "release-3.6.0.md")
        self.assertIn("check_links@1 failed: FileNotFoundError", events[-3]["message"])
        self.assertIn("Link check: not run", events[-1]["message"])

    def test_a_required_branch_still_fails_the_run_after_its_retries(self):
        model = StubLlm(model="stub", fail=True)
        with self.assertRaisesRegex(ConnectionError, "503 UNAVAILABLE"):
            prepare(build_partial(model), "release-3.5.0.md")
        self.assertEqual(model.started, 2 * 3)  # two model branches, three attempts each

    def test_max_concurrency_limits_branches_in_flight(self):
        for limit, peak in [(None, 2), (1, 1)]:
            model = StubLlm(model="stub", delay=0.05)
            prepare(build_graph(model, max_concurrency=limit), "release-3.5.0.md")
            self.assertEqual(model.peak, peak, limit)


if __name__ == "__main__":
    unittest.main()
