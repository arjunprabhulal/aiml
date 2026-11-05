"""Replay the recorded two-node call through ADK's live workflow runner; no network."""
import asyncio
import copy
import json
import logging
import unittest
from pathlib import Path

from google.adk.agents import Agent, LoopAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

import live_harness
from live_harness import ReplayLive, say_text, talk, wait_for_turn
from record import RUN_CONFIG, TURNS
from voice_intake import PAGES, DocsQuestion, build_workflow, transcript_by_node

HERE = Path(__file__).parent
RECORD = json.loads((HERE / "workflow-run.json").read_text())
RUNS = {run["name"]: run for run in RECORD["runs"]}
HAPPY = RUNS["two live nodes"]
live_harness.PACE = 0
logging.disable(logging.CRITICAL)


def replay():
    return ReplayLive(model=RECORD["environment"]["workflow_model"], connections=copy.deepcopy(HAPPY["connections"]), opened=[])


def call(root, turns, timeout=10):
    async def run():
        runner = Runner(app_name="voice_docs", agent=root, session_service=InMemorySessionService())
        session = await runner.session_service.create_session(app_name="voice_docs", user_id="dev")
        return await talk(runner, session.id, RUN_CONFIG, turns, timeout=timeout)
    return asyncio.run(run())


class VoiceIntake(unittest.TestCase):
    def test_one_stream_carries_both_nodes_in_order(self):
        rows = call(build_workflow(replay()), [say_text(t) for t in TURNS] + [wait_for_turn()])
        authors = [r["author"] for r in rows if r.get("audio_bytes")]
        self.assertEqual(sorted(set(authors), key=authors.index), ["intake", "answer"])

    def test_the_typed_handoff_becomes_the_next_nodes_history(self):
        model = replay()
        call(build_workflow(model), [say_text(t) for t in TURNS] + [wait_for_turn()])
        request, connection = model.opened[1]
        self.assertEqual(connection.received[0], ("history", 1))
        handoff = DocsQuestion.model_validate_json(request.contents[0].parts[0].text)
        self.assertIn(handoff.page, PAGES)
        [args] = [a for a in HAPPY["finish_task"] if "page" in a]
        self.assertEqual(handoff, DocsQuestion(**args))

    def test_finish_task_can_end_a_node_before_its_finished_transcript(self):
        answer = [r for r in HAPPY["events"] if r["author"] == "answer" and "output_transcription" in r]
        self.assertTrue(answer)
        self.assertTrue(all(r.get("partial") for r in answer))
        self.assertTrue(transcript_by_node(HAPPY["events"])["answer"].endswith("[partial]"))

    def test_a_single_turn_node_skips_the_live_connection(self):
        with self.assertRaisesRegex(NotImplementedError, "only replays run_live"):
            call(build_workflow(replay(), answer_mode=None), [say_text(t) for t in TURNS] + [wait_for_turn()])
        self.assertIn("only supports real-time bidirectional streaming", RUNS["answer node left as single_turn"]["error"])

    def test_loop_agent_is_not_supported_under_run_live(self):
        loop = LoopAgent(name="retry", sub_agents=[Agent(name="answer", model=replay(), instruction="Answer briefly.")])
        with self.assertRaises(NotImplementedError):
            call(loop, [say_text(TURNS[0])])


if __name__ == "__main__":
    unittest.main()
