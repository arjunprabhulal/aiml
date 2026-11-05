"""Run the evaluation cases through the traced pipeline and diagnose every failure from its trace.

    python3 trace_run.py record    # needs Ollama with the pinned gemma4:e2b; writes recorded/model-calls.json
    python3 trace_run.py           # offline: replays the recorded model calls and writes runs/
    python3 trace_run.py --check   # offline: reruns into a scratch folder and compares with runs/

Each run starts retrieval_service.py as a separate process, runs every case and
trial through the evaluation harness with the traced pipeline as the system,
then reads both processes' span files, rebuilds the traces and follows each
failed row to the step that lost its evidence. Standard library only.

Timing fields (the harness's RUN_DESCRIPTION_FIELDS and the tracer's
TIMING_FIELDS) change on every run; --check compares everything else exactly.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import harness
import pipeline
from diagnose import diagnose
from tracing import JsonLinesExporter, collect, read_spans, without_timing

HERE = Path(__file__).resolve().parent
TASK, CASES, SPLITS = "grounded_task", HERE / "cases.json", ("development", "held_out")
RECORDING = HERE / "recorded" / "model-calls.json"
# Two versions of the pipeline. "before" is what was deployed: an index built before
# the refund policy changed, and two passages of context. "after" rebuilds the
# index and keeps three passages.
CONFIGS = (
    {"name": "before", "version": "1", "index": "index_snapshot", "context_limit": 2},
    {"name": "after", "version": "2", "index": "current", "context_limit": 3},
)


class RetrievalProcess:
    """retrieval_service.py in its own process, on a port the operating system chooses."""

    def __init__(self, spans_path, index):
        command = [sys.executable, str(HERE / "retrieval_service.py"), "--corpus", str(HERE / "corpus.json"),
                   "--spans", str(spans_path), "--index", index, "--derived-ids"]
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, cwd=HERE)
        self.url = f"http://127.0.0.1:{int(self.process.stdout.readline())}"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.process.terminate()
        self.process.wait()
        self.process.stdout.close()


def execute(out_dir, model, config, clock=None):
    """Run every case and trial; write run.json, both span files, traces.json and diagnosis.json."""
    out_dir = Path(out_dir) / config["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    gateway_spans, retrieval_spans = out_dir / "spans-gateway.jsonl", out_dir / "spans-retrieval.jsonl"
    for path in (gateway_spans, retrieval_spans):
        path.write_text("", encoding="utf-8")
    task = harness.load_task(TASK)
    case_set = harness.load_cases(CASES, task)
    with RetrievalProcess(retrieval_spans, config["index"]) as service:
        flow = pipeline.Pipeline(pipeline.RetrievalClient(service.url), model, JsonLinesExporter(gateway_spans),
                                 config["context_limit"], clock=clock)
        system = pipeline.TracedSystem(flow, config["version"], replayed=isinstance(model, pipeline.ReplayModel))
        record = harness.run(system, case_set, task, SPLITS, trials=len(pipeline.MODEL["seeds"]),
                             include_held_out=True)
    traces = collect(read_spans(gateway_spans, retrieval_spans))
    result = {
        "run": record,
        "traces": {trace_id: traces[trace_id] for trace_id in sorted(traces)},
        "diagnosis": diagnose(record, case_set["cases"], traces, pipeline.CORPUS["current"]),
    }
    for name, value in result.items():
        harness.write(out_dir / f"{name}.json", value)
    return result


def execute_all(out_dir, model, clock=None):
    results = {config["name"]: execute(out_dir, model, config, clock) for config in CONFIGS}
    comparison = harness.compare(results["before"]["run"], results["after"]["run"])
    harness.write(Path(out_dir) / "comparison.json", comparison)
    return results, comparison


def comparable(out_dir):
    """The saved outputs without the fields that describe one run's timing and machine."""
    out_dir = Path(out_dir)
    files = {"comparison": json.loads((out_dir / "comparison.json").read_text(encoding="utf-8"))}
    for config in CONFIGS:
        folder = out_dir / config["name"]
        for name in ("run", "traces", "diagnosis"):
            files[f"{config['name']}/{name}"] = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("spans-gateway", "spans-retrieval"):
            lines = (folder / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            files[f"{config['name']}/{name}"] = sorted((json.loads(line) for line in lines), key=lambda s: s["span_id"])
    return without_timing(harness.without_run_description(files))


def report(results, comparison):
    for name, result in results.items():
        for split, data in result["run"]["summary"].items():
            print(f"{name} {split}: {data['pass']} pass, {data['fail']} fail, {data['incomplete']} incomplete "
                  f"of {data['trials']} trials")
        for row in result["diagnosis"]:
            print(f"  {row['case_id']} trial {row['trial']}: {row['verdict']} at {row['step']}: {row['detail']}")
    for split, data in comparison["summary"].items():
        print(f"before -> after, {split}: fixed {data['fixed']}, regressed {data['regressed']}, changed {data['changed']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", choices=["record"])
    parser.add_argument("--check", action="store_true", help="rerun offline and compare with runs/")
    options = parser.parse_args(argv)
    if options.check:
        with tempfile.TemporaryDirectory() as scratch:
            execute_all(scratch, pipeline.ReplayModel(RECORDING))
            if comparable(scratch) != comparable(HERE / "runs"):
                sys.exit("runs/ differs from a fresh replay")
        print("runs/ matches a fresh replay, apart from timing fields")
        return
    if options.command == "record":
        model = pipeline.OllamaModel()
        execute_all(HERE / "runs", model)
        harness.write(RECORDING, {"model": pipeline.MODEL, "calls": dict(sorted(model.recorded.items()))})
        print(f"recorded {len(model.recorded)} model calls; now run python3 trace_run.py to replay them")
        return
    report(*execute_all(HERE / "runs", pipeline.ReplayModel(RECORDING)))


if __name__ == "__main__":
    main()
