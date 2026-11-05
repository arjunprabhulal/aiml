"""Run the review-fix task on Gemini with two executor step limits; save plans, tool calls, reports and checks."""
import json
import tempfile
from pathlib import Path

from graph import MODEL, STEP_LIMIT, build_graph, run_task


def run(task: dict, step_limit: int) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        state = run_task(build_graph(step_limit=step_limit), task, Path(folder))
        files = {p.relative_to(folder).as_posix(): p.read_text() for p in sorted(Path(folder).rglob("*"))
                 if p.is_file() and "__pycache__" not in p.parts}
    return {"step_limit": step_limit, "attempts": state["attempt"], "plan": state["plan"], "log": state["log"],
            "results": state["results"], "verdict": state["verdict"], "files": files}


def main() -> None:
    task = json.loads(Path("task.json").read_text())
    runs = [run(task, 8), run(task, STEP_LIMIT)]
    Path("runs.json").write_text(json.dumps({"model": MODEL, "runs": runs}, indent=1) + "\n")
    for r in runs:
        print(f"== step_limit={r['step_limit']}  attempts: {r['attempts']}  last plan:")
        for i, step in enumerate(r["plan"], 1):
            print(f"  {i}. {step['path']}: {step['change'][:90]}")
        for e in r["log"]:
            what = f"report: {e['report']}" if "report" in e else f"{e['tool']:<10} {e['path']} -> {e['result'].splitlines()[0][:44]}"
            print(f"  attempt {e['attempt']} step {e['step']}  {what[:110]}")
        for c in r["results"]:
            kind = "pytest" if c.get("pytest") else "unchanged" if c.get("unchanged") else json.dumps(c["contains"])
            print(f"  {'PASS' if c['passed'] else 'FAIL'}  {c['path']}  {kind}  {c.get('detail', '')}".rstrip())
        print("  verdict:", r["verdict"])


if __name__ == "__main__":
    main()
