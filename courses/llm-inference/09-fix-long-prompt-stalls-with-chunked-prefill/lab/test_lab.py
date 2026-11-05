from __future__ import annotations

import unittest

from lab import (
    ChunkedPrefillScheduler,
    InferenceRequest,
    build_default_workload,
    simulate_long_prompt_arrival,
)


class TestChunkedPrefillLab(unittest.TestCase):
    def test_monolithic_100k_prefill_stalls_active_decodes(self) -> None:
        workload = build_default_workload()
        scheduler = ChunkedPrefillScheduler(
            mode="monolithic", token_budget=2048, tpot_slo_ms=50.0
        )
        result = scheduler.run(workload)
        self.assertFalse(result["tpot_slo_met"])
        self.assertGreater(result["max_itl_ms"], 1000.0)

    def test_oversized_chunk_budget_violates_tpot_slo(self) -> None:
        workload = build_default_workload()
        scheduler = ChunkedPrefillScheduler(
            mode="chunked", token_budget=8192, tpot_slo_ms=50.0
        )
        result = scheduler.run(workload)
        self.assertFalse(result["tpot_slo_met"])
        self.assertGreater(result["max_itl_ms"], 50.0)

    def test_decode_reservation_exceeding_token_budget_raises(self) -> None:
        workload = build_default_workload()
        scheduler = ChunkedPrefillScheduler(
            mode="chunked", token_budget=2, tpot_slo_ms=50.0
        )
        with self.assertRaises(ValueError):
            scheduler.run(workload)

    def test_chunked_2048_meets_tpot_slo_and_completes_all_requests(self) -> None:
        report = simulate_long_prompt_arrival(token_budget=2048, tpot_slo_ms=50.0)
        chunked = report["chunked_2048"]
        self.assertTrue(chunked["tpot_slo_met"])
        self.assertLessEqual(chunked["max_itl_ms"], 50.0)
        self.assertEqual(chunked["requests"]["doc-100k"]["generated_tokens"], 8)
        self.assertEqual(chunked["requests"]["chat-1"]["generated_tokens"], 60)

    def test_prefill_progress_exact_token_accounting(self) -> None:
        reqs = [
            InferenceRequest(
                request_id="chat-1",
                prompt_tokens=128,
                max_new_tokens=5,
                prefilled_tokens=128,
                generated_tokens=1,
                decode_step_timestamps_ms=[0.0],
            ),
            InferenceRequest(request_id="doc-5k", prompt_tokens=5000, max_new_tokens=3),
        ]
        res = ChunkedPrefillScheduler(
            mode="chunked", token_budget=1024, tpot_slo_ms=50.0
        ).run(reqs)
        self.assertEqual(res["requests"]["doc-5k"]["prompt_tokens"], 5000)
        self.assertEqual(res["requests"]["doc-5k"]["generated_tokens"], 3)


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('estimate_step_latency_ms(-1,[])', 'decode_tokens'), ('ChunkedPrefillScheduler(mode="bad")', 'Unsupported mode'), ('ChunkedPrefillScheduler(token_budget=0)', 'token_budget')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
