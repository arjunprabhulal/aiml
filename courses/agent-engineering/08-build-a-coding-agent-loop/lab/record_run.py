"""Record one local attempt without changing the starting sample repository."""
import argparse
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import tempfile
from urllib.request import urlopen
import time

from harness.loop import agent_events
from harness.ollama_model import LocalModel
from harness.tools import RepoTools

HERE = Path(__file__).resolve().parent
TASK = ("Fix python_sources so changed paths using Windows backslashes are selected "
        "the same way as forward-slash paths and returned with forward slashes. "
        "Keep filtering to Python files under src. Inspect and run the existing tests first.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma4:e2b")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--output", default="recorded-run.json")
    args = parser.parse_args()
    model = LocalModel(args.model)
    metadata = model.client.show(args.model).model_dump(exclude_none=True)
    tags = model.client.list().model_dump(exclude_none=True)["models"]
    tag = next(item for item in tags if item["model"] == args.model)
    turns = []

    def record_chat(messages, tools):
        row = {"messages": copy.deepcopy(messages), "chunks": []}
        turns.append(row)
        for chunk in model(messages, tools):
            row["chunks"].append(chunk)
            yield chunk

    with tempfile.TemporaryDirectory(prefix="harness-sample-") as temp:
        work = Path(temp) / "repo"
        shutil.copytree(HERE / "sample_repo", work)
        tools = RepoTools(work)
        before = tools.run_tests()
        original_tests = (work / "tests/test_path_rules.py").read_bytes()
        start = time.monotonic()
        events = list(agent_events(record_chat, tools, TASK, args.max_turns))
        elapsed = time.monotonic() - start
        after = tools.run_tests()
        assert (work / "tests/test_path_rules.py").read_bytes() == original_tests
        record = {"task": TASK, "model": args.model, "model_digest": tag["digest"],
                  "model_capabilities": metadata.get("capabilities"),
                  "think": True, "options": {"temperature": 0, "seed": 7, "num_ctx": 8192, "num_predict": 2048},
                  "max_turns": args.max_turns, "elapsed_seconds": elapsed,
                  "environment": {"python": platform.python_version(), "platform": platform.platform(),
                                  "ollama_sdk": importlib.metadata.version("ollama"),
                                  "pytest": importlib.metadata.version("pytest"),
                                  "ollama_server": json.load(urlopen("http://127.0.0.1:11434/api/version", timeout=10))},
                  "before": before, "after": after, "events": events, "turns": turns,
                  "tests_sha256": hashlib.sha256(original_tests).hexdigest(),
                  "result_source": (work / "path_rules.py").read_text()}
    output = HERE / args.output
    output.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str) + "\n")
    print(json.dumps({"record": output.name, "before_exit": before["exit_code"],
                      "after_exit": after["exit_code"], "turns": len(turns),
                      "stop": events[-1], "elapsed_seconds": elapsed}, indent=2))


if __name__ == "__main__":
    main()
