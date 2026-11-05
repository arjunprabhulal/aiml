"""Record: a barge-in, the saved session, a second connection on the same session, a reused queue."""
import asyncio
import json
from pathlib import Path

from google.adk.agents import LiveRequestQueue

from captions import RUN_CONFIG, Captions, build_agent, make_runner, open_session, remember_questions, stored
from live_harness import RecordingGemini, environment, MODEL, read_pcm, say_audio, say_text, spoken, summarize

HERE = Path(__file__).parent
LONG = "Read me every limit on the page, one at a time, with a sentence about each."


async def barge_in(runner, session_id, queue):
    """Ask a long question, then talk over the answer once its audio starts."""
    rows, interrupted = [], False
    await say_text(LONG)(queue)
    async for event in runner.run_live(user_id="dev", session_id=session_id,
                                       live_request_queue=queue, run_config=RUN_CONFIG):
        row = summarize(event)
        rows.append(row)
        if row.get("audio_bytes") and not interrupted:
            interrupted = True
            await say_audio(read_pcm(HERE / "interrupt.wav"))(queue)
        if sum(1 for r in rows if r.get("turn_complete")) == 2:
            break
    queue.close()
    return rows


async def one_turn(runner, session_id, queue, turn, timeout=60):
    rows = []

    async def loop():
        await turn(queue)
        async for event in runner.run_live(user_id="dev", session_id=session_id,
                                           live_request_queue=queue, run_config=RUN_CONFIG):
            rows.append(summarize(event))
            if event.turn_complete:
                break
    try:
        await asyncio.wait_for(loop(), timeout)
        outcome = "turn complete"
    except asyncio.TimeoutError:
        outcome = f"no event for {timeout} s"
    queue.close()
    return rows, outcome


async def main():
    model = RecordingGemini(model=MODEL, connections=[])
    runner = make_runner(build_agent(model))
    session = await open_session(runner, "review-call")
    first = await asyncio.wait_for(barge_in(runner, session.id, LiveRequestQueue()), 120)
    captions = Captions()
    for row in first:
        captions.apply(row)
    saved_after_first = stored(await open_session(runner, "review-call"))
    second, _ = await one_turn(runner, session.id, LiveRequestQueue(), say_audio(read_pcm(HERE / "followup.wav")))
    asked = await remember_questions(runner, await open_session(runner, "review-call"))
    third, _ = await one_turn(runner, session.id, LiveRequestQueue(), say_text("What did I ask you a moment ago?"))
    closed = LiveRequestQueue()
    closed.close()
    reused, outcome = await one_turn(runner, session.id, closed, say_text("Are you still there?"), timeout=20)
    print(f"[first connection] interrupted={any(r.get('interrupted') for r in first)} "
          f"resumption updates={sum(1 for r in first if 'resumption_update' in r)}")
    for who, line in captions.lines:
        print(f"  {who}: {line}")
    print(f"[saved] {len(saved_after_first)} events, audio parts saved: "
          f"{sum('inline_data' in r['kinds'] for r in saved_after_first)}")
    print(f"[second connection] history sent: {model.connections[1]["traffic"][0]["turns"]}")
    print(f"  user: {spoken(second, 'input_transcription')}\n  agent: {spoken(second)}")
    print(f"[third connection, state asked={asked}]\n  agent: {spoken(third)}")
    print(f"[reused closed queue] {len(reused)} events, {outcome}")
    record = {"environment": environment(), "first": first, "captions": captions.lines,
              "saved_after_first": saved_after_first, "second": second, "third": third, "asked": asked,
              "reused_queue": {"events": reused, "outcome": outcome}, "connections": model.connections}
    (HERE / "events-run.json").write_text(json.dumps(record, indent=1) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
