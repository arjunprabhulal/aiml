"""Record real Gemini events for both Runner modes. Run: python record.py.

Requires GOOGLE_API_KEY. Offline tests replay these model responses through
Runner without requesting new responses.
"""
import asyncio
import json
import time
from importlib.metadata import version
from pathlib import Path
from google.adk import Runner
from google.adk.agents import RunConfig
from google.adk.agents.run_config import StreamingMode
from google.adk.sessions import InMemorySessionService
from google.genai import types
import ask

HERE = Path(__file__).resolve().parent
QUESTION = 'How do I undo the last production deploy?'

async def capture(mode):
    sessions = InMemorySessionService()
    runner = Runner(app_name=ask.APP, agent=ask.root_agent, session_service=sessions)
    session = await sessions.create_session(app_name=ask.APP, user_id=ask.USER)
    config = RunConfig(streaming_mode=mode, max_llm_calls=4)
    events, elapsed = [], []
    started = time.perf_counter()
    try:
        async for event in runner.run_async(user_id=ask.USER, session_id=session.id,
                new_message=types.Content(role='user', parts=[types.Part(text=QUESTION)]),
                run_config=config, yield_user_message=True):
            events.append(event)
            elapsed.append(round(time.perf_counter() - started, 3))
        stored = await sessions.get_session(app_name=ask.APP, user_id=ask.USER, session_id=session.id)
    finally:
        await runner.close()
    turns = []
    for event in events:
        if event.content and event.content.role == 'model':
            content = event.content.model_dump(mode='json', exclude_none=True)
            for part in content.get('parts', []):
                part.pop('thought_signature', None)
            turns.append({'content': content, 'partial': bool(event.partial)})
    return {'lines': [ask.describe(e) for e in events], 'seconds': elapsed,
            'stored': len(stored.events), 'answer': ask.answer(events), 'model_turns': turns}

async def main():
    record = {'question': QUESTION, 'model': str(ask.root_agent.model),
              'execution_mode': 'fresh-hosted-model-inference',
              'environment': {'google-adk': version('google-adk'), 'google-genai': version('google-genai')}}
    for mode in (StreamingMode.NONE, StreamingMode.SSE):
        record[mode.name.lower()] = await capture(mode)
    (HERE / 'recorded-events.json').write_text(json.dumps(record, indent=1) + '\n')
    for mode in ('none', 'sse'):
        print(mode.upper(), *record[mode]['lines'], sep='\n')

if __name__ == '__main__':
    asyncio.run(main())
