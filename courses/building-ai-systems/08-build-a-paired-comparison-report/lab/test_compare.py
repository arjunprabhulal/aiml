"""Tests for the paired comparison report. Run: python3 -m unittest -v test_compare.py

No test calls a model: the recorded logs are replayed through the harness, and
the comparison is checked on scripted systems with known answers.
"""
import itertools
import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bench
import compare
import harness
import model_triage

HERE = Path(__file__).resolve().parent
TASK = harness.load_task("triage_task")


def stored(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


class Scripted:
    """Right answer unless wrong(case, trial) says otherwise; rejections are raised as the case requires."""
    mode, model, prompt, tools, index = "live", None, None, None, None

    def __init__(self, wrong, version):
        self.wrong, self.name, self.version = wrong, "scripted", version

    def respond(self, case, trial):
        if "rejected" in case["expected"]:
            raise ValueError("message is blank" if case["input"] is not None else "message is not text")
        if self.wrong(case, trial):
            return {"category": "other" if case["expected"]["category"] != "other" else "billing", "needs_human": True}
        return {"category": case["expected"]["category"], "needs_human": True}


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.cases = harness.load_cases(HERE / "cases-robustness.json", TASK)
        self.dev = [c for c in self.cases["cases"] if c["split"] == "development"]

    def run_system(self, wrong, version, trials=4):
        return harness.run(Scripted(wrong, version), self.cases, TASK, trials=trials)

    def test_recorded_runs_and_comparison_match_fresh_runs(self):
        records = {}
        for name in ("qwen-v1", "qwen-v2"):
            with self.subTest(system=name):
                recording = bench.to_recording(HERE / f"recorded/{name}.jsonl", self.cases)
                self.assertEqual(harness.without_run_description(recording),
                                 harness.without_run_description(stored(f"recorded/{name}.json")))
                records[name] = harness.run(harness.ReplaySystem(HERE / f"recorded/{name}.json", self.cases),
                                            self.cases, TASK, trials=recording["trials"])
                self.assertEqual(harness.without_run_description(records[name]),
                                 harness.without_run_description(stored(f"runs/{name}.json")))
        self.assertEqual(compare.compare(records["qwen-v1"], records["qwen-v2"], self.cases),
                         stored("runs/comparison.json"))

    def test_runs_measured_differently_are_refused(self):
        base = self.run_system(lambda c, t: False, "a")
        with self.assertRaisesRegex(harness.RunError, "trials"):
            compare.compare(base, self.run_system(lambda c, t: False, "b", trials=3), self.cases)
        edited = json.loads((HERE / "cases-robustness.json").read_text(encoding="utf-8"))
        edited["cases"][0]["input"] += " Thanks."
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "edited-cases.json"
        path.write_text(json.dumps(edited), encoding="utf-8")
        with self.assertRaisesRegex(harness.RunError, "another version"):
            compare.compare(base, self.run_system(lambda c, t: False, "b"), harness.load_cases(path, TASK))

    def test_difference_and_case_counts(self):
        late = {"late-order", "charged-twice"}
        base = self.run_system(lambda c, t: c["id"] in late, "a")                     # Fails 2 cases always.
        cand = self.run_system(lambda c, t: c["id"] == "charged-twice" and t < 2, "b")  # Half of one case.
        result = compare.compare(base, cand, self.cases)
        o = result["overall"]
        self.assertEqual((o["better"], o["worse"], o["same"]), (2, 0, len(self.dev) - 2))
        self.assertAlmostEqual(o["difference"], round((1 + 0.5) / len(self.dev), 4))
        self.assertEqual(result["cases"], [{"case_id": "charged-twice", "baseline": 0.0, "candidate": 0.5},
                                           {"case_id": "late-order", "baseline": 0.0, "candidate": 1.0}])
        self.assertEqual(result["trial_pairs"], {"both_pass": 4 * (len(self.dev) - 2), "only_baseline": 0,
                                                 "only_candidate": 6, "neither": 2})

    def test_bootstrap_interval_is_seeded_and_brackets_the_mean(self):
        values = [0, 0, 1, 0, 1, 1, 0, 0, 0, 1]
        first = compare.interval(values, random.Random(compare.SEED))
        self.assertEqual(first, compare.interval(values, random.Random(compare.SEED)))
        self.assertLess(first[0], compare.mean(values))  # Resampling spreads the means around the mean.
        self.assertGreater(first[1], compare.mean(values))
        self.assertEqual(compare.interval([0.25] * 6, random.Random(1)), [0.25, 0.25])

    def test_trial_level_interval_is_narrower_than_case_level(self):
        # Every trial of a case agrees with the others: 4 trials carry the information of 1.
        flip = {c["id"] for c in self.dev[::3] if "rejected" not in c["expected"]}
        base = self.run_system(lambda c, t: False, "a")
        cand = self.run_system(lambda c, t: c["id"] in flip, "b")
        o = compare.compare(base, cand, self.cases)["overall"]
        width = lambda pair: pair[1] - pair[0]
        self.assertLess(width(o["trial_level_interval_95"]), width(o["interval_95"]))

    def test_variants_of_one_source_are_resampled_together(self):
        # The candidate fixes every variant of one source case: several "independent" improvements
        # at the case level, one improvement at the source level.
        base = self.run_system(lambda c, t: c["tags"].get("source") == "late-order", "a")
        cand = self.run_system(lambda c, t: False, "b")
        o = compare.compare(base, cand, self.cases)["overall"]
        self.assertEqual(o["source_groups"], len({c["tags"].get("source", c["id"]) for c in self.dev}))
        self.assertGreater(o["interval_95"][0], 0)
        self.assertEqual(o["source_cluster_interval_95"][0], 0.0)
        groups = {"a": [1, 1, 1, 1], "b": [0]}
        self.assertEqual(compare.grouped_interval(groups, random.Random(compare.SEED)), [0.0, 1.0])

    def test_exact_source_interval_pins_the_no_gain_share(self):
        result = compare.compare(stored("runs/qwen-v1.json"), stored("runs/qwen-v2.json"), self.cases)
        o = result["overall"]
        changed_sources = {self.tag(c["case_id"])["source"] for c in result["cases"]}
        unchanged = o["source_groups"] - len(changed_sources)
        # No case got worse, so a draw shows no gain exactly when it misses every changed source.
        self.assertEqual(o["source_no_gain_share"], round((unchanged / o["source_groups"]) ** o["source_groups"], 4))
        self.assertTrue(o["source_cluster_method"].startswith("exact"))
        self.assertEqual(o["source_cluster_interval_95"][0], 0.0)  # The no-gain share is above 2.5%.

    def test_sampled_lower_end_depends_on_the_seed(self):
        # Rebuild the source groups of the recorded comparison and sample them with 50 seeds.
        v1, v2 = compare.shares(stored("runs/qwen-v1.json")), compare.shares(stored("runs/qwen-v2.json"))
        groups = {}
        for case_id in v1:
            groups.setdefault(self.tag(case_id).get("source", case_id), []).append(v2[case_id] - v1[case_id])
        lower = {compare.grouped_interval(groups, random.Random(seed))[0] > 0 for seed in range(50)}
        self.assertEqual(lower, {True, False})  # Some seeds put the lower end at 0, others above it.

    def test_exact_grouped_interval_matches_every_draw(self):
        groups = {"a": [1.0, 1.0], "b": [0.0], "c": [-0.5, 0.0, 0.5]}
        exact = compare.exact_grouped(groups)
        names = list(groups)
        means = sorted(compare.mean([v for g in draw for v in groups[g]]) for draw in itertools.product(names, repeat=3))
        cumulative = lambda share: means[math.ceil(share * len(means)) - 1]
        self.assertEqual(exact["interval_95"], [round(cumulative(0.025), 4), round(cumulative(0.975), 4)])
        self.assertEqual(exact["share_at_or_below_zero"], round(sum(m <= 0 for m in means) / len(means), 4))
        with mock.patch.object(compare, "EXACT_LIMIT", 1):
            self.assertIsNone(compare.exact_grouped(groups))

    def tag(self, case_id):
        return next(c for c in self.cases["cases"] if c["id"] == case_id)["tags"]

    def test_slices_cover_every_tag_value_and_mark_few_cases(self):
        base = self.run_system(lambda c, t: False, "a")
        cand = self.run_system(lambda c, t: c["tags"].get("language") == "es", "b")
        result = compare.compare(base, cand, self.cases)
        self.assertNotIn("source", result["slices"])
        es, en = result["slices"]["language"]["es"], result["slices"]["language"]["en"]
        self.assertEqual((es["difference"], es["worse"], en["difference"]), (-1.0, es["cases"], 0.0))
        self.assertEqual(sum(s["cases"] for s in result["slices"]["variant"].values()), len(self.dev))
        self.assertTrue(es["few_cases"])
        self.assertFalse(en["few_cases"])

    def test_prompt_versions_send_their_own_system_message(self):
        sent = []
        case = next(c for c in self.dev if "rejected" not in c["expected"])
        for system in (model_triage.qwen_v1, model_triage.qwen_v2):
            system.server = "test"
            reply = {"message": {"content": '{"category": "billing", "needs_human": false}'}, "done_reason": "stop"}
            with mock.patch.object(model_triage, "post", lambda path, body: sent.append(body) or reply):
                system.respond(case, 0)
        self.assertEqual([b["messages"][0]["content"] for b in sent], [model_triage.PROMPT_V1, model_triage.PROMPT_V2])
        self.assertTrue(model_triage.PROMPT_V2.startswith(model_triage.PROMPT_V1))
        self.assertEqual([b["options"]["seed"] for b in sent], [model_triage.SEED_BASE] * 2)
        self.assertNotEqual(model_triage.qwen_v1.prompt, model_triage.qwen_v2.prompt)

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
                bench.main(["--cases", str(HERE / "cases-robustness.json"), "--system", "model_triage:gemma", "--trials", "2",
                            "--log", str(log)])
            self.assertFalse(log.exists())
        self.assertEqual(system.calls, [])

if __name__ == "__main__":
    unittest.main()
