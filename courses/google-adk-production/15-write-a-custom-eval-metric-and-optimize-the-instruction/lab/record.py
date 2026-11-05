"""Score the docs assistant with the custom citation metric, optimize its instruction with GEPA,
and score the optimized instruction on the held-out validation set.

Run from this folder with GOOGLE_API_KEY set, in a venv with google-adk[eval]: python record.py
Writes run-output.txt, optimize-output.txt, optimized-instruction.txt and results/<run>.json.
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
HISTORY = HERE / "docs_assistant" / ".adk" / "eval_history"
ENV = {**os.environ, "ADK_DISABLE_LOAD_DOTENV": "1", "PYTHONWARNINGS": "ignore"}
WITH_PATH = {"PYTHONPATH": str(HERE)}  # so `adk` can import citation_metric
EVAL = ["eval", "docs_assistant"]
RUNS = {
    "partial-metric-info": (EVAL + ["train", "--config_file_path", "config-partial-metric-info.json"], {}),
    "metric-not-on-path": (EVAL + ["train", "--config_file_path", "eval_config.json"], {}),
    "baseline-train": (EVAL + ["train", "--config_file_path", "eval_config.json", "--print_detailed_results"], WITH_PATH),
    "baseline-validation": (EVAL + ["validation", "--config_file_path", "eval_config.json", "--print_detailed_results"], WITH_PATH),
}


def clean(line: str) -> str:
    line = re.sub(r"^.*?(\d{4}-\d\d-\d\d \d\d:)", r"\1", line)
    return line if len(line) <= 220 else line[:220] + " ..."


def compact(value):
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if v is not None and k != "thought_signature"}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def adk(name: str, args: list, extra: dict) -> str:
    shutil.rmtree(HISTORY, ignore_errors=True)
    result = subprocess.run([ADK, *args], cwd=HERE, env={**ENV, **extra}, capture_output=True, text=True, timeout=3600)
    errors = [clean(l) for l in result.stderr.splitlines() if re.search(r"(Error|Exception):|ERROR -", l)]
    saved = sorted(HISTORY.glob("*.json"))
    if saved:
        (HERE / "results" / f"{name}.json").write_text(json.dumps(compact(json.loads(saved[-1].read_text())), indent=1))
    env = "".join(f"{k}={Path(v).relative_to(HERE) or '.'} " for k, v in extra.items())
    return f"# Run {name}\n$ {env}adk {' '.join(args)}\n" + result.stdout.strip() + (
        "\n" + "\n".join(dict.fromkeys(errors)) if errors else "") + "\n"


PROBE = """
import asyncio, sys
from google.adk.runners import InMemoryRunner
from google.genai import types
from docs_assistant.agent import root_agent

async def main():
    runner = InMemoryRunner(agent=root_agent, app_name="docs_assistant")
    session = await runner.session_service.create_session(app_name="docs_assistant", user_id="dev")
    message = types.Content(role="user", parts=[types.Part(text=sys.argv[1])])
    async for event in runner.run_async(user_id="dev", session_id=session.id, new_message=message):
        for part in event.content.parts if event.content else []:
            if part.function_call:
                print("call  ", part.function_call.name, dict(part.function_call.args or {}))
            elif part.text and not part.thought and event.is_final_response():
                print("answer", part.text.strip())

asyncio.run(main())
"""


def changed_docs_probe() -> str:
    """Edit install.md, then ask the optimized agent what the page now says."""
    page = HERE / "docs_assistant" / "docs" / "install.md"
    original = page.read_text()
    page.write_text(original.replace("Python 3.12 or later.", "Python 3.13 or later."))
    try:
        question = "Which Python version do I need?"
        result = subprocess.run([sys.executable, "-c", PROBE, question], cwd=HERE, capture_output=True, text=True,
                                env={**ENV, "DOCS_INSTRUCTION_FILE": str(HERE / "optimized-instruction.txt")}, timeout=300)
    finally:
        page.write_text(original)
    return (f"# Run optimized-after-docs-change (install.md now says Python 3.13)\n> {question}\n"
            + result.stdout.strip() + "\n")


def main() -> None:
    (HERE / "results").mkdir(exist_ok=True)
    output = [adk(name, args, extra) for name, (args, extra) in RUNS.items()]

    optimize = adk("optimize", ["optimize", "docs_assistant", "--sampler_config_file_path", "sampler_config.json",
                                "--optimizer_config_file_path", "optimizer_config.json", "--print_detailed_results"], WITH_PATH)
    (HERE / "optimize-output.txt").write_text(optimize)
    found = re.search(r"Optimized root agent instructions:\n-+\n(.*?)\n=+", optimize, re.S)
    if found:
        (HERE / "optimized-instruction.txt").write_text(found.group(1).strip() + "\n")
        output.append(adk("optimized-validation", EVAL + ["validation", "--config_file_path", "eval_config.json",
                                                          "--print_detailed_results"],
                          {**WITH_PATH, "DOCS_INSTRUCTION_FILE": str(HERE / "optimized-instruction.txt")}))
        output.append(changed_docs_probe())
    shutil.rmtree(HERE / "docs_assistant" / ".adk", ignore_errors=True)
    (HERE / "run-output.txt").write_text("\n".join(output))


if __name__ == "__main__":
    main()
