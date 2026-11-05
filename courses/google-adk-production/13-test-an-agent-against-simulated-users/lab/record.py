"""Run the scenario eval set through `adk eval` under four configurations and keep the results.

Run from this folder with GOOGLE_API_KEY set, in a venv with google-adk[eval]: python record.py
Writes run-output.txt and results/<run>.json (the EvalSetResult, compacted).
ADK_DISABLE_LOAD_DOTENV=1 stops `adk` from loading a .env found in a parent folder.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADK = str(Path(sys.executable).with_name("adk"))
RUNS = {
    "simulated-users": ["--config_file_path", "eval_config.json"],
    "default-criteria": [],
    "one-turn-limit": ["--config_file_path", "config-one-turn.json"],
    "task-success-metric": ["--config_file_path", "config-task-success.json"],
}


def compact(value):
    """Drop nulls and opaque thought signatures so the saved result stays readable."""
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if v is not None and k != "thought_signature"}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def clean(line: str) -> str:
    """Drop progress-bar prefixes and cut long API error bodies."""
    line = re.sub(r"^.*?(\d{4}-\d\d-\d\d \d\d:)", r"\1", line)
    return line if len(line) <= 220 else line[:220] + " ..."


def main() -> None:
    env = {**os.environ, "ADK_DISABLE_LOAD_DOTENV": "1", "PYTHONWARNINGS": "ignore"}
    history = HERE / "docs_assistant" / ".adk" / "eval_history"
    (HERE / "results").mkdir(exist_ok=True)
    output = []
    for name, flags in RUNS.items():
        shutil.rmtree(history, ignore_errors=True)
        command = ["adk", "eval", "docs_assistant", "scenarios", *flags, "--print_detailed_results"]
        result = subprocess.run([ADK, *command[1:]], cwd=HERE, env=env, capture_output=True, text=True, timeout=900)
        errors = [clean(line) for line in result.stderr.splitlines() if re.search(r"(Error|Exception):|ERROR -", line)]
        text = result.stdout.strip() + ("\n" + "\n".join(dict.fromkeys(errors)) if errors else "")
        output.append(f"# Run {name}\n$ {' '.join(command)}\n{text}\n")
        saved = sorted(history.glob("*.json"))
        if saved:
            (HERE / "results" / f"{name}.json").write_text(json.dumps(compact(json.loads(saved[-1].read_text())), indent=1))
    shutil.rmtree(HERE / "docs_assistant" / ".adk", ignore_errors=True)
    (HERE / "run-output.txt").write_text("\n".join(output))


if __name__ == "__main__":
    main()
