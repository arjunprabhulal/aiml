"""Replay the recorded Gemini turns against a real FileArtifactService in a temporary folder, offline.

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

from google.adk import Runner  # noqa: E402
from google.adk.artifacts import FileArtifactService  # noqa: E402
from google.adk.errors.input_validation_error import InputValidationError  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

import assistant  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD = json.loads((HERE / "recorded-runs.json").read_text(encoding="utf-8"))


class ReplayLlm(BaseLlm):
    turns: list
    requests: list = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(json.dumps([c.model_dump(mode="json", exclude_none=True) for c in llm_request.contents]))
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


class Artifacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def replay(self, upto: int):
        """Replay steps 1..upto; a new run number means a new Runner and session on the same store."""
        async def go():
            out, runner, run = [], None, None
            for step in RECORD["steps"][:upto]:
                if step["run"] != run:
                    if runner:
                        await runner.close()
                    model = ReplayLlm(model="replay", turns=[], requests=[])
                    runner = assistant.make_runner(assistant.root_agent.clone(update={"model": model}), self.store)
                    session = await runner.session_service.create_session(app_name="docs", user_id="dana")
                    run = step["run"]
                model.turns[:] = step["model_turns"]
                start = len(model.requests)
                message = assistant.upload(HERE / "ship.toml", step["message"]) if step["kind"] == "upload" else step["message"]
                events = await assistant.ask(runner, "dana", session.id, message)
                keys = await runner.artifact_service.list_artifact_keys(app_name="docs", user_id="dana", session_id=session.id)
                out.append({"requests": model.requests[start:], "events": events, "keys": keys, "session": session.id})
            await runner.close()
            return out
        return asyncio.run(go())

    def test_an_upload_becomes_an_artifact_and_a_placeholder(self):
        step = self.replay(1)[0]
        self.assertEqual(step["keys"], ["ship.toml"])
        self.assertIn('[Uploaded Artifact: \\"ship.toml\\"]', step["requests"][0])
        self.assertNotIn("SEARCH_INDEX_URL", step["requests"][0])  # the file itself is not in the message

    def test_the_file_is_in_the_request_only_after_load_artifacts(self):
        steps = self.replay(5)
        counts = [sum("SEARCH_INDEX_URL" in r for r in s["requests"]) for s in steps]
        self.assertEqual(counts, [s["requests_with_file"] for s in RECORD["steps"]])
        self.assertEqual(counts[1:], [0, 0, 0, 0])

    def test_saving_a_filename_again_creates_a_new_version(self):
        steps = self.replay(3)
        service = FileArtifactService(root_dir=self.store)
        versions = asyncio.run(service.list_versions(app_name="docs", user_id="dana", session_id=steps[0]["session"],
                                                     filename="review.md"))
        self.assertEqual(versions, [0, 1])
        delta = {k: v for e in steps[2]["events"] for k, v in e.actions.artifact_delta.items()}
        self.assertEqual(delta, {"review.md": 1})

    def test_only_user_scoped_files_reach_a_new_session(self):
        steps = self.replay(5)
        self.assertEqual(steps[3]["keys"], ["review.md", "ship.toml", "user:checklist.md"])
        self.assertEqual(steps[4]["keys"], ["user:checklist.md"])  # review.md is still on disk, in session 1

    def test_a_parent_traversal_filename_is_refused(self):
        service = FileArtifactService(root_dir=self.store)
        with self.assertRaisesRegex(InputValidationError, "parent traversal"):
            asyncio.run(service.save_artifact(app_name="docs", user_id="dana", session_id="s",
                                              filename="../../ship.toml", artifact=types.Part(text="x")))

    def test_an_invalid_model_filename_returns_a_tool_error(self):
        model = ReplayLlm(model="replay", requests=[], turns=[
            {"role": "model", "parts": [{"function_call": {"name": "save_text_file",
             "args": {"filename": "../../outside.md", "text": "review"}, "id": "bad-name"}}]},
            {"role": "model", "parts": [{"text": "Choose a filename inside the artifact store."}]},
        ])

        async def go():
            runner = assistant.make_runner(assistant.root_agent.clone(update={"model": model}), self.store)
            session = await runner.session_service.create_session(app_name="docs", user_id="dana")
            try:
                events = await assistant.ask(runner, "dana", session.id, "Save the review.")
                keys = await runner.artifact_service.list_artifact_keys(
                    app_name="docs", user_id="dana", session_id=session.id)
                return events, keys
            finally:
                await runner.close()

        events, keys = asyncio.run(go())
        results = [r.response for event in events for r in event.get_function_responses()]
        self.assertIn("parent traversal", results[0]["error"])
        self.assertEqual(keys, [])
        self.assertTrue(events[-1].is_final_response())

    def test_a_missing_file_loads_as_none(self):
        service = FileArtifactService(root_dir=self.store)
        self.assertIsNone(asyncio.run(service.load_artifact(app_name="docs", user_id="dana", session_id="s",
                                                            filename="review.md")))

    def test_a_runner_without_an_artifact_service_fails(self):
        model = ReplayLlm(model="replay", turns=[], requests=[])
        runner = Runner(app_name="docs", agent=assistant.root_agent.clone(update={"model": model}),
                        session_service=InMemorySessionService(), auto_create_session=True)
        with self.assertRaisesRegex(ValueError, "Artifact service is not initialized"):
            asyncio.run(assistant.ask(runner, "dana", "s", "Save the text 'hello' as note.md."))
        self.assertEqual(model.requests, [])  # it fails while building the first request


if __name__ == "__main__":
    unittest.main()
