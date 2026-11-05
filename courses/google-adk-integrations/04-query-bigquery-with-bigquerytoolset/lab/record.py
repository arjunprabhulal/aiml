"""Run the BigQuery docs analyst on Gemini against the lesson dataset and save the runs.

Run from this folder after setup.sh, with GOOGLE_API_KEY and Application Default Credentials:
python record.py. Writes recorded-runs.json and run-output.txt; the tests replay them offline.
"""
import asyncio
import datetime
import json
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import google.auth  # noqa: E402
from google.cloud import bigquery as bq  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import agent  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = {
    "traffic": "Which three docs pages had the most views in the week of October 12, and which site searches returned no results?",
    "write": "Delete the rows in search_queries that returned results; we only need the failed searches.",
    "bytes": "How many questions in bigquery-public-data.stackoverflow.posts_questions are tagged google-adk?",
}


async def run(key: str) -> dict:
    turns, declarations, results = [], {}, []

    def keep_turn(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)

    def keep_tools(callback_context, llm_request):
        for tool in llm_request.config.tools or []:
            for d in tool.function_declarations or []:
                declarations[d.name] = d.model_dump(mode="json", exclude_none=True)

    def keep_result(tool, args, tool_context, tool_response):
        results.append({"tool": tool.name, "args": args, "response": tool_response})

    recording = agent.build_agent().clone(update={
        "after_model_callback": keep_turn, "before_model_callback": keep_tools, "after_tool_callback": keep_result})
    events = await agent.ask(QUESTIONS[key], recording)
    return {"question": QUESTIONS[key], "transcript": agent.show(events), "model_turns": turns,
            "declarations": declarations, "tool_results": results}


def lesson_jobs(since: datetime.datetime) -> list[dict]:
    """The query jobs this recording ran, read back from BigQuery's job list (listing jobs is free)."""
    credentials, _ = google.auth.default()
    client = bq.Client(project=agent.PROJECT, credentials=credentials)
    jobs = []
    for job in client.list_jobs(min_creation_time=since, max_results=200):
        if (job.labels or {}).get("aiml-lesson") != "query-bigquery-with-bigquerytoolset" or job.job_type != "query":
            continue
        jobs.append({"state": job.state, "statement_type": job.statement_type, "tool": job.labels.get("adk-bigquery-tool"),
                     "total_bytes_processed": job.total_bytes_processed, "total_bytes_billed": job.total_bytes_billed,
                     "error": (job.error_result or {}).get("reason")})
    return jobs


async def main() -> None:
    since = datetime.datetime.now(datetime.timezone.utc)
    record = {"model": agent.MODEL, "dataset": agent.DATASET, "tools": await agent.list_tools(),
              "all_tools": await agent.list_tools(tool_filter=None), "runs": {}}
    for key in QUESTIONS:
        record["runs"][key] = await run(key)
    record["declarations"] = record["runs"]["traffic"]["declarations"]
    for r in record["runs"].values():
        r.pop("declarations")
    try:
        agent.tool_config(maximum_bytes_billed=1_000_000)
    except ValidationError as error:
        record["cap_below_minimum"] = error.errors()[0]["msg"]
    record["jobs"] = lesson_jobs(since)
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out = [f"$ python agent.py --tools\n{record['tools']}\n"]
    for r in record["runs"].values():
        out.append(f'$ python agent.py "{r["question"]}"\n{r["transcript"]}\n')
    (HERE / "run-output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(json.dumps(record["jobs"], indent=1), record.get("cap_below_minimum"))


if __name__ == "__main__":
    asyncio.run(main())
