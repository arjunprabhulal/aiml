"""Prepare a release page from three independent branches that run at the same time."""
import asyncio
import re
from pathlib import Path

from google.adk import Agent, Event, Workflow
from google.adk.workflow import JoinNode, RetryConfig, node
from google.genai import types
from pydantic import BaseModel

HERE = Path(__file__).parent
PAGE = re.compile(r"See (/\S*/)\.")


class Release(BaseModel):
    version: str
    entries: list[str]
    sitemap: str


class Highlights(BaseModel):
    bullets: list[str]


class UpgradeSteps(BaseModel):
    steps: list[str]


class LinkReport(BaseModel):
    missing: list[str]


def load_release(node_input: str):
    """Function node: parse the release file the run starts from."""
    lines = node_input.strip().splitlines()
    entries = [line[2:] for line in lines if line.startswith("- ")]
    sitemap = next(line[8:].strip() for line in lines if line.startswith("sitemap:"))
    return Event(output=Release(version=lines[0][3:], entries=entries, sitemap=sitemap),
                 state={"version": lines[0][3:]})


def check_links(node_input: Release):
    """Function node: every page an entry points to must be in the built site's sitemap.
    It raises if the site has not been built, because then nothing can be checked."""
    sitemap = HERE / node_input.sitemap
    if not sitemap.is_file():
        raise FileNotFoundError(f"{node_input.sitemap} not found: build the site first")
    built = set(sitemap.read_text().split())
    wanted = [page for entry in node_input.entries for page in PAGE.findall(entry)]
    return LinkReport(missing=[page for page in wanted if page not in built])


def assemble(node_input: dict, version: str):
    """Function node after the join: node_input maps each branch name to its output."""
    lines = [f"# docuctl {version} release notes", ""]
    lines += [f"- {b}" for b in node_input["write_highlights"]["bullets"]]
    lines += ["", "## Upgrade", *(f"1. {s}" for s in node_input["write_upgrade_steps"]["steps"])]
    links = node_input.get("check_links")
    if links is None:
        lines += ["", "Link check: not run (see the error above)."]
    elif links["missing"]:
        lines += ["", "Link check: missing " + ", ".join(links["missing"])]
    else:
        lines += ["", "Link check: every linked page exists."]
    return Event(message="\n".join(lines))


def make_agents(model):
    model = model or "gemini-3.8-flash"  # or LiteLlm(model="ollama_chat/gemma4:e2b")
    retry = RetryConfig(max_attempts=3, initial_delay=1.0)
    highlights = Agent(name="write_highlights", model=model,
                       generate_content_config=types.GenerateContentConfig(
                           max_output_tokens=1024,
                           thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)), input_schema=Release,
                       output_schema=Highlights,
                       instruction="Write one short user-facing bullet per entry. No marketing.")
    upgrade = Agent(name="write_upgrade_steps", model=model,
                       generate_content_config=types.GenerateContentConfig(
                           max_output_tokens=1024,
                           thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)), input_schema=Release,
                    output_schema=UpgradeSteps,
                    instruction=("Write the steps a user must take to upgrade, one per entry "
                                 "marked BREAKING. Return an empty list if there are none."))
    return node(highlights, retry_config=retry), node(upgrade, retry_config=retry)


def build_graph(model=None, max_concurrency=None) -> Workflow:
    """Graph fan-out: three rows from load_release, gathered by a JoinNode. Fail-all."""
    highlights, upgrade = make_agents(model)
    gather = JoinNode(name="gather")
    return Workflow(
        name="release_prep",
        max_concurrency=max_concurrency,
        edges=[
            ("START", load_release),
            (load_release, highlights, gather),
            (load_release, upgrade, gather),
            (load_release, check_links, gather),
            (gather, assemble),
        ],
    )


def build_partial(model=None) -> Workflow:
    """Dynamic fan-out: the same branches, but the link check may fail without
    failing the release. Required branches still stop the run."""
    highlights, upgrade = make_agents(model)

    @node(rerun_on_resume=True)
    async def prepare(ctx, node_input: Release):
        branches = {"write_highlights": highlights, "write_upgrade_steps": upgrade,
                    "check_links": check_links}
        results = await asyncio.gather(
            *(ctx.run_node(branch, node_input) for branch in branches.values()),
            return_exceptions=True)
        outputs = dict(zip(branches, results))
        error = outputs["check_links"]  # DynamicNodeFailError wraps the child's exception
        for name in ("write_highlights", "write_upgrade_steps"):
            if isinstance(outputs[name], BaseException):
                raise outputs[name]  # a required branch: no release page without it
        if isinstance(error, BaseException):
            outputs["check_links"] = None
            cause = getattr(error, "error", error)
            yield Event(message=f"{error.error_node_path} failed: {type(cause).__name__}: {cause}")
        yield Event(output={k: v.model_dump() if hasattr(v, "model_dump") else v
                            for k, v in outputs.items()})

    return Workflow(name="release_prep_partial",
                    edges=[("START", load_release, prepare, assemble)])
