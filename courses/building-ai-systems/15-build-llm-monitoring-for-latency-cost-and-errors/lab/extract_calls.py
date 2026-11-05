"""Copy the per-call token counts and model timings out of the tracing build's recording.

    python3 extract_calls.py

Reads ../build-end-to-end-request-tracing-with-evidence-provenance/recorded/model-calls.json,
which holds 48 calls to gemma4:e2b recorded through Ollama, and writes calls.json with
only the fields the monitoring simulation uses. load_duration is left out: it is the
time Ollama spent loading the model, which a warm server does not pay on every call.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "build-end-to-end-request-tracing-with-evidence-provenance" / "recorded" / "model-calls.json"


def extract(source=SOURCE):
    recording = json.loads(Path(source).read_text(encoding="utf-8"))
    calls = [{"request_sha256": key,
              "input_tokens": call["prompt_eval_count"], "output_tokens": call["eval_count"],
              "model_ms": round((call["prompt_eval_duration"] + call["eval_duration"]) / 1e6, 3)}
             for key, call in sorted(recording["calls"].items())]
    return {"source": "build-end-to-end-request-tracing-with-evidence-provenance/recorded/model-calls.json",
            "model": recording["model"]["ollama_tag"], "ollama_version": recording["model"]["ollama_version"],
            "calls": calls}


if __name__ == "__main__":
    (HERE / "calls.json").write_text(json.dumps(extract(), indent=2) + "\n", encoding="utf-8")
    print("wrote calls.json")
