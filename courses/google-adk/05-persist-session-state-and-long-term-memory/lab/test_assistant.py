"""Replay the recorded Gemini turns against a real SQLite session store, offline.

Run: python -m unittest -v test_assistant.py
"""
import asyncio
import json
import logging
import tempfile
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk import Event  # noqa: E402
from google.adk.events import EventActions  # noqa: E402
from google.adk.memory import InMemoryMemoryService  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.sessions import DatabaseSessionService  # noqa: E402
from google.adk.errors import StaleSessionError  # noqa: E402
from google.genai import types  # noqa: E402

import assistant as current_assistant  # noqa: E402
from importlib import import_module
assistant = import_module("assistant")

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))


class ReplayLlm(BaseLlm):
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


from output_cap_check import assert_capped_wire

class SessionsAndMemory(unittest.TestCase):

    def test_every_database_agent_turn_keeps_the_serialized_response_cap(self):
        async def go():
            step = RECORD["steps"][0]
            model = ReplayLlm(model=assistant.MODEL, turns=list(step["model_turns"]), requests=[])
            runner = assistant.make_runner(InMemoryMemoryService(),
                assistant.root_agent.clone(update={"model": model}), self.db_url)
            try:
                session = await runner.session_service.create_session(app_name=assistant.APP,
                    user_id=step["user"])
                await assistant.ask(runner, step["user"], session.id, step["question"])
                return model.requests
            finally:
                await runner.close()
                await runner.session_service.close()
        requests = asyncio.run(go())
        self.assertGreater(len(requests), 1)
        assert_capped_wire(self, requests)
        for request in requests:
            self.assertEqual(request.config.max_output_tokens, 1024)


    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_url = f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'sessions.db'}"

    def tearDown(self):
        self.tmp.cleanup()

    def replay(self, steps: list[int], instruction: str | None = None):
        """Replay recorded steps in order; a new run number means new service objects, as after a restart."""
        async def go():
            results, runner, run = [], None, None
            for i in steps:
                step = RECORD["steps"][i]
                if step["run"] != run:
                    if runner:
                        await runner.close()
                    run, memory = step["run"], InMemoryMemoryService()
                    model = ReplayLlm(model="replay", turns=[], requests=[])
                    update = {"model": model} | ({"instruction": instruction} if instruction else {})
                    runner = assistant.make_runner(memory, assistant.root_agent.clone(update=update), self.db_url)
                model.turns[:] = step["model_turns"]
                start = len(model.requests)
                session = await runner.session_service.create_session(app_name=assistant.APP, user_id=step["user"])
                events = await assistant.ask(runner, step["user"], session.id, step["question"])
                stored = await runner.session_service.get_session(app_name=assistant.APP, user_id=step["user"], session_id=session.id)
                await memory.add_session_to_memory(stored)
                results.append({"transcript": assistant.show(events), "state": dict(stored.state),
                                "instruction": model.requests[start].config.system_instruction})
            await runner.close()
            return results
        return asyncio.run(go())

    def test_user_state_survives_a_restart(self):
        first, after = self.replay([0, 2])
        self.assertEqual(first["state"]["user:docuctl_version"], "1.x")
        self.assertIn("The developer's docuctl version: 1.x", after["instruction"])
        self.assertEqual(after["transcript"], RECORD["steps"][2]["transcript"])

    def test_another_user_does_not_see_the_version(self):
        _, lee = self.replay([0, 4])
        self.assertIn("The developer's docuctl version: \n", lee["instruction"])
        self.assertNotIn("user:docuctl_version", lee["state"])

    def test_memory_recalls_an_earlier_session_in_the_same_process(self):
        _, recall = self.replay([0, 1])
        self.assertEqual(recall["transcript"], RECORD["steps"][1]["transcript"])
        self.assertIn("r41", recall["transcript"])

    def test_in_memory_memory_is_empty_after_a_restart(self):
        async def go():
            first = InMemoryMemoryService()
            service = DatabaseSessionService(db_url=self.db_url)
            session = await service.create_session(app_name=assistant.APP, user_id="dana")
            await service.append_event(session, Event(author="user", content=types.Content(
                role="user", parts=[types.Part(text="roll back production to r41")])))
            await first.add_session_to_memory(session)
            found = await first.search_memory(app_name=assistant.APP, user_id="dana", query="r41")
            lost = await InMemoryMemoryService().search_memory(app_name=assistant.APP, user_id="dana", query="r41")
            return len(found.memories), len(lost.memories)
        self.assertEqual(asyncio.run(go()), (1, 0))

    def test_writing_to_a_fetched_session_is_not_saved(self):
        async def go():
            service = DatabaseSessionService(db_url=self.db_url)
            session = await service.create_session(app_name=assistant.APP, user_id="sam")
            session.state["user:docuctl_version"] = "2.x"
            again = await service.get_session(app_name=assistant.APP, user_id="sam", session_id=session.id)
            return dict(again.state)
        self.assertEqual(asyncio.run(go()), RECORD["failures"]["direct_mutation"]["stored"])

    def test_an_append_through_a_stale_session_is_rejected(self):
        async def go():
            service = DatabaseSessionService(db_url=self.db_url)
            session = await service.create_session(app_name=assistant.APP, user_id="sam")
            stale = await service.get_session(app_name=assistant.APP, user_id="sam", session_id=session.id)
            await service.append_event(session, Event(author="docs_assistant", actions=EventActions(state_delta={"note": "a"})))
            await service.append_event(stale, Event(author="docs_assistant", actions=EventActions(state_delta={"note": "b"})))
        with self.assertRaises(StaleSessionError):
            asyncio.run(go())

    def test_a_required_placeholder_without_a_value_raises(self):
        strict = assistant.INSTRUCTION.replace("{user:docuctl_version?}", "{user:docuctl_version}")
        with self.assertRaises(KeyError) as caught:
            self.replay([4], instruction=strict)
        self.assertIn("Context variable not found: `user:docuctl_version`", str(caught.exception))


class CurrentDocuctlContract(unittest.TestCase):
    def test_current_tool_saves_the_docuctl_user_key(self):
        from types import SimpleNamespace
        context=SimpleNamespace(state={})
        result=current_assistant.set_docuctl_version("2.x",context)
        self.assertEqual(result,{"saved":"2.x"})
        self.assertEqual(context.state,{"user:docuctl_version":"2.x"})
    def test_current_agent_and_docs_use_docuctl(self):
        self.assertIn("user:docuctl_version?",current_assistant.root_agent.instruction)
        self.assertIn("docuctl rollback",current_assistant.read_page("rollback")["text"])
        self.assertIn("error",current_assistant.read_page("../secret"))
        self.assertEqual(current_assistant.root_agent.generate_content_config.max_output_tokens,1024)

if __name__ == "__main__":
    unittest.main()
