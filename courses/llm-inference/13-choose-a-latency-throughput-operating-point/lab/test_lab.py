"""Unit and failure-boundary tests for the decode latency-throughput Pareto optimizer."""

from __future__ import annotations

import unittest

from lab import (
    ServingConfig,
    build_candidate_sweep,
    compute_decode_step_profile,
    pareto_frontier,
    select_pareto_config,
)


class TestLatencyThroughputPareto(unittest.TestCase):
    def test_selected_config_satisfies_sla_and_beats_small_batch(self) -> None:
        sweep = build_candidate_sweep()
        result = select_pareto_config(sweep, sla_tpot_ms=25.0)
        selected = result["selected"]
        self.assertTrue(selected["fits_hbm"])
        self.assertLessEqual(selected["tpot_ms"], 25.0)
        self.assertEqual(selected["precision"], "fp8")
        self.assertGreater(selected["tokens_per_s_per_gpu"], 600.0)

    def test_bf16_single_gpu_70b_rejected_by_hbm_capacity(self) -> None:
        profile = compute_decode_step_profile(
            ServingConfig(
                name="bf16-tp1-b16",
                precision="bf16",
                tp_degree=1,
                batch_size=16,
            )
        )
        self.assertFalse(profile.fits_hbm)
        self.assertGreater(profile.memory_per_gpu_gb, 80.0)

    def test_tensor_parallel_over_pcie_adds_allreduce_bottleneck(self) -> None:
        nvlink_profile = compute_decode_step_profile(
            ServingConfig(
                name="fp8-tp4-b64-nvlink",
                precision="fp8",
                tp_degree=4,
                batch_size=64,
                interconnect="nvlink",
            )
        )
        pcie_profile = compute_decode_step_profile(
            ServingConfig(
                name="fp8-tp4-b64-pcie",
                precision="fp8",
                tp_degree=4,
                batch_size=64,
                interconnect="pcie",
            )
        )
        self.assertLessEqual(nvlink_profile.tpot_ms, 25.0)
        self.assertGreater(pcie_profile.tpot_ms, 25.0)
        self.assertEqual(pcie_profile.bottleneck, "allreduce_comm")
        self.assertGreater(pcie_profile.allreduce_ms, nvlink_profile.allreduce_ms * 5.0)

    def test_oversized_batch_pushes_tpot_past_sla(self) -> None:
        b64 = compute_decode_step_profile(
            ServingConfig(
                name="fp8-tp2-b64-nvlink",
                precision="fp8",
                tp_degree=2,
                batch_size=64,
                interconnect="nvlink",
            )
        )
        b128 = compute_decode_step_profile(
            ServingConfig(
                name="fp8-tp2-b128-nvlink",
                precision="fp8",
                tp_degree=2,
                batch_size=128,
                interconnect="nvlink",
            )
        )
        self.assertLessEqual(b64.tpot_ms, 25.0)
        self.assertGreater(b128.tpot_ms, 25.0)
        self.assertGreater(b128.kv_read_ms, b64.kv_read_ms)

    def test_pareto_frontier_excludes_dominated_points(self) -> None:
        profiles = [compute_decode_step_profile(c) for c in build_candidate_sweep()]
        frontier = pareto_frontier(profiles)
        for p in frontier:
            self.assertTrue(p.fits_hbm)
            for other in frontier:
                if other is p:
                    continue
                self.assertFalse(
                    other.tpot_ms <= p.tpot_ms
                    and other.tokens_per_s_per_gpu >= p.tokens_per_s_per_gpu
                    and (
                        other.tpot_ms < p.tpot_ms
                        or other.tokens_per_s_per_gpu > p.tokens_per_s_per_gpu
                    )
                )


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('compute_decode_step_profile(ServingConfig("x","bf16",3,1))', 'Unsupported tp'), ('compute_decode_step_profile(ServingConfig("x","bf16",1,0))', 'batch_size'), ('compute_decode_step_profile(ServingConfig("x","bad",1,1))', 'Unsupported precision'), ('compute_decode_step_profile(ServingConfig("x","bf16",1,1,"bad"))', 'Unsupported interconnect'), ('select_pareto_config([])', 'No HBM-feasible')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
