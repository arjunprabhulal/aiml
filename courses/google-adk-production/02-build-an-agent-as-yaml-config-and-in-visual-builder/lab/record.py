"""Record the YAML docs assistant: adk run, load.py, three load failures and the Visual Builder endpoints.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes run-output.txt and recorded-runs.json. The builder calls run against a temporary copy of
this folder, because a save rewrites root_agent.yaml.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import httpx  # noqa: E402
from google.adk.agents.config_agent_utils import from_config  # noqa: E402

import load  # noqa: E402

HERE = Path(__file__).resolve().parent
ADK = str(Path(sys.executable).with_name("adk"))
QUESTION = "How do I roll back production?"
ENV = {**os.environ, "GOOGLE_GENAI_USE_ENTERPRISE": "0", "GOOGLE_GENAI_USE_VERTEXAI": "0", "PYTHONWARNINGS": "ignore"}
YAML = (HERE / "docs_config" / "root_agent.yaml").read_text(encoding="utf-8")
BROKEN = {
    "misspelled_field": YAML.replace("instruction:", "instructions:"),
    "missing_tool": YAML.replace("tools.read_page", "tools.read_pages"),
    "stdlib_tool": YAML.replace("docs_config.tools.read_page", "os.system"),
}
UPLOADS = {
    "edit": YAML.replace("under 100 words", "under 80 words"),
    "args_key": YAML.replace("  - name: docs_config.tools.read_page", "  - name: docs_config.tools.read_page\n    args:\n      page: tokens"),
    "outside_code": YAML.replace("docs_config.tools.read_page", "subprocess.run"),
}


def curl(*args: str) -> str:
    proc = subprocess.run(["curl", "-s", "-w", "\nHTTP %{http_code}", *args], capture_output=True, text=True, timeout=30)
    return proc.stdout


def main() -> None:
    rec, out = {"model": "gemini-3.8-flash", "question": QUESTION}, []
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["create", "--type=config", "--model", "gemini-3.8-flash", "--api_key", "your-gemini-api-key", "docs_config"]
        proc = subprocess.run([ADK, *cmd], cwd=tmp, env=ENV, capture_output=True, text=True, timeout=60)
        made = Path(tmp) / "docs_config"
        rec["adk_create"] = {"command": "adk " + " ".join(cmd), "files": sorted(p.name for p in made.iterdir()),
                             "root_agent.yaml": (made / "root_agent.yaml").read_text(encoding="utf-8")}
    out += [f"$ {rec['adk_create']['command']}", f"created docs_config/: {', '.join(rec['adk_create']['files'])}",
            rec["adk_create"]["root_agent.yaml"].rstrip(), ""]
    proc = subprocess.run([ADK, "run", "--in_memory", "docs_config", QUESTION], cwd=HERE, env=ENV, capture_output=True, text=True, timeout=300)
    rec["adk_run"] = [l for l in proc.stdout.splitlines() if l.strip() and not l.startswith(("Log setup", "To access latest log"))]
    out += [f"$ adk run --in_memory docs_config {QUESTION!r}", *rec["adk_run"], ""]

    agent = load.load()
    events = asyncio.run(load.ask(agent, QUESTION))
    rec["load"] = {"lines": [load.describe(e) for e in events], "answer": events[-1].content.parts[-1].text,
                   "model_turns": [{"content": {"role": "model", "parts": [
                       {k: v for k, v in p.model_dump(mode="json", exclude_none=True).items() if k != "thought_signature"}
                       for p in e.content.parts]}} for e in events if e.content and e.content.role == "model"]}
    cfg = agent.generate_content_config
    out += [f"$ python load.py {QUESTION!r}", f"LlmAgent {agent.name} model={agent.model} tools=['read_page']",
            f"temperature={cfg.temperature} thinking_level={cfg.thinking_config.thinking_level.value}",
            *rec["load"]["lines"], f"answer: {rec['load']['answer']}", ""]

    rec["load_failures"] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in BROKEN.items():
            path = Path(tmp) / f"{name}.yaml"
            path.write_text(text, encoding="utf-8")
            try:
                from_config(str(path))
                rec["load_failures"][name] = "loaded"
            except Exception as error:  # the three failures raise three different types
                rec["load_failures"][name] = f"{type(error).__name__}: {error}"
        out += [f"from_config {name}: {msg.splitlines()[0]}" for name, msg in rec["load_failures"].items()] + [""]

        work = Path(tmp) / "agents"
        shutil.copytree(HERE / "docs_config", work / "docs_config", ignore=shutil.ignore_patterns("__pycache__", ".env"))
        shutil.copytree(HERE / "docs", work / "docs")
        for name, text in UPLOADS.items():
            (Path(tmp) / f"{name}.yaml").write_text(text, encoding="utf-8")
        server = subprocess.Popen([ADK, "web", "--port", "8766", "."], cwd=work, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        try:
            for _ in range(60):
                try:
                    httpx.get("http://127.0.0.1:8766/list-apps")
                    break
                except httpx.ConnectError:
                    time.sleep(0.5)
            base = "http://127.0.0.1:8766/dev/apps/docs_config/builder"
            got = curl(base)
            rec["builder"] = {"get": got.splitlines()[-1], "get_matches_file": got.rsplit("\nHTTP", 1)[0] == YAML}
            for name in UPLOADS:
                rec["builder"][name] = curl("-X", "POST", f"{base}/save", "-F", f"files=@{tmp}/{name}.yaml;filename=docs_config/root_agent.yaml")
            rec["builder"]["saved_has_edit"] = "under 80 words" in (work / "docs_config" / "root_agent.yaml").read_text(encoding="utf-8")
        finally:
            server.terminate()
            server.wait(timeout=20)
    out += ["$ adk web --port 8766 .", "$ curl -s http://127.0.0.1:8766/dev/apps/docs_config/builder", rec["builder"]["get"]]
    for name in UPLOADS:
        out += [f"$ curl -s -X POST {'http://127.0.0.1:8766/dev/apps/docs_config/builder'}/save -F 'files=@{name}.yaml;filename=docs_config/root_agent.yaml'",
                rec["builder"][name]]
    (HERE / "run-output.txt").write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    (HERE / "recorded-runs.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
