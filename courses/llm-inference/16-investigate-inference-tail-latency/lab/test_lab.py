"""Unit and failure-boundary tests for inference telemetry and 10x p99 spike diagnostics."""

from __future__ import annotations

import unittest

from lab import (
    RequestLog,
    diagnose_p99_spike,
    simulate_workload_logs,
)


class TestInferenceMetricsAndP99Spikes(unittest.TestCase):
    def test_single_token_and_zero_duration_metrics_are_undefined(self):
        row = RequestLog("one", 1, 1, 0, 0, 9, False, 0, 0, 0)
        result = diagnose_p99_spike("one", [row])
        self.assertIsNone(result.p50_tpot_ms)
        self.assertIsNone(result.p99_tpot_ms)
        self.assertIsNone(result.p99_to_p50_ratio)

    def test_kv_headroom_gating_and_chunked_prefill_collapse_p99_spike(self) -> None:
        before = diagnose_p99_spike(
            "unbounded",
            simulate_workload_logs(admit_watermark_pct=98.5, chunked_prefill=False),
        )
        after = diagnose_p99_spike(
            "gated",
            simulate_workload_logs(admit_watermark_pct=85.0, chunked_prefill=True),
        )
        self.assertGreater(before.p99_to_p50_ratio, 10.0)
        self.assertEqual(
            before.diagnostic_hypothesis, "kv_cache_preemption_and_recompute_thrashing"
        )
        self.assertLessEqual(after.p99_to_p50_ratio, 2.1)
        self.assertEqual(after.preemption_count, 0)
        self.assertEqual(after.diagnostic_hypothesis, "no_rule_matched")
        self.assertLess(
            after.modeled_cost_per_1k_requests_usd,
            before.modeled_cost_per_1k_requests_usd,
        )

    def test_averaging_latency_hides_10x_p99_preemption_spike(self) -> None:
        logs = simulate_workload_logs(admit_watermark_pct=98.5, chunked_prefill=False)
        snap = diagnose_p99_spike("unbounded", logs)
        # p50 and mean look deceptively low (< 3.1s), while p99 exceeds 23s (>12x p50)
        self.assertLess(snap.p50_e2e_ms, 2000.0)
        self.assertLess(snap.mean_e2e_ms, 3100.0)
        self.assertGreater(snap.p99_e2e_ms, snap.p50_e2e_ms * 10.0)
        self.assertGreater(snap.p99_e2e_ms, snap.mean_e2e_ms * 7.0)

    def test_kv_thrashing_cascades_recompute_queue_delay(self) -> None:
        logs = simulate_workload_logs(admit_watermark_pct=98.5, chunked_prefill=False)
        preempted_reqs = [r for r in logs if r.preempted]
        self.assertEqual(len(preempted_reqs), 5)
        # Each subsequent preempted request suffers strictly worse queue wait and recompute delay
        for prev, curr in zip(preempted_reqs, preempted_reqs[1:]):
            self.assertGreater(curr.queue_wait_ms, prev.queue_wait_ms)
            self.assertGreater(curr.recompute_penalty_ms, prev.recompute_penalty_ms)


class TelemetryBoundaryTests(unittest.TestCase):
    def test_no_matching_rule_does_not_claim_slo_success(self):
        from lab import RequestLog

        record = RequestLog("slow", 32, 2, 60000, 100, 10, False, 0, 32, 50)
        result = diagnose_p99_spike("slow", [record])
        self.assertEqual(result.diagnostic_hypothesis, "no_rule_matched")
        self.assertEqual(result.p99_ttft_ms, 60100)

    def test_first_token_is_not_counted_as_an_extra_decode(self):
        from lab import RequestLog

        self.assertEqual(RequestLog("one", 32, 1, 4, 6, 10, False, 0, 0, 50).e2e_ms, 10)


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('percentile([],50)', 'empty list'), ('diagnose_p99_spike("empty",[])', 'logs must'), ('RequestLog("x",0,1,0,0,1,False,0,0,0)', 'token counts'), ('RequestLog("x",1,1,-1,0,1,False,0,0,0)', 'measurements')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
