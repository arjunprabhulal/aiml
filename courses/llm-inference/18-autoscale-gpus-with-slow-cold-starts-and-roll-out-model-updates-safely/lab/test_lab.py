"""Unit and failure-mode tests for GPU autoscaling with slow cold starts and canary model rollouts."""

from __future__ import annotations

import unittest

from lab import (
    AutoscalerConfig,
    CanaryGate,
    CanaryStageSample,
    simulate_autoscaler,
    simulate_cold_start_and_rollout,
)


class AutoscalingAndRolloutTest(unittest.TestCase):
    def test_threshold_breaches_are_not_rounded_away(self):
        gate = CanaryGate()
        for sample in [
            CanaryStageSample(5, 200, 28, 34.001, 0.8, 0.8, 0),
            CanaryStageSample(5, 200, 28, 28, 0.8, 0.78499, 0),
        ]:
            self.assertFalse(gate.evaluate_stage(sample)["passed"])

    def test_combined_fast_start_scenario_keeps_finite_standby_accounting(
        self,
    ) -> None:
        report = simulate_cold_start_and_rollout()
        leading = report["autoscaling_comparison"]["leading_kv_and_velocity"]
        self.assertEqual(leading["slo_breach_windows"], 1)
        self.assertGreater(leading["peak_p99_ttft_ms"], 450.0)
        remaining = [s["warm_standby_remaining"] for s in leading["timeline"]]
        self.assertEqual(remaining, sorted(remaining, reverse=True))
        self.assertEqual(remaining[-1], 0)
        self.assertGreaterEqual(leading["max_ready_replicas"], 10)

    def test_scaling_on_gpu_utilization_reacts_after_slo_breach(self) -> None:
        reactive = simulate_autoscaler(
            AutoscalerConfig(
                mode="reactive_gpu_util",
                cold_start_seconds=180,
                warm_standby_replicas=0,
            )
        )
        leading = simulate_autoscaler(
            AutoscalerConfig(
                mode="leading_kv_and_velocity",
                target_kv_utilization=0.68,
                warm_standby_replicas=2,
                fast_weight_stream_seconds=22,
            )
        )
        # Reactive scaling triggers late and waits 180s for weights, breaching the 450ms TTFT SLO across the surge.
        self.assertGreaterEqual(reactive["slo_breach_windows"], 6)
        self.assertGreater(reactive["peak_p99_ttft_ms"], 1800.0)
        self.assertEqual(leading["slo_breach_windows"], 1)

    def test_canary_recommends_rollback_on_quality_or_tpot_regression(
        self,
    ) -> None:
        report = simulate_cold_start_and_rollout()
        defective = report["canary_rollouts"]["defective_int4_build"]
        healthy = report["canary_rollouts"]["validated_fp8_build"]

        self.assertTrue(defective["rolled_back"])
        self.assertFalse(defective["completed_100_percent"])
        self.assertEqual(defective["final_canary_traffic_percent"], 0)
        self.assertIn("tpot_slo_regression", defective["rollback_reasons"])
        self.assertIn("quality_score_regression", defective["rollback_reasons"])
        # Stage 100% never runs after Stage 25% trips the rollback gate.
        self.assertEqual(len(defective["stages"]), 2)

        self.assertFalse(healthy["rolled_back"])
        self.assertTrue(healthy["completed_100_percent"])
        self.assertEqual(healthy["final_canary_traffic_percent"], 100)

    def test_canary_gate_rejects_elevated_error_rate_even_when_fast(self) -> None:
        gate = CanaryGate()
        verdict = gate.evaluate_stage(
            CanaryStageSample(
                stage_percent=5,
                requests_evaluated=200,
                baseline_p99_tpot_ms=28.0,
                canary_p99_tpot_ms=25.0,
                baseline_exact_match=0.840,
                canary_exact_match=0.839,
                canary_error_rate=0.018,
            )
        )
        self.assertFalse(verdict["passed"])
        self.assertEqual(verdict["decision"], "rollback_to_0_percent")
        self.assertIn("error_rate_breach", verdict["reasons"])


class CanaryValidationTests(unittest.TestCase):
    def test_nonfinite_sample_cannot_pass_gates(self):
        with self.assertRaises(ValueError):
            CanaryStageSample(5, 200, 20, float("nan"), 0.8, 0.8, 0)

    def test_empty_observation_cannot_be_promoted(self):
        with self.assertRaises(ValueError):
            CanaryStageSample(5, 0, 20, 20, 0.8, 0.8, 0)


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('AutoscalerConfig("reactive_gpu_util",min_replicas=0)', 'replica bounds'), ('AutoscalerConfig("reactive_gpu_util",target_kv_utilization=0)', 'target_kv'), ('CanaryStageSample(5,1,1,1,2,1,0)', 'canary rate'), ('a=CanaryStageSample(5,1,1,1,1,1,0)\nCanaryGate().run_rollout([a,a])', 'stages must')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
