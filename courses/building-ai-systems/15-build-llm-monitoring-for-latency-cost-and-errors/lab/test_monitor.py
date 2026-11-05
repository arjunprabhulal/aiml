"""Tests for monitor.py: python3 -m unittest -v test_monitor.py

Everything runs on the simulated clock, so every count and duration is exact.
"""
import json
import unittest
from pathlib import Path

import extract_calls
import monitor

HERE = Path(__file__).resolve().parent
CONFIGS = {c["name"]: c for c in monitor.TRAFFIC["configs"]}


class Primitives(unittest.TestCase):
    def test_a_value_on_a_bucket_bound_is_counted_in_that_bucket(self):
        histogram = monitor.Histogram((1.0, 2.0))
        for value in (1.0, 1.5, 2.0, 2.5):
            histogram.record(value)
        self.assertEqual(histogram.counts, [1, 2, 1])  # (0,1], (1,2], (2,+Inf)

    def test_bucket_quantile_interpolates_linearly_inside_its_bucket(self):
        histogram = monitor.Histogram((1.0, 2.0, 4.0))
        histogram.counts = [2, 0, 8, 0]
        # q=0.6 of 10 is rank 6: 4 of the 8 values in (2, 4], so 2 + 2 * 4/8 = 3.
        self.assertAlmostEqual(histogram.quantile(0.6), 3.0)
        self.assertAlmostEqual(histogram.quantile(0.1), 0.5)  # the lowest bucket starts at 0

    def test_a_quantile_in_the_inf_bucket_returns_the_highest_bound_and_empty_is_none(self):
        histogram = monitor.Histogram((1.0, 2.0))
        histogram.counts = [1, 0, 9]
        self.assertEqual(histogram.quantile(0.95), 2.0)
        self.assertIsNone(monitor.Histogram((1.0,)).quantile(0.5))

    def test_nearest_rank_rounds_the_rank_up(self):
        self.assertEqual(monitor.nearest_rank([70, 10, 50, 30, 60, 20, 40], 95), 70)
        self.assertEqual(monitor.nearest_rank([70, 10, 50, 30, 60, 20, 40], 50), 40)

    def test_cost_uses_both_token_prices(self):
        self.assertEqual(monitor.cost_usd(1_000_000, 0), monitor.PRICES["input_usd_per_million"])
        self.assertEqual(monitor.cost_usd(0, 1_000_000), monitor.PRICES["output_usd_per_million"])


class Simulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {name: monitor.simulate(config) for name, config in CONFIGS.items()}
        cls.runs = {run["name"]: run for run in monitor.results()["runs"]}

    def test_saved_monitoring_matches_a_fresh_run_byte_for_byte(self):
        self.assertEqual((HERE / "monitoring.json").read_text(), monitor.record(monitor.results()))

    def test_calls_are_the_recorded_model_calls_from_the_tracing_build(self):
        self.assertEqual(json.loads((HERE / "calls.json").read_text()), extract_calls.extract())

    def test_a_full_queue_answers_503_at_once(self):
        rejected = [r for r in self.rows["B"] if r["status"] == "503"]
        self.assertTrue(rejected)
        self.assertTrue(all(r["latency_ms"] == 0 and not r["ran"] for r in rejected))
        self.assertTrue(all(r["depth_at_arrival"] > CONFIGS["B"]["queue_limit"] for r in rejected))

    def test_a_client_timeout_caps_latency_but_the_worker_still_runs_the_call(self):
        timed_out = [r for r in self.rows["A"] if r["status"] == "timeout"]
        limit = monitor.TRAFFIC["client_timeout_ms"]
        self.assertTrue(timed_out and all(r["latency_ms"] == limit and r["end_ms"] == r["arrival_ms"] + limit
                                          for r in timed_out))
        self.assertTrue(all(r["ran"] for r in timed_out))
        self.assertGreater(self.runs["A"]["wasted_model_ms"], 0)

    def test_dropping_expired_calls_skips_work_nobody_waits_for(self):
        skipped = [r for r in self.rows["B"] if r["status"] == "timeout" and not r["ran"]]
        self.assertTrue(skipped)
        self.assertLess(self.runs["B"]["wasted_model_ms"], self.runs["A"]["wasted_model_ms"])
        self.assertGreater(self.runs["B"]["totals"]["ok"], self.runs["A"]["totals"]["ok"])

    def test_every_request_ends_in_exactly_one_window(self):
        for run in self.runs.values():
            self.assertEqual(sum(w["ended"] for w in run["windows"]), run["requests"])
            self.assertEqual(sum(w["arrivals"] for w in run["windows"]), run["requests"])

    def test_a_request_is_counted_in_the_window_where_its_client_saw_it_end(self):
        size = monitor.TRAFFIC["window_seconds"] * 1000
        crossing = [r for r in self.rows["A"] if r["arrival_ms"] // size != r["end_ms"] // size]
        self.assertTrue(crossing)  # timeouts that arrive late in one window end in the next
        for w in self.runs["A"]["windows"]:
            self.assertEqual(w["ended"], sum(r["end_ms"] // size == w["window"] for r in self.rows["A"]))

    def test_error_rate_counts_503s_and_timeouts_over_every_ended_request(self):
        for w in self.runs["A"]["windows"]:
            errors = w["errors"]["503"] + w["errors"]["timeout"]
            self.assertEqual(w["error_rate"], round(errors / w["ended"], 4) if w["ended"] else 0.0)
        self.assertEqual(self.runs["A"]["windows"][5]["error_rate"], 1.0)

    def test_tokens_count_calls_whose_client_already_gave_up(self):
        a = self.runs["A"]
        ran_tokens = sum(r["output_tokens"] for r in self.rows["A"] if r["ran"])
        self.assertEqual(sum(w["output_tokens"] for w in a["windows"]), ran_tokens)
        self.assertGreater(a["windows"][5]["output_tokens"], 0)  # no answer reached a client in this window


class Alerts(unittest.TestCase):
    rule = {"name": "R", "metric": "error_rate", "threshold": 0.05, "for_windows": 2}

    def timeline(self, values):
        windows = [{"window": i, "error_rate": v} for i, v in enumerate(values)]
        return [row["R"] for row in monitor.evaluate(windows, [self.rule])[0]]

    def test_a_rule_is_pending_until_it_holds_for_its_windows_then_fires(self):
        self.assertEqual(self.timeline([0.0, 0.2, 0.2, 0.2, 0.0]),
                         ["inactive", "pending", "firing", "firing", "inactive"])

    def test_one_bad_window_stays_pending_and_never_fires(self):
        self.assertEqual(self.timeline([0.2, 0.0, 0.2, 0.0]), ["pending", "inactive", "pending", "inactive"])

    def test_missing_data_counts_as_not_met_so_the_alert_resolves(self):
        # The recorded run shows this trap: with no answered request, p95 has no value.
        self.assertEqual(self.timeline([0.2, 0.2, None]), ["pending", "firing", "inactive"])


if __name__ == "__main__":
    unittest.main()
