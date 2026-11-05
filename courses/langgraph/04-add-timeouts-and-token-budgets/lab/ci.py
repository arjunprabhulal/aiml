"""Tools over a stub CI service. Each job has a fixed delay that stands in for network time."""
import asyncio

from langchain_core.tools import tool

TOOL_TIMEOUT = 3.0  # seconds one tool call may take

JOBS = {
    812: {"pr": 415, "name": "unit-tests", "delay": 0.2,
          "log": "FAILED tests/test_client.py::test_default_timeout - AssertionError: expected 10, got 30"},
    815: {"pr": 421, "name": "integration", "delay": 8.0,
          "log": "ERROR: postgres container did not become healthy within 120s"},
}


@tool
async def list_failed_jobs(pr: int) -> list[dict]:
    """List the failed CI jobs of a pull request, by its number."""
    async with asyncio.timeout(TOOL_TIMEOUT):
        await asyncio.sleep(0.1)
        return [{"job_id": i, "name": j["name"]} for i, j in JOBS.items() if j["pr"] == pr]


@tool
async def fetch_job_log(job_id: int) -> str:
    """Fetch the end of one CI job's log."""
    async with asyncio.timeout(TOOL_TIMEOUT):
        job = JOBS.get(job_id)
        if job is None:
            return f"No job {job_id}."
        await asyncio.sleep(job["delay"])
        return job["log"]
