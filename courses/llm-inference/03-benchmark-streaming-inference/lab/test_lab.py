"""Checks the scheduler model, not any serving engine's performance."""

import unittest
from lab import (
    SCENARIO_PROFILES,
    EngineProfile,
    WorkloadRequest,
    build_agent_trace,
    evaluate_engine_benchmark,
)


class BenchmarkTests(unittest.TestCase):
    def test_closed_loop_benchmark_hides_queueing(self):
        # A single closed-loop client waits for the WHOLE prior response.
        profile = EngineProfile("fixed", 1, 0, 10, 0, 1)
        trace = [WorkloadRequest("a", 0, 0, 7, 3), WorkloadRequest("b", 0, 0, 7, 3)]
        result = evaluate_engine_benchmark(trace, profile, closed_loop=True)
        self.assertEqual(result.duration_s, 0.06)  # 2 * (10 prefill + 20 decode)
        self.assertEqual(result.ttft_p99_ms, 10)
        opened = evaluate_engine_benchmark(trace, profile)
        self.assertEqual(opened.ttft_p99_ms, 40)  # second arrival waits for admission

    def test_throughput_without_slo_masks_tail_violations(self):
        trace = build_agent_trace()
        result = evaluate_engine_benchmark(
            trace, SCENARIO_PROFILES["baseline"], tpot_slo_ms=1
        )
        self.assertGreater(result.raw_output_tokens_per_s, 0)
        self.assertEqual(result.slo_goodput_rps, 0)

    def test_admission_capacity_changes_queue_wait(self):
        trace = [WorkloadRequest(str(i), 0, 0, 7, 3) for i in range(3)]
        one = evaluate_engine_benchmark(trace, EngineProfile("one", 1, 0, 10, 0, 1))
        three = evaluate_engine_benchmark(trace, EngineProfile("three", 1, 0, 10, 0, 3))
        self.assertEqual(one.ttft_p99_ms, 70)
        self.assertEqual(three.ttft_p99_ms, 30)

    def test_invalid_capacity_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_engine_benchmark(
                build_agent_trace(), EngineProfile("invalid", 1, 0, 10, 0, 0)
            )


class TransportCompletionTests(unittest.TestCase):
    def test_eof_without_done_is_failed(self):
        import io
        from unittest.mock import patch
        from benchmark import request_one

        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(b'data: {"token":"partial"}\n\n'),
        ):
            result = request_one("http://localhost/generate", "prompt", 24)
        self.assertEqual(result["status"], "failed")
        self.assertIn("completion marker", result["error"])

    def test_complete_stream_requires_done_marker(self):
        import io
        from unittest.mock import patch
        from benchmark import request_one

        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(b'data: {"token":"complete"}\n\ndata: [DONE]\n\n'),
        ):
            result = request_one("http://localhost/generate", "prompt", 24)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "complete")


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('import benchmark\nbenchmark.run("unused",[])', 'Workload, rate'), ('evaluate_engine_benchmark([], EngineProfile("test",1,0,1,0,1))', 'Workload trace')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
