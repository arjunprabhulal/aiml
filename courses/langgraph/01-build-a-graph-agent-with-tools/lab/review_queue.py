"""A small pull-request queue and the three read-only tools the review agent uses."""
from langchain_core.tools import tool

PULL_REQUESTS = {
    412: {
        "title": "Retry webhook delivery on 503",
        "author": "mlee",
        "ci": "passed",
        "diff": "webhooks/sender.py: wrap post() in a loop of 3 attempts with 2s backoff on HTTP 503\n"
                "tests/test_sender.py: add test_retries_on_503",
    },
    415: {
        "title": "Raise the default HTTP timeout to 30s",
        "author": "dkim",
        "ci": "failed: tests/test_client.py::test_default_timeout expected 10, got 30",
        "diff": "client/http.py: DEFAULT_TIMEOUT = 10 -> DEFAULT_TIMEOUT = 30",
    },
    418: {
        "title": "Remove the unused legacy CSV export",
        "author": "apatel",
        "ci": "passed",
        "diff": "export/csv_legacy.py: deleted (212 lines)\nexport/__init__.py: drop csv_legacy import",
    },
}


class UnknownPullRequest(LookupError):
    """The model asked for a pull request that is not in the queue."""


def _pull_request(number: int) -> dict:
    if number not in PULL_REQUESTS:
        raise UnknownPullRequest(f"There is no open pull request #{number}.")
    return PULL_REQUESTS[number]


@tool
def list_open_prs() -> list[dict]:
    """List the open pull requests with their number, title and author."""
    return [{"number": n, "title": p["title"], "author": p["author"]} for n, p in PULL_REQUESTS.items()]


@tool
def get_diff(number: int) -> str:
    """Get the changed files and a one-line summary of each change for a pull request."""
    return _pull_request(number)["diff"]


@tool
def get_ci_status(number: int) -> str:
    """Get the CI result for a pull request: 'passed', or 'failed:' and the failing test."""
    return _pull_request(number)["ci"]
