"""Replay the recorded Gemini turns through the guarded app, offline.

Run: python -m unittest -v test_guarded.py
The model is replaced by its recorded turns; the App, plugin, callbacks, tool and session store are real.
"""
import asyncio
import json
import logging
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.plugins import BasePlugin  # noqa: E402
from google.adk.tools import FunctionTool  # noqa: E402
from google.genai import types  # noqa: E402

import guarded  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))


class ReplayLlm(BaseLlm):
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(json.dumps([c.model_dump(mode="json", exclude_none=True) for c in llm_request.contents]))
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


def replay(run: str, plugins=None, **update):
    model = ReplayLlm(model="replay", turns=list(RECORD["runs"][run]["model_turns"]), requests=[])
    agent = guarded.root_agent.clone(update={"model": model, **update})
    events, stored = asyncio.run(guarded.ask(guarded.build_app(agent, plugins), RECORD["runs"][run]["question"]))
    stored_json = json.dumps([e.content.model_dump(mode="json", exclude_none=True) for e in stored if e.content])
    return guarded.show(events), model, stored_json


class RedactOnlyModelRequests(BasePlugin):
    """The tempting version: redact in before_model_callback only."""

    def __init__(self):
        super().__init__(name="redact_model_requests")

    async def before_model_callback(self, *, callback_context, llm_request):
        for content in llm_request.contents:
            for part in content.parts or []:
                if part.text:
                    part.text = guarded.redact(part.text)[0]
        return None


class BlockAllTools(BasePlugin):
    def __init__(self):
        super().__init__(name="block_all_tools")

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        return {"error": "Tools are disabled."}


from output_cap_check import assert_capped_wire

class Guards(unittest.TestCase):

    def test_every_full_app_turn_keeps_the_serialized_response_cap(self):
        class ConfigReplay(ReplayLlm):
            configs: list = []
            wire_requests: list = []

            async def generate_content_async(self, llm_request, stream=False):
                self.wire_requests.append(llm_request)
                self.configs.append(llm_request.config.model_dump(
                    mode="json", by_alias=True, exclude_none=True))
                async for response in super().generate_content_async(llm_request, stream):
                    yield response
        model = ConfigReplay(model=guarded.MODEL, turns=list(RECORD["runs"]["read"]["model_turns"]),
                             requests=[], configs=[], wire_requests=[])
        root = guarded.root_agent.clone(update={"model": model})
        asyncio.run(guarded.ask(guarded.build_app(root), RECORD["runs"]["read"]["question"]))
        self.assertGreater(len(model.configs), 1)
        assert_capped_wire(self, model.wire_requests)
        for sent in model.configs:
            self.assertEqual(sent["maxOutputTokens"], 1024)


    def test_a_pasted_key_reaches_neither_the_model_nor_the_session(self):
        transcript, model, stored = replay("pasted")
        self.assertEqual(transcript, RECORD["runs"]["pasted"]["transcript"])
        self.assertFalse(any("AKIA" in r for r in model.requests))
        self.assertNotIn("AKIA", stored)
        self.assertIn(guarded.REDACTED, stored)

    def test_without_the_plugin_the_key_is_sent_and_stored(self):
        _, model, stored = replay("pasted-no-plugin", plugins=[])
        self.assertTrue(any("AKIA" in r for r in model.requests))
        self.assertIn("AKIA", stored)

    def test_redacting_only_model_requests_still_stores_the_key(self):
        _, model, stored = replay("pasted", plugins=[RedactOnlyModelRequests()])
        self.assertFalse(any("AKIA" in r for r in model.requests))
        self.assertIn("AKIA", stored)  # the user message was saved before the model call

    def test_a_key_in_a_tool_result_is_redacted(self):
        transcript, model, stored = replay("read")
        self.assertEqual(transcript, RECORD["runs"]["read"]["transcript"])
        self.assertFalse(any("AKIA" in r for r in model.requests))
        self.assertNotIn("AKIA", stored)

    def test_a_path_outside_the_workspace_is_refused_before_the_tool_runs(self):
        transcript, _, _ = replay("outside")
        self.assertIn("result read_file Refused: ../workspace-old/docuctl.toml is outside the workspace.", transcript)
        resolved = (guarded.WORKSPACE / "../workspace-old/docuctl.toml").resolve()
        self.assertTrue(str(resolved).startswith(str(guarded.WORKSPACE)))  # why a prefix check is not enough
        refused = guarded.stay_in_workspace(FunctionTool(guarded.read_file), {"path": "../workspace-old/docuctl.toml"}, None)
        self.assertIn("outside the workspace", refused["error"])
        self.assertIsNone(guarded.stay_in_workspace(FunctionTool(guarded.read_file), {"path": "docs/config.md"}, None))

    def test_a_plugin_answer_skips_the_agent_callback(self):
        calls = []

        def agent_callback(tool, args, tool_context):
            calls.append(tool.name)
            return None

        transcript, _, _ = replay("read", plugins=[BlockAllTools()], before_tool_callback=agent_callback)
        self.assertEqual(calls, [])
        self.assertIn("result read_file Tools are disabled.", transcript)


if __name__ == "__main__":
    unittest.main()
