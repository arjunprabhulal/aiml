"""Run the private-docs assistant on Gemini with Agent Search and save the runs.

python record.py not-indexed   # right after datastore.py create, before indexing finishes
python record.py               # once datastore.py status shows every document indexed
Both merge into recorded-runs.json; the second also writes run-output.txt. The tests replay them offline.
"""
import asyncio
import json
import logging
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import agent  # noqa: E402

HERE = Path(__file__).resolve().parent
RECORD = HERE / "recorded-runs.json"
QUESTIONS = {
    "postmortem": ("Why did staging deploys get stuck on September 30, and what changed?", "platform"),
    "rotate": ("How do I rotate the release signing key, and when can I revoke the old one?", "platform"),
    "team-docs": ("How do I rotate the release signing key?", "docs"),
    "team-platform": ("How do I rotate the release signing key?", "platform"),
    "not-found": ("What is our on-call rotation for the docs site?", "docs"),
}


def redact(text: str) -> str:
    return re.sub(r"projects/\d+", "projects/<project-number>", text)


async def run(question: str, team: str | None) -> dict:
    requests, turns = [], []

    def keep_request(callback_context, llm_request):
        for tool in llm_request.config.tools or []:
            if tool.retrieval:
                requests.append(tool.retrieval.model_dump(mode="json", exclude_none=True))

    def keep_turn(callback_context, llm_response):
        content = llm_response.content.model_dump(mode="json", exclude_none=True) if llm_response.content else None
        for part in (content or {}).get("parts", []):
            part.pop("thought_signature", None)
        turns.append({
            "content": content,
            "grounding_metadata": llm_response.grounding_metadata.model_dump(mode="json", exclude_none=True)
            if llm_response.grounding_metadata else None})

    recording = agent.build_agent().clone(update={"before_model_callback": keep_request, "after_model_callback": keep_turn})
    events = await agent.ask(question, recording, team=team)
    final = [e for e in events if e.grounding_metadata]
    return {"question": question, "team": team, "transcript": redact(agent.show(events)), "retrieval": requests,
            "sources": agent.sources(final[-1]) if final else [], "model_turns": json.loads(redact(json.dumps(turns)))}


async def main(mode: str) -> None:
    record = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    record["model"] = agent.MODEL
    if mode == "not-indexed":
        record["not_indexed"] = await run(*QUESTIONS["postmortem"])
    else:
        record["runs"] = {key: await run(*q) for key, q in QUESTIONS.items()}
        out = []
        for r in record["runs"].values():
            prefix = f"DOCS_TEAM={r['team']} " if r["team"] else ""
            out.append(f'$ {prefix}python agent.py "{r["question"]}"\n{r["transcript"]}\n')
        (HERE / "run-output.txt").write_text("\n".join(out), encoding="utf-8")
        print("\n".join(out))
    RECORD.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if sys.argv[1:] else "runs"))
