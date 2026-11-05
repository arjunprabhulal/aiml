"""Replay the recorded Gemini fixes, and drive retries and timeouts with a stub model."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk import Event, Workflow
from google.adk.models import BaseLlm, LlmResponse
from google.adk.workflow import NodeTimeoutError, RetryConfig, node
from google.genai import types

from harness import ReplayLlm, last_user_text, run
from lint_changed import DOCS, build_workflow

logging.getLogger("google_adk").setLevel(logging.CRITICAL)
HERE = Path(__file__).parent
RECORD = json.loads((HERE / "lint-run.json").read_text())


class StubLlm(BaseLlm):
    """Fails the first `fails` calls, waits `delay` seconds, then returns the page unchanged."""
    fails: int = 0
    delay: float = 0.0
    attempts: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        self.attempts += 1
        await asyncio.sleep(self.delay)
        if self.attempts <= self.fails:
            raise ConnectionError("503 UNAVAILABLE")
        content = json.loads(last_user_text(llm_request))["content"]
        yield LlmResponse(content=types.Content(
            role="model", parts=[types.Part(text=json.dumps({"content": content}))]))


def lint(model, changed=RECORD["input"], **options):
    return asyncio.run(run(build_workflow(model, retry_delay=0.01, **options), changed))[0]


class DynamicLint(unittest.TestCase):
    def test_replay_produces_the_recorded_events(self):
        model = ReplayLlm(model=RECORD["environment"]["model"],
                          calls=copy.deepcopy(RECORD["model_calls"]))
        by_path = lambda events: sorted(events, key=lambda e: e["node_info"]["path"])
        self.assertEqual(by_path(lint(model)), by_path(RECORD["events"]))

    def test_one_child_per_page_with_a_counter_in_its_path(self):
        reviews = [e["node_info"]["path"] for e in RECORD["events"]
                   if e["node_info"]["path"].endswith(("review_page@1", "review_page@2", "review_page@3"))]
        self.assertEqual(sorted(reviews), [f"docs_lint@1/lint_changed_pages@1/review_page@{n}"
                                           for n in (1, 2, 3)])

    def test_the_two_fixes_ran_concurrently(self):
        latencies = [call["latency_s"] for call in RECORD["model_calls"]]
        self.assertEqual(len(latencies), 2)
        self.assertLess(RECORD["run_seconds"], sum(latencies))

    def test_the_semaphore_bounds_how_many_pages_are_fixed_at_once(self):
        class CountingLlm(StubLlm):
            in_flight: int = 0
            peak: int = 0

            async def generate_content_async(self, llm_request, stream=False):
                self.in_flight += 1
                self.peak = max(self.peak, self.in_flight)
                try:
                    async for response in super().generate_content_async(llm_request, stream):
                        yield response
                finally:
                    self.in_flight -= 1

        changed = "install.md quickstart.md"  # both pages fail lint and need the fixer
        unbounded = CountingLlm(model="stub", delay=0.05)
        lint(unbounded, changed)
        self.assertEqual(unbounded.peak, 2)  # the default limit (4) lets both run at once
        bounded = CountingLlm(model="stub", delay=0.05)
        events = lint(bounded, changed, max_concurrent=1)
        self.assertEqual(bounded.peak, 1)
        self.assertEqual(bounded.attempts, 4)  # every page still gets its two fix rounds
        self.assertIn("install.md: still failing after 2 rounds", events[-1]["message"])

    def test_the_fix_loop_stops_after_max_rounds(self):
        model = StubLlm(model="stub")
        events = lint(model, "install.md")
        self.assertEqual(model.attempts, 2)
        self.assertIn("install.md: still failing after 2 rounds", events[-1]["message"])
        self.assertEqual((DOCS / "install.md").read_text().count("####"), 1)  # source untouched

    def test_a_transient_model_error_is_retried(self):
        model = StubLlm(model="stub", fails=2)
        events = lint(model, "quickstart.md")
        self.assertEqual(model.attempts, 2 + 2)  # two failed attempts, then two fix rounds
        self.assertIn("still failing after 2 rounds", events[-1]["message"])

    def test_retries_exhausted_raise_the_last_error(self):
        model = StubLlm(model="stub", fails=3)
        with self.assertRaisesRegex(ConnectionError, "503 UNAVAILABLE"):
            lint(model, "quickstart.md")
        self.assertEqual(model.attempts, 3)

    def test_each_attempt_has_its_own_timeout(self):
        model = StubLlm(model="stub", delay=0.5)
        with self.assertRaisesRegex(NodeTimeoutError, "'fix_page' timed out after 0.1 seconds"):
            lint(model, "quickstart.md", timeout=0.1)
        self.assertEqual(model.attempts, 3)

    def test_catching_exception_inside_a_node_disables_its_retries(self):
        attempts = []

        @node(retry_config=RetryConfig(max_attempts=3, initial_delay=0.01))
        def fetch_page(node_input: str):
            attempts.append(node_input)
            try:
                raise ConnectionError("503 UNAVAILABLE")
            except Exception:
                return Event(output="")  # the failure is hidden; nothing is retried

        asyncio.run(run(Workflow(name="swallow", edges=[("START", fetch_page)]), "cli.md"))
        self.assertEqual(attempts, ["cli.md"])


if __name__ == "__main__":
    unittest.main()
