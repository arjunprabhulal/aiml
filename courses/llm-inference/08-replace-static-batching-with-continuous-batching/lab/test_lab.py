"""Unit and failure-boundary tests for static vs continuous batching."""

from __future__ import annotations

import unittest

from lab import (
    ContinuousBatchScheduler,
    InferenceRequest,
    StaticBatchRunner,
    compare_batching_modes,
)


class ContinuousBatchingTest(unittest.TestCase):
    def test_continuous_batching_eliminates_padding_and_improves_throughput(
        self,
    ) -> None:
        report = compare_batching_modes()
        static = report["static_batching"]
        cont = report["continuous_batching"]
        self.assertGreater(static["wasted_pad_token_steps"], 2500)
        self.assertEqual(cont["wasted_pad_token_steps"], 0)
        self.assertGreater(
            cont["effective_tokens_per_sec"], static["effective_tokens_per_sec"] * 1.8
        )
        self.assertLess(
            cont["avg_short_request_e2e_ms"], static["avg_short_request_e2e_ms"]
        )

    def test_single_long_request_pins_entire_static_batch(self) -> None:
        """In static batching, batch slots stay reserved until the longest output; short responses can still finish sooner."""
        requests = [
            InferenceRequest(
                "long-outlier", arrival_ms=0.0, prompt_tokens=128, output_tokens=512
            ),
            InferenceRequest(
                "short-1", arrival_ms=0.0, prompt_tokens=128, output_tokens=32
            ),
            InferenceRequest(
                "short-2", arrival_ms=0.0, prompt_tokens=128, output_tokens=32
            ),
            InferenceRequest(
                "short-3", arrival_ms=0.0, prompt_tokens=128, output_tokens=32
            ),
            InferenceRequest(
                "queued-next", arrival_ms=50.0, prompt_tokens=128, output_tokens=32
            ),
        ]
        static_res = StaticBatchRunner(max_batch_size=4).run(requests)
        cont_res = ContinuousBatchScheduler(max_batch_size=4, max_kv_tokens=4096).run(
            requests
        )

        static_by_id = {r["req_id"]: r for r in static_res["per_request"]}
        cont_by_id = {r["req_id"]: r for r in cont_res["per_request"]}

        # Short responses can stream out early even while a static batch retains their slots.
        self.assertLess(
            static_by_id["short-1"]["e2e_latency_ms"],
            static_by_id["long-outlier"]["e2e_latency_ms"],
        )
        self.assertAlmostEqual(
            static_by_id["short-1"]["e2e_latency_ms"],
            cont_by_id["short-1"]["e2e_latency_ms"],
            places=3,
        )
        # And queued-next joins right after short-1 exits instead of waiting for 512 steps
        self.assertLess(
            cont_by_id["queued-next"]["queue_delay_ms"],
            static_by_id["queued-next"]["queue_delay_ms"] * 0.12,
        )

    def test_unbounded_continuous_batch_exceeds_kv_capacity(self) -> None:
        """Admitting requests without checking the KV cache token budget overflows GPU memory during decode."""
        heavy_requests = [
            InferenceRequest(
                f"req-{i}", arrival_ms=0.0, prompt_tokens=600, output_tokens=200
            )
            for i in range(4)
        ]
        # Total KV needed for 4 active requests = 4 * 800 = 3200 > max_kv_tokens=2000
        unsafe_scheduler = ContinuousBatchScheduler(
            max_batch_size=4,
            max_kv_tokens=2000,
            enforce_kv_limit=False,
        )
        with self.assertRaises(MemoryError):
            unsafe_scheduler.run(heavy_requests)

        # With enforce_kv_limit=True, the scheduler bounds active concurrency so peak KV stays <= 2000
        safe_scheduler = ContinuousBatchScheduler(
            max_batch_size=4,
            max_kv_tokens=2000,
            enforce_kv_limit=True,
        )
        res = safe_scheduler.run(heavy_requests)
        self.assertEqual(res["requests_completed"], 4)
        self.assertLessEqual(res["peak_kv_tokens"], 2000)


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('ContinuousBatchScheduler().run([])', 'Requests and'), ('ContinuousBatchScheduler().run([InferenceRequest("x",0,0,1)])', 'Invalid request'), ('ContinuousBatchScheduler(max_kv_tokens=1).run([InferenceRequest("x",0,2,1)])', 'exceeds total KV')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
