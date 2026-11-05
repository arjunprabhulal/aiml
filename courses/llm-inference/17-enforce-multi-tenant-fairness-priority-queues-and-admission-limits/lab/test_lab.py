"""Unit and failure-mode tests for multi-tenant fairness, priority queues, and admission limits."""

from __future__ import annotations

import unittest

from lab import (
    InferenceRequest,
    MultiTenantScheduler,
    TenantQuota,
    build_noisy_neighbor_workload,
    simulate_noisy_neighbor,
    summarize_outcomes,
)


class MultiTenantFairnessTest(unittest.TestCase):
    def test_service_token_accounting_weights_decode_higher_than_prefill(self) -> None:
        short_chat = InferenceRequest(
            request_id="chat-1",
            tenant_id="tenant_chat_pro",
            arrival_ms=0,
            prefill_tokens=250,
            decode_tokens=80,
            priority_class="interactive",
        )
        long_rag = InferenceRequest(
            request_id="rag-1",
            tenant_id="tenant_batch_rag",
            arrival_ms=0,
            prefill_tokens=3200,
            decode_tokens=350,
            priority_class="batch",
        )
        self.assertEqual(short_chat.service_tokens(decode_weight=4), 570)
        self.assertEqual(long_rag.service_tokens(decode_weight=4), 4600)
        self.assertGreater(
            long_rag.service_tokens(4) / short_chat.service_tokens(4), 8.0
        )

    def test_service_token_drr_meets_interactive_ttft_slo_under_batch_flood(
        self,
    ) -> None:
        report = simulate_noisy_neighbor()
        protected = report["comparison"]["service_token_drr_with_admission"]
        self.assertLessEqual(protected["interactive_p99_ttft_ms"], 500.0)
        self.assertEqual(protected["tenants"]["tenant_chat_pro"]["shed_429"], 0)
        self.assertEqual(protected["tenants"]["tenant_ide_assist"]["shed_429"], 0)
        self.assertGreater(protected["tenants"]["tenant_batch_rag"]["shed_429"], 0)

    def test_request_count_fairness_lets_long_prompts_starve_short_chats(self) -> None:
        quotas, workload = build_noisy_neighbor_workload()
        naive = MultiTenantScheduler(
            quotas,
            scheduling_mode="request_count_fifo",
            enable_admission_control=False,
        )
        protected = MultiTenantScheduler(
            quotas,
            scheduling_mode="service_token_drr",
            enable_admission_control=True,
        )
        naive_summary = summarize_outcomes(naive.run_trace(workload))
        protected_summary = summarize_outcomes(protected.run_trace(workload))

        # Under 1-for-1 request-count scheduling, 4,600-service-token batch jobs block 570-token chats.
        self.assertGreater(naive_summary["interactive_p99_ttft_ms"], 1800.0)
        self.assertLessEqual(protected_summary["interactive_p99_ttft_ms"], 500.0)

    def test_missing_admission_limit_causes_cluster_queue_collapse(self) -> None:
        quotas, workload = build_noisy_neighbor_workload()
        unbounded = MultiTenantScheduler(
            quotas,
            total_kv_blocks=1024,
            scheduling_mode="request_count_fifo",
            enable_admission_control=False,
        )
        guarded = MultiTenantScheduler(
            quotas,
            total_kv_blocks=1024,
            interactive_kv_watermark=0.90,
            batch_kv_watermark=0.65,
            scheduling_mode="service_token_drr",
            enable_admission_control=True,
        )
        unbounded_summary = summarize_outcomes(unbounded.run_trace(workload))
        guarded_summary = summarize_outcomes(guarded.run_trace(workload))

        # Without KV watermark shedding, peak KV occupancy exceeds 1.0 (OOM/preemption thrash).
        self.assertGreater(unbounded_summary["peak_kv_occupancy_ratio"], 1.0)
        self.assertLessEqual(guarded_summary["peak_kv_occupancy_ratio"], 0.90)
        self.assertGreater(guarded_summary["shed_429_requests"], 0)


class ServiceTimeAccountingTests(unittest.TestCase):
    def test_batch_service_is_not_discarded_after_one_slice(self):
        quota = TenantQuota("tenant", 1, 100000, 100000, "batch")
        requests = [
            InferenceRequest("a", "tenant", 0, 4800, 300, "batch"),
            InferenceRequest("b", "tenant", 0, 4800, 300, "batch"),
        ]
        scheduler = MultiTenantScheduler(
            [quota],
            total_kv_blocks=100000,
            enable_admission_control=False,
            cluster_service_tokens_per_ms=30,
        )
        outcomes = scheduler.run_trace(requests)
        self.assertEqual(len(outcomes), 2)
        self.assertGreaterEqual(outcomes[1].queue_wait_ms, 200)


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('TenantQuota("",1,1,1)', 'tenant_id'), ('TenantQuota("x",0,1,1)', 'weight must'), ('TenantQuota("x",1,0,1)', 'token quotas'), ('InferenceRequest("x","x",0,1,1,"interactive").service_tokens(0)', 'decode_weight'), ('MultiTenantScheduler([])', 'At least one'), ('MultiTenantScheduler([TenantQuota("x",1,1,1)],batch_kv_watermark=1,interactive_kv_watermark=0.5)', 'Watermarks must')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
