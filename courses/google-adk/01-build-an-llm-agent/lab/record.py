"""Record two hosted-model turns from the guide; export a private Gemini API key."""
import asyncio
import json
from pathlib import Path

from google.adk.runners import InMemoryRunner
from google.genai import types

from docs_assistant.agent import root_agent

HERE = Path(__file__).resolve().parent


async def main():
    cases = json.loads((HERE / "sample-questions.json").read_text())
    transcript, turns = [], []
    runner = InMemoryRunner(agent=root_agent, app_name="docs_assistant")
    session = await runner.session_service.create_session(
        app_name="docs_assistant", user_id="learner")
    try:
        for case in cases.values():
            question = case["question"]
            message = types.Content(role="user", parts=[types.Part(text=question)])
            events = [event async for event in runner.run_async(
                user_id="learner", session_id=session.id, new_message=message)]
            answer = "".join(part.text or "" for event in events
                             if event.is_final_response() and event.content
                             for part in event.content.parts)
            transcript.extend([f"[user]: {question}", f"[docs_assistant]: {answer}", ""])
            # Opaque signatures are unnecessary for reviewing the answer text.
            projected = [event.model_dump(
                mode="json", exclude_none=True,
                exclude={"content": {"parts": {"__all__": {"thought_signature"}}}})
                for event in events]
            turns.append({"question": question, "answer": answer, "events": projected})
    finally:
        await runner.close()
    (HERE / "example-conversation.txt").write_text("\n".join(transcript))
    (HERE / "recorded-conversation.json").write_text(json.dumps({
        "execution_mode": "fresh-hosted-model-run", "model": root_agent.model,
        "turns": turns}, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
