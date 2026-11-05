"""Typed function tools for the docs assistant: two reads and one write."""
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

DOCS = Path(__file__).resolve().parent / "docs"
Page = Literal["config", "deploy", "rollback", "tokens"]
ISSUES: list[dict] = []  # every docs issue the tool filed, in order


def search_docs(query: Annotated[str, Field(min_length=2)], limit: Annotated[int, Field(ge=1, le=5)] = 3) -> dict:
    """Find documentation pages whose text contains every word in the query.

    Args:
        query: Words to look for, for example "rollback production".
        limit: The largest number of pages to return, from 1 to 5.
    """
    words = query.lower().split()
    hits = []
    for path in sorted(DOCS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if all(word in text.lower() for word in words):
            hits.append({"page": path.stem, "title": text.splitlines()[0].lstrip("# ")})
    return {"pages": hits[:limit], "total": len(hits)}


def read_page(page: Page) -> dict:
    """Read one documentation page in full."""
    return {"page": page, "text": (DOCS / f"{page}.md").read_text(encoding="utf-8")}


def file_docs_issue(
    page: Page,
    kind: Literal["outdated", "incorrect", "unclear"],
    summary: Annotated[str, Field(min_length=10, max_length=200)],
) -> dict:
    """File an issue against a documentation page. This writes to the docs issue tracker.

    Args:
        page: The page the issue is about.
        kind: outdated, incorrect or unclear.
        summary: One sentence that says what is wrong, 10 to 200 characters.
    """
    issue = {"id": f"DOC-{len(ISSUES) + 1}", "page": page, "kind": kind, "summary": summary}
    ISSUES.append(issue)
    return issue
