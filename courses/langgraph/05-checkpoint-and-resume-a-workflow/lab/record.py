"""Crash and resume the workflow in real processes on Gemini, and save what each process ran."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from workflow import MODEL, build_graph

HERE = Path(__file__).parent
SCENARIOS = {
    "crash between steps, then resume": [
        ("after summarize", ["--thread", "r1", "--version", "2.5.0"]), (None, ["--thread", "r1"])],
    "crash inside a step with a side effect": [
        ("announce", ["--thread", "r2", "--version", "2.5.1"]), (None, ["--thread", "r2"])],
    "resume under a new thread id": [
        ("after summarize", ["--thread", "r3", "--version", "2.5.2"]), (None, ["--thread", "r3-retry", "--version", "2.5.2"])],
    "durability exit, then a crash": [
        ("after summarize", ["--thread", "r4", "--version", "2.5.3", "--durability", "exit"]),
        (None, ["--thread", "r4", "--version", "2.5.3", "--durability", "exit"])],
}


def main(reset_example_data: bool = False) -> None:
    if not reset_example_data:
        raise SystemExit("The diagnostic recorder deletes out/ and checkpoints.db. "
                         "Use a disposable copy and pass --reset-example-data, or run workflow.py "
                         "with --work-dir to keep a learner run.")
    shutil.rmtree(HERE / "out", ignore_errors=True)
    (HERE / "checkpoints.db").unlink(missing_ok=True)
    record = {"model": MODEL, "scenarios": []}
    for name, processes in SCENARIOS.items():
        print(f"== {name}")
        runs = []
        for crash, args in processes:
            env = {k: v for k, v in os.environ.items() if k != "CRASH_AT"} | ({"CRASH_AT": crash} if crash else {})
            done = subprocess.run([sys.executable, "workflow.py", *args], cwd=HERE, env=env, capture_output=True, text=True)
            shown = (f"CRASH_AT='{crash}' " if crash else "") + " ".join(["python", "workflow.py", *args])
            print(f"$ {shown}\n{done.stdout.rstrip()}\n(exit {done.returncode})")
            runs.append({"command": shown, "exit": done.returncode, "output": done.stdout.splitlines()})
        record["scenarios"].append({"name": name, "processes": runs})
    record["announcements"] = (HERE / "out/announcements.log").read_text().splitlines()
    record["notes_2_5_0"] = (HERE / "out/2.5.0.md").read_text()
    with SqliteSaver.from_conn_string(str(HERE / "checkpoints.db")) as saver:  # thread r1, oldest first
        history = list(build_graph(saver).get_state_history({"configurable": {"thread_id": "r1"}}))[::-1]
    record["r1_checkpoints"] = [{"step": c.metadata["step"], "source": c.metadata["source"], "next": list(c.next),
                                 "keys": sorted(c.values)} for c in history]
    print("== out/announcements.log", *record["announcements"], sep="\n")
    print("== checkpoints saved for thread r1")
    for c in record["r1_checkpoints"]:
        print(f"  step {c['step']:>2} {c['source']:<5} next={c['next']} state keys={c['keys']}")
    (HERE / "runs.json").write_text(json.dumps(record, indent=1) + "\n")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-example-data", action="store_true",
                        help="Delete this example's out/ and checkpoints.db before recording all crash scenarios.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main(reset_example_data=parse_args().reset_example_data)
