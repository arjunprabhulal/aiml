"""Record lesson runs on the Live API: two answered turns, ungrounded trials and three failures."""
import asyncio
import json
from pathlib import Path

from google.adk.agents.run_config import RunConfig

from live_harness import RecordingGemini, environment, MODEL, read_pcm, say_audio, say_text, spoken
from voice_docs_helper import ask, build_agent, mentions

HERE = Path(__file__).parent
QUESTION = "What does ADK stand for?"


def error_text(error) -> str:
    return f"{type(error).__name__}: {str(error).splitlines()[0][:240]}"


async def answered(name, turn, facts, grounded=True):
    model = RecordingGemini(model=MODEL, connections=[])
    rows, answer = await ask(build_agent(model, grounded=grounded), turn)
    run = {"name": name, "grounded": grounded, "answer": answer, "heard": spoken(rows, "input_transcription"),
           "expected": list(facts), "check_passed": mentions(answer, *facts), "events": rows,
           "connections": model.connections}
    print(f"[{name}] {answer!r} check_passed={run['check_passed']}")
    return run


async def failure(name, coro):
    try:
        await coro
        return {"name": name, "error": None}
    except Exception as error:  # recorded, not handled: these runs show what breaks
        print(f"[{name}] {error_text(error)}")
        return {"name": name, "error": error_text(error)}


async def missing_session():
    from google.adk.agents import LiveRequestQueue
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    runner = Runner(app_name="voice_docs", agent=build_agent(), session_service=InMemorySessionService())
    async for _ in runner.run_live(user_id="dev", session_id="never-created",
                                   live_request_queue=LiveRequestQueue(), run_config=RunConfig()):
        break


async def main():
    runs = [await answered("text turn", say_text(QUESTION), ["Agent Development Kit"]),
            await answered("spoken turn", say_audio(read_pcm(HERE / "question.wav")), ["16"])]
    for trial in range(1, 4):
        run = await answered(f"ungrounded trial {trial}", say_text(QUESTION), ["Agent Development Kit"], grounded=False)
        run.pop("connections")
        runs.append(run)
    failures = [
        await failure("TEXT response modality", ask(build_agent(), say_text(QUESTION), RunConfig(response_modalities=["TEXT"]))),
        await failure("standard Gemini model", ask(build_agent("gemini-3.8-flash"), say_text(QUESTION))),
        await failure("session not created", missing_session()),
    ]
    record = {"environment": environment(), "question": QUESTION, "runs": runs, "failures": failures}
    (HERE / "stream-run.json").write_text(json.dumps(record, indent=1) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
