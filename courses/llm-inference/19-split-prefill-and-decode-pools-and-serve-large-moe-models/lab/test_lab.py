"""Unit and failure-mode tests for disaggregated prefill/decode pools and large MoE serving."""

from __future__ import annotations

import unittest

from lab import (
    DisaggregationWorkload,
    ModelKVSpec,
    evaluate_moe_parallelism,
    evaluate_pd_disaggregation,
)


class DisaggregationAndMoETest(unittest.TestCase):
    def test_exact_kv_cache_transfer_bytes_and_rdma_pd_disaggregation(self) -> None:
        spec = ModelKVSpec(layers=80, kv_heads=8, head_dim=128, bytes_per_element=2)
        # 2 (K+V) * 80 * 8 * 128 * 2 = 327,680 bytes/token; for 4,096 tokens = 1,342,177,280 bytes (1,280 MB).
        self.assertEqual(spec.kv_bytes_per_token(), 327_680)
        self.assertEqual(spec.kv_transfer_bytes(4096), 1_342_177_280)

        rdma = evaluate_pd_disaggregation(
            spec, DisaggregationWorkload(), "rdma_roce_50gbs"
        )
        self.assertEqual(rdma["kv_transfer_mib"], 1280.0)
        self.assertTrue(rdma["disaggregated"]["ttft_improved_vs_colocated"])
        self.assertLess(
            rdma["disaggregated"]["p99_tpot_ms"],
            rdma["colocated"]["p99_tpot_ms"],
        )

    def test_slow_network_kv_transfer_erases_disaggregation_ttft_gain(self) -> None:
        spec = ModelKVSpec()
        workload = DisaggregationWorkload(prompt_tokens=4096)
        rdma = evaluate_pd_disaggregation(spec, workload, "rdma_roce_50gbs")
        tcp = evaluate_pd_disaggregation(spec, workload, "tcp_ethernet_12_5gbs")

        # Over 12.5 GB/s TCP without RDMA pipelining, transferring 1.28 GB of KV cache takes >120ms,
        # pushing disaggregated TTFT above the co-located baseline.
        self.assertTrue(rdma["disaggregated"]["ttft_improved_vs_colocated"])
        self.assertFalse(tcp["disaggregated"]["ttft_improved_vs_colocated"])
        self.assertGreater(
            tcp["disaggregated"]["p99_ttft_ms"],
            tcp["colocated"]["p99_ttft_ms"],
        )

    def test_hybrid_tp_ep_outperforms_pure_tp16_on_large_moe(self) -> None:
        pure_tp = evaluate_moe_parallelism(strategy="pure_tp16")
        hybrid_ep = evaluate_moe_parallelism(strategy="hybrid_tp2_ep8")
        self.assertLess(hybrid_ep["step_tpot_ms"], pure_tp["step_tpot_ms"])
        self.assertGreater(
            hybrid_ep["cluster_decode_tokens_per_sec"],
            pure_tp["cluster_decode_tokens_per_sec"],
        )

    def test_skewed_expert_routing_creates_ep_straggler_bottleneck(self) -> None:
        unmitigated = evaluate_moe_parallelism(
            strategy="hybrid_tp2_ep8",
            hot_expert_skew_factor=2.6,
            enable_redundant_hot_experts=False,
        )
        mitigated = evaluate_moe_parallelism(
            strategy="hybrid_tp2_ep8",
            hot_expert_skew_factor=2.6,
            enable_redundant_hot_experts=True,
        )
        # Without redundant hot-expert replication, 2.6x routing skew inflates step TPOT by >70%.
        self.assertGreater(unmitigated["step_tpot_ms"], mitigated["step_tpot_ms"] * 1.5)
        self.assertGreater(
            mitigated["cluster_decode_tokens_per_sec"],
            unmitigated["cluster_decode_tokens_per_sec"] * 1.5,
        )


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('evaluate_moe_parallelism(num_gpus=0)', 'num_gpus'), ('evaluate_moe_parallelism(hot_expert_skew_factor=0.5)', 'skew_factor'), ('ModelKVSpec().kv_transfer_bytes(0)', 'prompt_tokens')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
