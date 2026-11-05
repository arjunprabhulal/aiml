"""The custom tool root_agent.yaml names by its fully qualified name: docs_config.tools.read_page."""
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
PAGES = sorted(p.stem for p in DOCS.glob("*.md"))


def read_page(page: str) -> dict:
    """Read one page of the docuctl documentation.

    Args:
        page: The page name: config, deploy, rollback or tokens.
    """
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    return {"page": page, "text": (DOCS / f"{page}.md").read_text(encoding="utf-8")}
