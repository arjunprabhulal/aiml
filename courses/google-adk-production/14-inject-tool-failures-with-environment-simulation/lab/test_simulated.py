"""Replay the recorded Gemini turns against the same injected faults, offline.

Run: python -m unittest -v test_simulated.py
The model is replaced by its recorded turns; the environment simulation plugin, the retry
plugin and the tools are real.
"""
import asyncio
import json
import logging
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.apps import App  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.tools import FunctionTool  # noqa: E402
from google.adk.tools.environment_simulation.environment_simulation_config import (  # noqa: E402
    EnvironmentSimulationConfig, ToolSimulationConfig)
from google.adk.tools.environment_simulation.environment_simulation_engine import EnvironmentSimulationEngine  # noqa: E402
from google.genai import types  # noqa: E402

import record  # noqa: E402
import simulated  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
READ_PAGE = FunctionTool(simulated.read_page)


class ReplayLlm(BaseLlm):
    turns: list

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def replay(run: str):
    """Run the recorded model turns of one run through the same app; return its trail and error."""
    options = dict(record.RUNS[run])
    app = simulated.build_app(**options)
    model = ReplayLlm(model="replay", turns=list(RECORD["runs"][run]["model_turns"]))
    app = App(name=app.name, root_agent=app.root_agent.clone(update={"model": model}), plugins=app.plugins)
    events, error = [], None
    try:
        asyncio.run(simulated.ask(app, RECORD["question"], events))
    except RuntimeError as exc:
        error = exc
    return simulated.show(events), error


def engine(*injections) -> EnvironmentSimulationEngine:
    return EnvironmentSimulationEngine(EnvironmentSimulationConfig(tool_simulation_configs=[
        ToolSimulationConfig(tool_name="read_page", injection_configs=list(injections))]))


def simulate(sim, path):
    return asyncio.run(sim.simulate(READ_PAGE, {"path": path}, None))


def setUpModule():
    warnings.simplefilter("ignore")  # unittest resets the filter; ADK warns about experimental features


class Faults(unittest.TestCase):
    def test_the_outage_replays_the_recorded_tool_results(self):
        trail, _ = replay("outage")
        self.assertEqual(trail, RECORD["runs"]["outage"]["trail"])
        self.assertEqual(sum("error_code" in line for line in trail), RECORD["runs"]["outage"]["read_page_failures"])

    def test_without_an_error_rule_the_agent_sometimes_cites_a_page_it_never_read(self):
        runs = [RECORD["runs"]["outage"], *RECORD["outage_repeats"]]
        self.assertTrue(any(r["cites_a_page"] for r in runs))
        self.assertGreater(min(r["read_page_failures"] for r in runs), 1)

    def test_the_error_rule_stops_after_one_failure_and_cites_nothing(self):
        run = RECORD["runs"]["outage-with-error-rule"]
        self.assertEqual((run["read_page_failures"], run["cites_a_page"]), (1, False))
        trail, _ = replay("outage-with-error-rule")
        self.assertEqual(trail, run["trail"])

    def test_the_retry_plugin_raises_once_retries_are_used_up(self):
        trail, error = replay("outage-with-retry-plugin")
        self.assertIn("reflect_retry_tool_plugin", str(error))
        self.assertEqual(sum("ERROR_HANDLED_BY_REFLECT_AND_RETRY_PLUGIN" in line for line in trail), 2)

    def test_the_retry_plugin_sees_results_that_the_simulator_injected(self):
        trail, error = replay("outage-with-retry-limit-answer")
        self.assertIsNone(error)
        self.assertTrue(any("ERROR_HANDLED_BY_REFLECT_AND_RETRY_PLUGIN" in line for line in trail))

    def test_non_throwing_exhaustion_returns_guidance_without_blocking_more_calls(self):
        plugin = simulated.RetryOnErrorCode(max_retries=2, throw_exception_if_retry_exceeded=False)
        async def failures():
            return [await plugin.after_tool_callback(
                tool=READ_PAGE, tool_args={"path": "install.md"},
                tool_context=SimpleNamespace(invocation_id="retry-demo"),
                result={"error_code": 503, "error_message": "Unavailable"}) for _ in range(4)]
        results = asyncio.run(failures())
        self.assertEqual(len(results), 4)
        self.assertEqual(results[2], results[3])
        self.assertIn("exceeded", str(results[3]).lower())

    def test_match_args_fails_only_the_matching_page(self):
        sim = engine(*simulated.FAULTS["missing-page"])
        self.assertEqual(simulate(sim, "install.md"), {"error_code": 404, "error_message": "Page not found."})
        self.assertIsNone(simulate(sim, "cli.md"))  # None: the real tool runs

    def test_a_random_seed_is_reapplied_on_every_call(self):
        always = engine(*simulated.FAULTS["flaky"])  # probability 0.5, random_seed=1
        self.assertEqual(sum(simulate(always, "cli.md") is not None for _ in range(20)), 20)
        never = engine(simulated.fail(503, "Docs service unavailable.", injection_probability=0.5, random_seed=2))
        self.assertEqual(sum(simulate(never, "cli.md") is not None for _ in range(20)), 0)


class SelectedScenario(unittest.TestCase):
    def test_launcher_attaches_error_rule_and_selected_plugins(self):
        from unittest.mock import AsyncMock, patch
        import run
        marker = object()
        args = SimpleNamespace(question="chosen", fault="missing-page", retry="answer")
        with patch.object(simulated, "build_app", return_value=marker) as build, patch.object(simulated, "ask", new_callable=AsyncMock) as ask:
            asyncio.run(run.main(args))
        build.assert_called_once_with(fault="missing-page", instruction=simulated.INSTRUCTION + simulated.ON_ERROR, retry="answer")
        self.assertIs(ask.await_args.args[0], marker)
        self.assertEqual(ask.await_args.args[1], "chosen")


if __name__ == "__main__":
    unittest.main()
