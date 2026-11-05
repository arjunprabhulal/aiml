"""Replay the recorded Gemini turns against a real PostgreSQL 17 cluster behind a real MCP Toolbox server.

Run: PG_BIN=/path/to/postgresql@17/bin python -m unittest -v test_agent.py   (needs `toolbox` 0.21.0 on PATH)
The model is replaced by its recorded turns; Toolbox, the database, ToolboxToolset and the agent loop are real.
"""
import asyncio
import json
import logging
import re
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

import agent  # noqa: E402
from lab import HERE, Lab, config_error, free_port  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
LAB = None


def setUpModule():
    global LAB
    warnings.simplefilter("ignore")  # unittest resets warning filters before the tests run
    LAB = Lab().create()


def tearDownModule():
    LAB.destroy()


class ReplayLlm(BaseLlm):
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def replay(turns: list, toolset) -> tuple[str, ReplayLlm]:
    model = ReplayLlm(model="replay", turns=list(turns), requests=[])
    return agent.show(asyncio.run(agent.ask("replayed question", agent.build_agent(model, toolset)))), model


def offered(model: ReplayLlm) -> dict:
    return {d.name: d for t in model.requests[0].config.tools or [] for d in t.function_declarations}


def feedback_rows() -> int:
    with LAB.admin() as conn:
        return conn.execute("SELECT count(*) FROM feedback").fetchone()[0]


class ToolboxToolsetTests(unittest.TestCase):
    def test_the_reader_toolset_lists_only_read_tools(self):
        self.assertEqual(asyncio.run(agent.list_tools(LAB.url)), RECORD["discovery"])

    def test_the_feedback_question_replays_against_the_database(self):
        run = RECORD["runs"]["feedback"]
        transcript, _ = replay(run["model_turns"], agent.docs_db(LAB.url))
        self.assertEqual(transcript, run["transcript"])

    def test_team_is_bound_and_never_offered_to_the_model(self):
        _, model = replay(RECORD["runs"]["delete"]["model_turns"], agent.docs_db(LAB.url))
        tools = offered(model)
        self.assertEqual(sorted(tools), ["find-pages", "page-feedback"])
        self.assertTrue(all("team" not in d.parameters.properties for d in tools.values()))
        self.assertTrue(all("team" not in d["parameters"]["properties"] for d in RECORD["runs"]["feedback"]["declarations"].values()))

    def test_the_read_only_role_refuses_a_write(self):
        run = RECORD["failures"]["read_only_role"]
        transcript, _ = replay(run["model_turns"], agent.docs_db(LAB.url, "docs-admin", bind_team=False))
        self.assertEqual(transcript, run["transcript"])
        self.assertIn("permission denied for table feedback (SQLSTATE 42501)", transcript)
        self.assertEqual(feedback_rows(), RECORD["feedback_rows_after"])

    def test_a_bound_parameter_no_tool_uses_fails_the_whole_toolset(self):
        with self.assertRaises(ValueError) as caught:
            asyncio.run(agent.list_tools(LAB.url, "docs-admin"))
        self.assertIn("unused bound parameters could not be applied to any tool: team", str(caught.exception))
        run = RECORD["failures"]["unused_bound_param"]
        _, model = replay(run["model_turns"], agent.docs_db(LAB.url, "docs-admin"))
        self.assertEqual(offered(model), {})
        self.assertIn("will run without the tools from toolset ToolboxToolset", run["errors"][0])

    def test_a_toolbox_server_that_is_down_leaves_the_agent_without_tools(self):
        down = f"http://127.0.0.1:{free_port()}"
        _, model = replay([{"role": "model", "parts": [{"text": ""}]}], agent.docs_db(down))
        self.assertEqual(offered(model), {})
        with self.assertRaises(Exception) as caught:
            asyncio.run(agent.list_tools(down))
        self.assertIn("Cannot connect to host", str(caught.exception))
        recorded = RECORD["failures"]["server_down"]
        self.assertEqual(re.sub(r"\d{4,5}", "PORT", recorded["errors"][0]).split(" which failed to load: ")[1].split(" ssl")[0],
                         "Cannot connect to host 127.0.0.1:PORT")
        self.assertEqual(recorded["transcript"], "answer ")

    def test_sql_in_an_argument_stays_a_value(self):
        from toolbox_core import ToolboxClient

        async def search():
            async with ToolboxClient(LAB.url) as toolbox:
                tools = await toolbox.load_toolset("docs-reader", bound_params={"team": agent.TEAM})
                find = next(t for t in tools if t._name == "find-pages")
                return await find(title_contains="x'; DROP TABLE pages; --")
        self.assertEqual(asyncio.run(search()), "null")
        with LAB.admin() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM pages").fetchone()[0], 4)

    def test_the_per_object_config_format_is_refused_by_toolbox_0_21(self):
        error = config_error(HERE / "tools-v2-format.yaml")
        prefix = 'unable to parse tool file at \\"tools-v2-format.yaml\\": ['
        self.assertTrue(error.startswith('"' + prefix), error)
        self.assertIn("unknown field", error)
        self.assertTrue(RECORD["config_error"].startswith('"' + prefix))


if __name__ == "__main__":
    unittest.main()
