"""Tests for the repeated-trial benchmark. Run: python3 -m unittest -v test_bench.py

No test calls a model. The recorded logs are replayed through the harness, and
the model system is exercised with a scripted stand-in for its chat() call.
"""
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bench
import harness
import model_triage
import outputs_digest
import report

HERE = Path(__file__).resolve().parent
TASK = harness.load_task("triage_task")
SYSTEMS = ("gemma", "qwen")


def stored(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


class Scripted:
    """A harness system whose answer depends on (case, trial); an exception is raised."""
    mode, model, prompt, tools = "live", None, None, None

    def __init__(self, answers, name="scripted"):
        self.answers, self.name, self.version, self.calls = answers, name, "test", []

    def respond(self, case, trial):
        self.calls.append((case["id"], trial))
        answer = self.answers(case, trial)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def right(case, trial):
    if "rejected" in case["expected"]:
        raise ValueError("message is blank" if case["input"] is not None else "message is not text")
    return {"category": case["expected"]["category"], "needs_human": case["class"] == "account security"}


class BenchTests(unittest.TestCase):
    def setUp(self):
        self.cases = harness.load_cases(HERE / "cases.json", TASK)
        self.dev = [c for c in self.cases["cases"] if c["split"] == "development"]
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)

    def grade(self, log, trials):
        path = self.dir / "recording.json"
        harness.write(path, bench.to_recording(log, self.cases))
        return harness.run(harness.ReplaySystem(path, self.cases), self.cases, TASK, trials=trials)

    def test_recorded_runs_and_report_match_fresh_runs(self):
        records = []
        for name in SYSTEMS:
            with self.subTest(system=name):
                recording = bench.to_recording(HERE / f"recorded/{name}.jsonl", self.cases)
                self.assertEqual(harness.without_run_description(recording),
                                 harness.without_run_description(stored(f"recorded/{name}.json")))
                fresh = harness.run(harness.ReplaySystem(HERE / f"recorded/{name}.json", self.cases), self.cases,
                                    TASK, trials=recording["trials"])
                self.assertEqual(harness.without_run_description(fresh),
                                 harness.without_run_description(stored(f"runs/{name}.json")))
                records.append(stored(f"runs/{name}.json"))
        self.assertEqual(report.build_report(records), stored("runs/report.json"))
        partial = report.build_report([stored("runs/gemma-partial.json")])
        self.assertEqual(partial, stored("runs/report-partial.json"))

    def test_trials_run_in_trial_major_order(self):
        system = Scripted(right)
        bench.run_bench(system, self.cases, ["development"], 2, self.dir / "log.jsonl")
        ids = [c["id"] for c in self.dev]
        self.assertEqual(system.calls, [(i, 0) for i in ids] + [(i, 1) for i in ids])

    def test_resume_skips_logged_trials_and_drops_a_partial_line(self):
        log = self.dir / "log.jsonl"
        first = Scripted(lambda case, trial: KeyboardInterrupt() if len(first.calls) == 4 else right(case, trial))
        with self.assertRaises(KeyboardInterrupt):  # Stops the run like Ctrl-C on the fourth call.
            bench.run_bench(first, self.cases, ["development"], 2, log)
        with log.open("a", encoding="utf-8") as handle:
            handle.write('{"case_id": "charged-tw')  # A line cut off by a crash.
        second = Scripted(right)
        counts = bench.run_bench(second, self.cases, ["development"], 2, log)
        self.assertEqual((counts["already_logged"], counts["ran"], counts["not_run"]), (3, 2 * len(self.dev) - 3, 0))
        self.assertNotIn(first.calls[0], second.calls)
        record = self.grade(log, 2)
        self.assertEqual(record["summary"]["development"]["pass"], 2 * len(self.dev))

    def test_resume_preserves_a_complete_last_row_without_newline(self):
        log = self.dir / "log.jsonl"
        bench.run_bench(Scripted(right), self.cases, ["development"], 1, log)
        original = log.read_bytes()
        log.write_bytes(original.rstrip(b"\n"))
        second = Scripted(right)
        counts = bench.run_bench(second, self.cases, ["development"], 1, log)
        self.assertEqual(second.calls, [])
        self.assertEqual(counts["already_logged"], len(self.dev))
        self.assertEqual(log.read_bytes(), original)
        self.assertEqual(self.grade(log, 1)["summary"]["development"]["pass"], len(self.dev))

    def test_log_for_another_plan_is_refused(self):
        log = self.dir / "log.jsonl"
        bench.run_bench(Scripted(right), self.cases, ["development"], 2, log)
        with self.assertRaisesRegex(bench.BenchError, "trials"):
            bench.run_bench(Scripted(right), self.cases, ["development"], 3, log)
        with self.assertRaisesRegex(bench.BenchError, "system"):
            bench.run_bench(Scripted(right, name="other"), self.cases, ["development"], 2, log)

    def test_budget_stops_and_unrun_trials_are_incomplete(self):
        ticks = itertools.count()
        counts = bench.run_bench(Scripted(right), self.cases, ["development"], 3, self.dir / "log.jsonl",
                                 budget_s=5, clock=lambda: next(ticks))
        self.assertTrue(counts["stopped_by_budget"])
        self.assertEqual(counts["ran"] + counts["not_run"], 3 * len(self.dev))
        record = self.grade(self.dir / "log.jsonl", 3)
        summary = record["summary"]["development"]
        self.assertEqual((summary["pass"], summary["incomplete"]), (counts["ran"], counts["not_run"]))
        reasons = {row["reason"] for row in record["results"] if row["verdict"] == "incomplete"}
        self.assertEqual(reasons, {"NotRun: not run: the benchmark stopped first"})
        section = report.system_report(record)  # Unrun trials are not flakiness, and give no pass@k.
        self.assertEqual((section["not_run"], section["flaky_cases"], section["curve"]), (counts["not_run"], [], None))

    def test_errors_are_logged_not_raised(self):
        def flaky(case, trial):
            return TimeoutError("timed out") if trial == 1 and "rejected" not in case["expected"] else right(case, trial)
        bench.run_bench(Scripted(flaky), self.cases, ["development"], 2, self.dir / "log.jsonl")
        record = self.grade(self.dir / "log.jsonl", 2)
        section = report.system_report(record)
        model_cases = sum("rejected" not in c["expected"] for c in self.dev)
        self.assertEqual(section["incomplete_by_error"], {"TimeoutError": model_cases})
        self.assertEqual(len(section["flaky_cases"]), model_cases)

    def test_duplicate_or_foreign_log_is_refused(self):
        log = self.dir / "log.jsonl"
        bench.run_bench(Scripted(right), self.cases, ["development"], 1, log)
        lines = log.read_text(encoding="utf-8").splitlines()
        log.write_text("\n".join(lines + [lines[1]]) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(bench.BenchError, "logged twice"):
            bench.to_recording(log, self.cases)
        edited = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
        edited["cases"][0]["input"] += " Thanks."
        other = harness.load_cases(self.write_json(edited), TASK)
        with self.assertRaisesRegex(bench.BenchError, "different case set"):
            bench.to_recording(log, other)

    def write_json(self, data):
        path = self.dir / f"{len(list(self.dir.iterdir()))}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_error_rows_keep_their_seed_and_the_header_its_budget(self):
        system = Scripted(lambda case, trial: TimeoutError("timed out") if "rejected" not in case["expected"] else right(case, trial))
        system.seed_for = lambda trial: 1000 + trial
        log = self.dir / "log.jsonl"
        bench.run_bench(system, self.cases, ["development"], 2, log, budget_s=60)
        header, rows = bench.read_log(log)
        self.assertEqual(header["budget_s"], 60)
        failed = [row for row in rows if "error" in row and row["error"]["types"][0] == "TimeoutError"]
        self.assertTrue(failed)
        self.assertTrue(all(row["metadata"] == {"seed": 1000 + row["trial"]} for row in failed))

    def test_recordings_have_identical_output_digests(self):
        recordings = stored("recorded/recordings.json")["recordings"]
        for name in SYSTEMS:
            with self.subTest(system=name):
                self.assertEqual(recordings[-1][name], outputs_digest.digest(HERE / f"recorded/{name}.jsonl"))
                self.assertEqual(len({r[name]["outputs_sha256"] for r in recordings}), 1)
        self.assertGreaterEqual(len(recordings), 2)

    def test_estimators_match_counting_every_subset(self):
        for n in range(1, 7):
            for c in range(n + 1):
                outcomes = [True] * c + [False] * (n - c)
                for k in range(1, n + 1):
                    subsets = list(itertools.combinations(outcomes, k))
                    with self.subTest(n=n, c=c, k=k):
                        self.assertAlmostEqual(report.pass_at_k(n, c, k), sum(any(s) for s in subsets) / len(subsets))
                        self.assertAlmostEqual(report.pass_power_k(n, c, k), sum(all(s) for s in subsets) / len(subsets))

    def test_report_counts_flaky_cases_and_latency(self):
        def half(case, trial):
            if case["id"] == "late-order" and trial % 2:
                return {"category": "other", "needs_human": False}
            return right(case, trial)
        bench.run_bench(Scripted(half), self.cases, ["development"], 4, self.dir / "log.jsonl")
        section = report.system_report(self.grade(self.dir / "log.jsonl", 4))
        self.assertEqual(section["flaky_cases"], ["late-order"])
        self.assertEqual(section["per_case"]["late-order"]["pass"], 2)
        self.assertEqual(section["failures_by_check"], {"triage-outcome": 2})
        cases = section["cases"]
        self.assertEqual(section["curve"]["4"]["pass_at_k"], 1.0)
        self.assertEqual(section["curve"]["4"]["pass_power_k"], round((cases - 1) / cases, 4))
        self.assertEqual(report.nearest_rank([5, 1, 3, 2, 4], 0.9), 5)
        self.assertEqual(report.nearest_rank([5, 1, 3, 2, 4], 0.5), 3)

    def test_model_system_checks_input_and_replies(self):
        case = dict(self.dev[0])
        replies = [
            {"message": {"content": '{"category": "billing", "needs_human": false}'}, "done_reason": "stop", "eval_count": 9},
            {"message": {"content": '{"category": "bill'}, "done_reason": "length", "eval_count": 64},
            {"message": {"content": "Billing."}, "done_reason": "stop", "eval_count": 2},
        ]
        system = model_triage.ModelTriage("gemma4:e2b")
        system.server = "test"
        seeds = []

        def chat(message, seed):
            seeds.append(seed)
            return replies[len(seeds) - 1]
        with mock.patch.object(system, "chat", chat):
            answer = system.respond(case, 0)
            self.assertEqual(answer.output, {"category": "billing", "needs_human": False})
            self.assertEqual(answer.metadata["seed"], model_triage.SEED_BASE)
            with self.assertRaises(model_triage.TruncatedReply):
                system.respond(case, 1)
            with self.assertRaises(json.JSONDecodeError):
                system.respond(case, 2)
            for text, message in (("   ", "blank"), (None, "not text")):
                with self.assertRaisesRegex(ValueError, message):
                    system.respond(dict(case, input=text), 3)
        self.assertEqual(seeds, [model_triage.SEED_BASE + t for t in range(3)])

    def test_unpinned_model_is_refused(self):
        system = model_triage.ModelTriage("gemma4:e2b")
        tags = {"models": [{"name": "gemma4:e2b", "digest": "0" * 64}]}
        with mock.patch.object(model_triage, "get", lambda path: tags):
            with self.assertRaisesRegex(RuntimeError, "not installed with digest"):
                system.check_model()

    def test_main_checks_the_model_before_logging_any_trial(self):
        class WrongWeights:
            mode, model, prompt, tools, index = "live", None, None, None, None
            name, version, calls = "wrong-weights", "test", []

            def check_model(self):
                raise RuntimeError("gemma4:e2b is not installed with digest b37049369adf")

            def respond(self, case, trial):
                self.calls.append((case["id"], trial))
                raise RuntimeError("no model")
        system = WrongWeights()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(harness, "load_system", lambda spec, cases: system):
            log = Path(tmp) / "wrong.jsonl"
            with self.assertRaisesRegex(bench.BenchError, "not installed with digest"):
                bench.main(["--cases", str(HERE / "cases.json"), "--system", "model_triage:gemma", "--trials", "2",
                            "--log", str(log)])
            self.assertFalse(log.exists())
        self.assertEqual(system.calls, [])

if __name__ == "__main__":
    unittest.main()
