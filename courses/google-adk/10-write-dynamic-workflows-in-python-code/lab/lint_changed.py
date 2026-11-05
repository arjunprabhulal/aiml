"""Lint the docs pages a change touched, in parallel, and let Gemini fix what fails."""
import asyncio
import re
from pathlib import Path

from google.adk import Agent, Context, Event, Workflow
from google.adk.workflow import RetryConfig, node
from google.genai import types
from pydantic import BaseModel

DOCS = Path(__file__).with_name("docs")
MAX_ROUNDS = 2
MAX_CONCURRENT_PAGES = 4  # review_page children in flight at once


class Page(BaseModel):
    path: str
    content: str


class FixRequest(Page):
    findings: list[str]


class FixedPage(BaseModel):
    content: str


@node
def lint_page(node_input: Page):
    """Deterministic checks; the list of findings is the node's output."""
    findings = []
    front = re.match(r"^---\n(.*?)\n---\n", node_input.content, re.S)
    if not front or not re.search(r"^title: \S", front[1], re.M):
        findings.append("front matter has no title")
    findings += [f"insecure link {url}"
                 for url in re.findall(r"\]\((http://[^)]+)\)", node_input.content)]
    levels = [len(marks) for marks in re.findall(r"^(#+) ", node_input.content, re.M)]
    findings += [f"heading jumps from h{a} to h{b}"
                 for a, b in zip(levels, levels[1:]) if b > a + 1]
    return findings


def make_fixer(model=None, retry_delay=2.0, timeout=60.0):
    agent = Agent(
        name="fix_page",
        model=model or "gemini-3.8-flash",  # or LiteLlm(model="ollama_chat/gemma4:e2b")
        generate_content_config=types.GenerateContentConfig(max_output_tokens=1024, thinking_config=types.ThinkingConfig(thinking_level="low")),
        input_schema=FixRequest,
        output_schema=FixedPage,
        instruction=("Rewrite the Markdown page so that every finding is fixed. "
                     "Change nothing else, and return the whole page."),
    )
    # A model call can fail with a 429 or 503, or hang: retry it, and bound each attempt.
    return node(agent, retry_config=RetryConfig(max_attempts=3, initial_delay=retry_delay),
                timeout=timeout)


def build_workflow(model=None, max_concurrent=MAX_CONCURRENT_PAGES, **fixer_options) -> Workflow:
    fixer = make_fixer(model, **fixer_options)

    @node(rerun_on_resume=True)
    async def review_page(ctx: Context, node_input: str):
        """Lint one page; while it fails, ask the fixer and lint again, at most MAX_ROUNDS times."""
        page = Page(path=node_input, content=(DOCS / node_input).read_text())
        findings = await ctx.run_node(lint_page, page)
        found, rounds = list(findings), 0
        while findings and rounds < MAX_ROUNDS:
            rounds += 1
            fixed = await ctx.run_node(fixer, FixRequest(**page.model_dump(), findings=findings))
            page = Page(path=page.path, content=fixed["content"])
            findings = await ctx.run_node(lint_page, page)
        return {"path": page.path, "found": found, "rounds": rounds,
                "left": findings, "content": page.content}

    @node(rerun_on_resume=True)
    async def lint_changed_pages(ctx: Context, node_input: str):
        """Fan out one review_page child per changed Markdown file, at most max_concurrent at once."""
        paths = [path for path in node_input.split() if path.endswith(".md")]
        limit = asyncio.Semaphore(max_concurrent)

        async def review(path):
            async with limit:  # a child starts only when a slot is free
                return await ctx.run_node(review_page, path)

        results = await asyncio.gather(*(review(path) for path in paths))
        lines = [f"{r['path']}: " + ("clean" if not r["found"] else
                 f"fixed in {r['rounds']} round(s): {r['found']}" if not r["left"] else
                 f"still failing after {r['rounds']} rounds: {r['left']}") for r in results]
        yield Event(message="\n".join(lines))

    return Workflow(name="docs_lint", edges=[("START", lint_changed_pages)])
