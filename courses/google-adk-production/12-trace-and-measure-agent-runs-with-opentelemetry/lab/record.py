"""Record traced runs of the docs assistant under three telemetry configurations.

Run from this folder with GOOGLE_API_KEY set: python record.py
Each run is a fresh process, because OpenTelemetry providers can be set only once per process.
Writes runs/<name>/traces.jsonl and metrics.jsonl, recorded-runs.json and run-output.txt.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUESTION = "How do I rebuild the search index?"
RUNS = {
    "defaults": {},
    "production": {"OTEL_SERVICE_NAME": "docs-assistant", "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false"},
    "otlp-without-exporter": {"OTEL_SERVICE_NAME": "docs-assistant", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"},
}


def checks(out: Path) -> dict:
    """What a trace backend would receive: span names, the service name and any message content."""
    spans = [json.loads(line) for line in (out / "traces.jsonl").read_text().splitlines()]
    content = sorted({f"{s['name']}: {k}" for s in spans for k, v in s["attributes"].items()
                      if "search index" in str(v) or "docs-assistant index --rebuild" in str(v)})
    return {"spans": len(spans), "span_names": sorted({s["name"] for s in spans}),
            "service_name": spans[0]["resource"]["attributes"].get("service.name"),
            "content_attributes": content}


def main() -> None:
    record, output = {"question": QUESTION, "runs": {}}, []
    for name, extra in RUNS.items():
        out = HERE / "runs" / name
        env = {**os.environ, "PYTHONWARNINGS": "ignore", **extra}
        result = subprocess.run([sys.executable, "traced.py", QUESTION, str(out)], cwd=HERE, env=env,
                                capture_output=True, text=True, timeout=300)
        settings = " ".join(f"{k}={v}" for k, v in extra.items()) or "(no OTEL_* variables)"
        text = result.stdout + (result.stderr.strip().splitlines()[-1] + "\n" if result.returncode else "")
        output.append(f"# Run {name}: {settings}\n$ python traced.py {QUESTION!r}\n{text}")
        entry = {"env": extra, "exit_code": result.returncode}
        if result.returncode == 0:
            entry.update(checks(out))
        else:
            entry["error"] = result.stderr.strip().splitlines()[-1]
            shutil.rmtree(out)  # the exporter files it opened stay empty
        record["runs"][name] = entry
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=2) + "\n")
    (HERE / "run-output.txt").write_text("\n".join(output))
    print("\n".join(output))


if __name__ == "__main__":
    main()
