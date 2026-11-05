"""A chosen question with the lesson's real SQLite sessions and process-local memory.

The assistant loads the root .env; SQLite state and process-local memory stay separate.
"""
import argparse
import asyncio
import json
from pathlib import Path
from google.adk.memory import InMemoryMemoryService
import assistant


def parse_options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--user", required=True, help="local test identity, not application authentication")
    parser.add_argument("--session", help="continue this existing session ID for the same user")
    parser.add_argument("--followup", help="one optional second question in a new session in this process")
    parser.add_argument("--remember", action="store_true", help="add first finished session to process-local memory before follow-up")
    parser.add_argument("--db", type=Path, default=Path(__file__).parent / "learner-sessions.db")
    args = parser.parse_args(argv)
    if not args.question.strip() or not args.user.strip() or (args.followup is not None and not args.followup.strip()):
        parser.error("questions and user must contain text")
    if args.remember and not args.followup:
        parser.error("--remember requires --followup in this process")
    return args


async def run_questions(options, agent=assistant.root_agent):
    memory = InMemoryMemoryService()
    url = "sqlite+aiosqlite:///" + str(options.db.resolve())
    runner = assistant.make_runner(memory, agent=agent, db_url=url)
    results = []
    try:
        if options.session:
            session = await runner.session_service.get_session(app_name=assistant.APP, user_id=options.user, session_id=options.session)
            if session is None:
                raise ValueError("No session with that ID for this user; omit --session to create one.")
        else:
            session = await runner.session_service.create_session(app_name=assistant.APP, user_id=options.user)
        for index, text in enumerate([options.question] + ([options.followup] if options.followup else [])):
            if index:
                session = await runner.session_service.create_session(app_name=assistant.APP, user_id=options.user)
            events = await assistant.ask(runner, options.user, session.id, text)
            saved = await runner.session_service.get_session(app_name=assistant.APP, user_id=options.user, session_id=session.id)
            result = {"session_id": session.id, "user_id": options.user, "transcript": assistant.show(events), "state": dict(saved.state)}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False))
            if index == 0 and options.remember:
                await memory.add_session_to_memory(saved)
    finally:
        try:
            await runner.close()
        finally:
            await runner.session_service.close()
    return results


if __name__ == "__main__":
    asyncio.run(run_questions(parse_options()))
