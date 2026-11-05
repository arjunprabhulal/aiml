"""Record: screen frames with a spoken question, push-to-talk, voice precedence and four failures."""
import asyncio
import json
import wave
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

import live_harness
from live_harness import RecordingGemini, environment, MODEL, read_pcm, say_audio, say_text, spoken, talk
from media import build_agent, push_to_talk, session_config, share_screen, then

HERE = Path(__file__).parent
FRAMES = [(HERE / f"frame-{n}.jpg").read_bytes() for n in (1, 2, 3)]


async def run(name, agent_model, turn, run_config, agent_voice=None, timeout=60, check=None):
    model = RecordingGemini(model=agent_model, connections=[])
    runner = Runner(app_name="voice_docs", agent=build_agent(model, agent_voice), session_service=InMemorySessionService())
    session = await runner.session_service.create_session(app_name="voice_docs", user_id="dev")
    entry = {"name": name}
    try:
        rows = await talk(runner, session.id, run_config, [turn], timeout=timeout)
        entry.update(heard=spoken(rows, "input_transcription"), answer=spoken(rows), events=len(rows))
        if check:
            entry["check"] = {"expects": check, "passed": check in entry["answer"]}
    except asyncio.TimeoutError:
        entry["error"] = f"TimeoutError: no turn_complete within {timeout} s"
    except Exception as error:
        entry["error"] = f"{type(error).__name__}: {str(error).splitlines()[0][:240]}"
    entry["connections"] = [{"model": c["model"], "config": c.get("config"), "traffic": c["traffic"]} for c in model.connections]
    print(f"[{name}] " + (entry.get("error") or f"heard={entry['heard']!r} said={entry['answer']!r}"))
    return entry


async def main():
    with wave.open(str(HERE / "slow.wav")) as clip:  # an 8 kHz microphone, sent unconverted
        slow = clip.readframes(clip.getnframes())
    runs = [
        await run("screen frames, then a spoken question", MODEL,
                  then(share_screen(FRAMES), say_audio(read_pcm(HERE / "which-test.wav"))),
                  session_config(), check="test_resume_after_drop"),
        await run("push-to-talk turn", MODEL, push_to_talk(read_pcm(HERE / "question.wav")),
                  session_config(push_to_talk=True), check="16"),
        await run("agent voice over session voice", MODEL, say_text("Say hello."), session_config("Kore"), agent_voice="Puck"),
        await run("8 kHz audio labelled 16 kHz", MODEL, say_audio(slow), session_config(), check="16"),
        await run("VAD off, no activity signals", MODEL, say_audio(read_pcm(HERE / "question.wav")),
                  session_config(push_to_talk=True), timeout=25),
        await run("unknown voice name", MODEL, say_text("Say hello."), session_config("Narrator")),
    ]
    from google.adk.agents.run_config import RunConfig
    runs.append(await run("current Live model greeting", MODEL, say_text("Say hello."),
                          RunConfig(response_modalities=["AUDIO"])))
    record = {"environment": environment(), "runs": runs}
    (HERE / "media-run.json").write_text(json.dumps(record, indent=1) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
