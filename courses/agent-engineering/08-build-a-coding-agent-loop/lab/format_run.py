"""Produce short reader output from the real saved local runs."""
import copy
import json
from pathlib import Path
import re
import shutil
import tempfile

from harness.loop import agent_events
from harness.tools import RepoTools

HERE = Path(__file__).resolve().parent


def tests(result):
    return " · ".join(re.findall(r"\d+ (?:failed|passed|error)", result["output"].splitlines()[-1]))


def main():
    run = json.loads((HERE / "recorded-run.json").read_text())
    bounded = json.loads((HERE / "recorded-max-turns.json").read_text())
    lines = [f"Local model: {run['model']}", f"Starting tests: {tests(run['before'])}"]
    for event in run["events"]:
        if event["type"] == "tool_start":
            lines.append(f"turn {event['turn']}: {event['name']} {json.dumps(event['arguments'], ensure_ascii=False)}")
        if event["type"] == "tool_result" and event["name"] == "run_tests":
            lines.append(f"tool result: exit_code={event['result']['exit_code']}, {tests(event['result'])}")
    lines += [f"Stop: {run['events'][-1]['reason']} after {len(run['turns'])} model calls",
              f"Independent final tests: {tests(run['after'])}",
              f"Recorded bounded run: {bounded['events'][-1]['reason']}; final test exit={bounded['after']['exit_code']}"]
    (HERE / "run-output.txt").write_text("\n".join(lines) + "\n")
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp) / "repo"
        shutil.copytree(HERE / "sample_repo", work)
        chunks = copy.deepcopy(run["turns"][0]["chunks"])
        for chunk in chunks:
            chunk["done"] = False
            chunk.pop("done_reason", None)
        events = list(agent_events(lambda messages, tools: iter(chunks), RepoTools(work), run["task"]))
        failure = {"method": "offline fault injection: remove done from saved first model stream",
                   "stop": events[-1], "tool_executions": sum(e["type"] == "tool_start" for e in events)}
        assert failure["stop"]["reason"] == "incomplete_model_turn" and failure["tool_executions"] == 0
        (HERE / "failure-output.json").write_text(json.dumps(failure, indent=2) + "\n")


if __name__ == "__main__":
    main()
