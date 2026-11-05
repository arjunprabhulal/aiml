"""Pull requests in two repositories. The diff summaries name the longest changed line."""
from langchain_core.tools import tool

PULL_REQUESTS = {
    501: {"repo": "acme/api", "title": "Add pagination to GET /projects",
          "diff": "api/projects.py: add limit and cursor query parameters; longest changed line is 96 characters\n"
                  "tests/test_projects.py: add test_second_page"},
    502: {"repo": "acme/web", "title": "Show the project count in the sidebar",
          "diff": "web/sidebar.tsx: render the project count badge; longest changed line is 96 characters"},
}


@tool
def get_diff(number: int) -> str:
    """Get the changed files and a one-line summary of each change for a pull request."""
    return PULL_REQUESTS[number]["diff"]
