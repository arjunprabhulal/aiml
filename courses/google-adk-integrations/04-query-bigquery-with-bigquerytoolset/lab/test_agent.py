"""Replay the recorded Gemini turns through the real BigQueryToolset, offline.

Run: python -m unittest -v test_agent.py
The model is replaced by its recorded turns and the BigQuery client by a stub, so nothing reaches
Google Cloud. ADK's own code decides what runs: the dry-run check, the job settings and the guardrails.
"""
import asyncio
import json
import logging
import os
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

from google.adk.integrations.bigquery import client as bq_client  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from pydantic import ValidationError  # noqa: E402

# Fixture project only: cloud clients and model calls are replaced in these tests.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "vertex-ai-experminent")
import agent  # noqa: E402

RECORD = json.loads(Path(__file__).with_name("recorded-runs.json").read_text(encoding="utf-8"))
OFFLINE = Credentials(token="offline-test")  # a valid-looking token; the stub never sends it


def setUpModule():
    warnings.simplefilter("ignore")  # unittest resets filters; ADK flags its BigQuery tools as experimental


class ReplayLlm(BaseLlm):
    turns: list

    async def generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(content=types.Content.model_validate(self.turns.pop(0)))


class StubBigQuery:
    """Answers the client calls ADK makes; records every job ADK would have started."""

    def __init__(self, rows):
        self.rows, self.dry_runs, self.executed = list(rows), [], []

    def query(self, query, project=None, job_config=None):
        self.dry_runs.append(query)
        kind = query.lstrip().split()[0].upper()
        return SimpleNamespace(statement_type="SELECT" if kind in ("SELECT", "WITH") else kind,
                               destination=None, to_api_repr=lambda: {"query": query})

    def query_and_wait(self, query, job_config=None, project=None, max_results=None):
        self.executed.append({"query": query, "maximum_bytes_billed": job_config.maximum_bytes_billed,
                              "labels": dict(job_config.labels)})
        return [SimpleNamespace(items=lambda r=row: r.items()) for row in (self.rows.pop(0) if self.rows else [])]

    def list_tables(self, dataset):
        return [SimpleNamespace(table_id=t) for t in ("page_views", "search_queries")]

    def get_table(self, ref):
        return SimpleNamespace(to_api_repr=lambda: {"id": str(ref)})


def errors(key: str) -> list[dict]:
    return [r["response"] for r in RECORD["runs"][key]["tool_results"]
            if isinstance(r["response"], dict) and r["response"].get("status") == "ERROR"]


def replay(key: str) -> StubBigQuery:
    run = RECORD["runs"][key]
    rows = [r["response"].get("rows", []) for r in run["tool_results"]
            if r["tool"] == "execute_sql" and r["response"].get("status") == "SUCCESS"]
    stub = StubBigQuery(rows)
    model = ReplayLlm(model="replay", turns=list(run["model_turns"]))
    with mock.patch.object(bq_client, "get_bigquery_client", return_value=stub):
        asyncio.run(agent.ask("replayed question", agent.build_agent(model, agent.bigquery(credentials=OFFLINE))))
    return stub


class BigQueryToolsetTests(unittest.TestCase):
    def test_tool_filter_offers_only_the_read_tools(self):
        offered = asyncio.run(agent.list_tools(credentials=OFFLINE))
        self.assertEqual(sorted(offered), sorted(RECORD["tools"]))
        hidden = set(RECORD["all_tools"]) - set(offered)
        self.assertTrue({"forecast", "detect_anomalies", "ask_data_insights"} <= hidden)

    def test_every_query_runs_with_the_cap_and_the_lesson_label(self):
        stub = replay("traffic")
        self.assertTrue(stub.executed)
        for job in stub.executed:
            self.assertEqual(job["maximum_bytes_billed"], 10 * 1024 * 1024)
            self.assertEqual(job["labels"]["aiml-lesson"], "query-bigquery-with-bigquerytoolset")

    def test_blocked_mode_rejects_a_delete_before_it_runs(self):
        stub = replay("write")
        self.assertTrue(any(q.lstrip().upper().startswith("DELETE") for q in stub.dry_runs))
        self.assertFalse(any(job["query"].lstrip().upper().startswith("DELETE") for job in stub.executed))
        self.assertEqual(errors("write")[0]["error_details"], "Read-only mode only supports SELECT statements.")

    def test_a_query_over_the_bytes_cap_fails_without_billing(self):
        self.assertIn("Query exceeded limit for bytes billed: 10485760.", errors("bytes")[0]["error_details"])
        capped = [j for j in RECORD["jobs"] if j["error"] == "bytesBilledLimitExceeded"]
        self.assertTrue(capped and all(j["total_bytes_billed"] in (None, 0) for j in capped))

    def test_a_cap_below_10_mib_is_refused_at_startup(self):
        with self.assertRaises(ValidationError):
            agent.tool_config(maximum_bytes_billed=1_000_000)
        self.assertIn("must be set >=10485760", RECORD["cap_below_minimum"])

    def test_compute_project_id_keeps_jobs_in_the_lesson_project(self):
        call = {"role": "model", "parts": [{"function_call": {"name": "execute_sql", "args": {
            "project_id": "bigquery-public-data", "query": "SELECT 1"}}}]}
        done = {"role": "model", "parts": [{"text": "done"}]}
        stub = StubBigQuery([])
        model = ReplayLlm(model="replay", turns=[call, done])
        with mock.patch.object(bq_client, "get_bigquery_client", return_value=stub):
            events = asyncio.run(agent.ask("q", agent.build_agent(model, agent.bigquery(credentials=OFFLINE))))
        self.assertIn("is restricted to execute queries only in the project", agent.show(events))
        self.assertEqual(stub.dry_runs, [])


if __name__ == "__main__":
    unittest.main()
