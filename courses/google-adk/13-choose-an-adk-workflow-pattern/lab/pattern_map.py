"""Print the structure of every workflow pattern this course builds, without calling a model.

The bundled lesson modules construct the actual course structures without model calls.
"""
import importlib.util
import json
from pathlib import Path

from google.adk import Agent, Workflow
from google.adk.tools import AgentTool

EXAMPLES = Path(__file__).resolve().parent / "patterns"

# Pattern name on adk.dev/workflows/patterns -> (lesson folder, module, builder, workflow type)
PATTERNS = {
    "Sequential pipeline": ("adk-graph-workflow", "release_notes", "build_workflow", "graph"),
    "Coordinator and dispatcher": ("adk-graph-routes", "build_router", "build_workflow", "graph"),
    "Human-in-the-loop": ("adk-human-approval", "migration_gate", "build_workflow", "graph"),
    "Generate and review": ("adk-generate-review", "review_gate", "build_workflow", "graph"),
    "Iterative refinement": ("adk-iterative-refinement", "refine_entry", "build_workflow", "graph"),
    "Parallel fan-out and gather": ("adk-parallel-gather", "release_prep", "build_graph", "graph"),
    "Parallel fan-out, partial results": ("adk-parallel-gather", "release_prep", "build_partial",
                                          "dynamic"),
    "Coordinator with sub-agents": ("adk-sub-agents", "review_team", "build_team", "collaborative"),
    "Hierarchical task decomposition": ("adk-task-decomposition", "upgrade_guide", "build_tree",
                                        "collaborative"),
}


def load(folder: str, module: str):
    """Import a lesson's module under a unique name; every lesson folder is self-contained."""
    spec = importlib.util.spec_from_file_location(f"{folder}.{module}",
                                                  EXAMPLES / folder / f"{module}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def edges(workflow: Workflow) -> list[str]:
    """The graph ADK validated at construction: one line per edge, with its route."""
    lines = []
    for edge in workflow.graph.edges:
        route = f" [{edge.route}]" if edge.route is not None else ""
        lines.append(f"{edge.from_node.name} -> {edge.to_node.name}{route}")
    return lines


def tree(agent: Agent, depth: int = 1, via: str = "") -> list[str]:
    """An agent hierarchy: sub-agents with their mode, and agents wrapped in AgentTool.
    ADK 2.12 also gives a coordinator one AgentTool subclass per single_turn sub-agent;
    those are the sub-agents, so they are listed once."""
    lines = [f"{'  ' * (depth - 1)}{agent.name} (depth {depth}{via})"]
    for sub in agent.sub_agents:
        lines += tree(sub, depth + 1, f", sub-agent, mode={sub.mode}")
    subs = {sub.name for sub in agent.sub_agents}
    for tool in agent.tools:
        if isinstance(tool, AgentTool) and tool.agent.name not in subs:
            lines += tree(tool.agent, depth + 1, ", AgentTool")
    return lines


def describe(name: str) -> dict:
    folder, module, builder, kind = PATTERNS[name]
    built = getattr(load(folder, module), builder)("gemini-3.8-flash")
    shape = edges(built) if isinstance(built, Workflow) else tree(built)
    return {"pattern": name, "type": kind, "lesson_code": f"{folder}/{module}.py", "shape": shape}


if __name__ == "__main__":
    described = [describe(name) for name in PATTERNS]
    for entry in described:
        print(f"{entry['pattern']} ({entry['type']}, {entry['lesson_code']})")
        print("\n".join(f"  {line}" for line in entry["shape"]) + "\n")
    Path(__file__).with_name("pattern-map.json").write_text(json.dumps(described, indent=2) + "\n")
