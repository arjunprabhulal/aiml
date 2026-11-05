"""Write an upgrade guide with a three-level agent tree: plan, write sections, research docs."""
import re
from pathlib import Path

from google.adk import Agent, Event, Workflow
from google.genai import types
from google.adk.plugins import BasePlugin
from google.adk.tools import AgentTool

DOCS = Path(__file__).with_name("docs")
SOURCE = re.compile(r"^Source: (\S+\.md)$", re.M)


def search_docs(query: str) -> list[dict]:
    """Find docs pages that contain every word of the query. Returns path and title."""
    words = query.lower().split()
    hits = []
    for page in sorted(DOCS.rglob("*.md")):
        text = page.read_text()
        if all(word in text.lower() for word in words):
            hits.append({"path": str(page.relative_to(DOCS)), "title": text.splitlines()[0][2:]})
    return hits


def read_page(path: str) -> dict:
    """Return the text of one docs page, by the path that search_docs returned."""
    page = (DOCS / path).resolve()
    if not page.is_relative_to(DOCS.resolve()) or not page.is_file():
        return {"error": f"no docs page at {path}"}
    return {"path": path, "text": page.read_text()}


# One entry per level, top first. The depth limit cuts the tree: the last level
# that is built gets the docs tools instead of a delegation tool.
LEVELS = [
    ("plan_guide",
     "You write upgrade guides for docuctl, a docs-site CLI. Split the goal into one "
     "section per breaking change, and ask write_section to write each one. Then return "
     "the sections in version order under one '# ' title. Do not write sections yourself."),
    ("write_section",
     "Write one section of an upgrade guide: a '## ' heading, the steps a user takes, and a "
     "last line 'Source: <path>' naming the docs page the steps come from. Get every fact "
     "from research_docs; never use your own knowledge of docuctl."),
    ("research_docs",
     "Answer the question from the docuctl docs only. Use search_docs with one or two "
     "words, then read_page. Quote exact commands and the page path."),
]
MAX_DEPTH = len(LEVELS)


def build_tree(model, max_depth: int = MAX_DEPTH, level: int = 0) -> Agent:
    name, instruction = LEVELS[level]
    if level + 1 < min(max_depth, len(LEVELS)):
        tools = [AgentTool(build_tree(model, max_depth, level + 1))]
    else:
        tools = [search_docs, read_page]  # a leaf: it can only read, not delegate
        if name == "write_section":
            instruction = instruction.replace(
                "Get every fact from research_docs;",
                "Use search_docs with one or two words, then read_page. "
                "Get every fact from those pages;")
    return Agent(name=name, model=model,
                       generate_content_config=types.GenerateContentConfig(
                           max_output_tokens=1024,
                           thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)), instruction=instruction, tools=tools,
                 description=instruction.split(".")[0])


def check_sources(node_input: str):
    """Function node: every section must cite a docs page that exists."""
    sections = re.split(r"(?m)^## [^\n]+\n", node_input)[1:]
    if not sections:
        raise ValueError("guide needs at least one section")
    cited = []
    for section in sections:
        lines = section.strip().splitlines()
        sources = SOURCE.findall(section)
        if len(sources) != 1 or not SOURCE.fullmatch(lines[-1]):
            raise ValueError("each section must end with one Source: <path> line")
        cited.append(sources[0])
    root = DOCS.resolve()
    missing = [path for path in cited
               if not (page := (root / path).resolve()).is_relative_to(root)
               or not page.is_file()]
    if missing:
        raise ValueError(f"missing pages: {missing}")
    return Event(message=node_input)


class DelegationLog(BasePlugin):
    """Records every agent start and tool call in the tree, with the agent's depth.
    AgentTool passes the runner's plugins to the nested runs (include_plugins=True)."""

    def __init__(self, max_model_calls: int | None = None):
        super().__init__(name="delegation_log")
        self.rows: list[dict] = []
        self.model_calls = 0
        self.max_model_calls = max_model_calls

    async def before_agent_callback(self, *, agent, callback_context):
        depth = [name for name, _ in LEVELS].index(agent.name) + 1
        self.rows.append({"depth": depth, "agent": agent.name})

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        self.rows.append({"agent": tool_context.agent_name, "calls": tool.name, "args": tool_args})

    async def before_model_callback(self, *, callback_context, llm_request):
        # One budget for the whole tree: each nested run counts its own max_llm_calls.
        self.model_calls += 1
        if self.max_model_calls is not None and self.model_calls > self.max_model_calls:
            raise RuntimeError(f"tree-wide model call budget of {self.max_model_calls} exceeded")


def build_workflow(model=None, max_depth: int = MAX_DEPTH) -> Workflow:
    model = model or "gemini-3.8-flash"  # or LiteLlm(model="ollama_chat/gemma4:e2b")
    return Workflow(name="upgrade_guide",
                    edges=[("START", build_tree(model, max_depth), check_sources)])
