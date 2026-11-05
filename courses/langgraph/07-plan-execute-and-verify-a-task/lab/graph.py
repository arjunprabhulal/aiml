"""A plan, execute and verify graph in LangGraph. The verifier reads the files on disk, not the agent's report."""
import json
import operator
import os
from pathlib import Path
from typing import Annotated, Literal

from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from workspace import make_tools, run_checks

MODEL = os.environ.get("REVIEW_MODEL", "gemini-3.8-flash")  # REVIEW_MODEL=gemma4:e2b runs it on Ollama
MAX_ATTEMPTS = 2  # plans per task
STEP_LIMIT = 16   # graph steps the executor agent may take on one plan step
EXECUTE = """You carry out one step of a plan in a project folder. Read a file before you change it,
then write its complete new content. Reply with one sentence saying what you changed."""


class Step(BaseModel):
    path: str = Field(description="The one file this step changes, relative to the project folder.")
    change: str = Field(description="Exactly what to write or change in that file.")


class Plan(BaseModel):
    steps: list[Step] = Field(description="One step per file, in order.")


class State(TypedDict, total=False):
    request: str
    workspace: str
    files: dict[str, str]  # the starting files, so a check can tell what changed
    checks: list[dict]
    plan: list[dict]
    step: int
    attempt: int
    log: Annotated[list[dict], operator.add]  # every tool call and every executor report
    results: list[dict]


def chat_model():
    if MODEL.startswith("gemini"):
        return ChatGoogleGenerativeAI(model=MODEL)  # reads GOOGLE_API_KEY from the environment
    return ChatOllama(model=MODEL, temperature=0, reasoning=False)


def build_graph(model=None, step_limit: int = STEP_LIMIT, planner=None):
    model = model or chat_model()
    planner = planner or model.with_structured_output(Plan)

    def plan(state: State) -> dict:
        prompt = f"Plan this task as file edits:\n{state['request']}"
        failed = [r for r in state.get("results", []) if not r["passed"]]
        if failed:
            prompt += f"\nThe last attempt failed these checks on the files; fix them: {json.dumps(failed)}"
        steps = [s.model_dump() for s in planner.invoke(prompt).steps]
        return {"plan": steps, "step": 0, "attempt": state.get("attempt", 0) + 1}

    def execute(state: State) -> dict:
        agent = create_agent(model, make_tools(Path(state["workspace"])), system_prompt=EXECUTE)
        step = state["plan"][state["step"]]
        ask = f"Task: {state['request']}\nDo only this step. File: {step['path']}\nChange: {step['change']}"
        messages, report = [], None
        try:
            for values in agent.stream({"messages": [("user", ask)]}, {"recursion_limit": step_limit}, stream_mode="values"):
                messages = values["messages"]
            report = messages[-1].text
        except GraphRecursionError:  # the step did not finish; the verifier still checks the files
            report = f"(no report: stopped at the step limit of {step_limit})"
        where = {"attempt": state["attempt"], "step": state["step"] + 1}
        calls = {c["id"]: c for m in messages for c in getattr(m, "tool_calls", [])}
        log = [{**where, "tool": m.name, "path": calls[m.tool_call_id]["args"].get("path"), "result": m.text}
               for m in messages if isinstance(m, ToolMessage)]
        return {"step": state["step"] + 1, "log": [*log, {**where, "report": report}]}

    def verify(state: State) -> dict:
        return {"results": run_checks(Path(state["workspace"]), state["checks"], state["files"])}

    def next_step(state: State) -> Literal["execute", "verify"]:
        return "execute" if state["step"] < len(state["plan"]) else "verify"

    def after_verify(state: State) -> Literal["plan", "__end__"]:
        passed = all(r["passed"] for r in state["results"])
        return END if passed or state["attempt"] >= MAX_ATTEMPTS else "plan"

    graph = StateGraph(State)
    graph.add_node("plan", plan)
    graph.add_node("execute", execute)
    graph.add_node("verify", verify)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", next_step)  # an empty plan goes straight to verify
    graph.add_conditional_edges("execute", next_step)
    graph.add_conditional_edges("verify", after_verify)
    return graph.compile()


def run_task(graph, task: dict, folder: Path) -> dict:
    for name, text in task["files"].items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    state = graph.invoke({"request": task["request"], "workspace": str(folder), "files": task["files"],
                          "checks": task["checks"]},
                         {"recursion_limit": 40})
    return {**state, "verdict": "pass" if all(r["passed"] for r in state["results"]) else "fail"}
