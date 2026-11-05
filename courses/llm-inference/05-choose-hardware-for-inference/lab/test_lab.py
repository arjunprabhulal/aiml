"""Unit and failure-boundary tests for the GPU roofline and selector lab."""

from __future__ import annotations

import unittest

from lab import (
    GPU_SPECS,
    GpuSpec,
    ModelWorkload,
    build_report,
    compute_decode_step_metrics,
    compute_prefill_metrics,
    evaluate_gpu_for_workload,
)


class GpuRooflineTest(unittest.TestCase):
    def test_ridge_points_reflect_compute_to_bandwidth_ratio(self) -> None:
        self.assertAlmostEqual(
            GPU_SPECS["example-small"].ridge_point_flops_per_byte, 418.98, places=2
        )
        self.assertAlmostEqual(
            GPU_SPECS["example-fast"].ridge_point_flops_per_byte, 295.22, places=2
        )
        self.assertAlmostEqual(
            GPU_SPECS["example-large-memory"].ridge_point_flops_per_byte,
            206.04,
            places=2,
        )
        self.assertAlmostEqual(
            GPU_SPECS["example-wide-bandwidth"].ridge_point_flops_per_byte,
            281.25,
            places=2,
        )

    def test_prefill_is_compute_bound_while_small_batch_decode_is_bandwidth_bound(
        self,
    ) -> None:
        workload = ModelWorkload(
            model_name="Llama-3-8B-BF16",
            active_params_b=8.0,
            bytes_per_param=2,
            kv_bytes_per_token=131072,
            prompt_tokens=2048,
            output_tokens=256,
            batch_size=8,
        )
        h100 = GPU_SPECS["example-fast"]
        prefill = compute_prefill_metrics(h100, workload)
        decode = compute_decode_step_metrics(h100, workload)
        self.assertEqual(prefill.regime, "compute-bound")
        self.assertGreater(
            prefill.operational_intensity, h100.ridge_point_flops_per_byte
        )
        self.assertEqual(decode.regime, "bandwidth-bound")
        self.assertLess(decode.operational_intensity, 20.0)

    def test_buying_peak_tflops_for_small_batch_decode_wastes_budget(self) -> None:
        """Doubling peak TFLOPS without raising HBM bandwidth leaves small-batch decode TPOT unchanged."""
        workload = ModelWorkload(
            model_name="Llama-3-8B-BF16",
            active_params_b=8.0,
            bytes_per_param=2,
            kv_bytes_per_token=131072,
            prompt_tokens=2048,
            output_tokens=256,
            batch_size=4,
        )
        h100 = GPU_SPECS["example-fast"]
        # Hypothetical chip with 2x BF16 TFLOPS but identical 3,350 GB/s HBM bandwidth
        double_compute_same_bw = GpuSpec(
            name="Hypothetical-2x-TFLOPS",
            memory_gb=80.0,
            bandwidth_gbps=h100.bandwidth_gbps,
            bf16_tflops=h100.bf16_tflops * 2.0,
            hourly_cost_usd=h100.hourly_cost_usd * 1.5,
        )
        h100_eval = evaluate_gpu_for_workload(h100, workload)
        hyp_eval = evaluate_gpu_for_workload(double_compute_same_bw, workload)
        self.assertEqual(h100_eval["tpot_ms"], hyp_eval["tpot_ms"])
        self.assertGreater(
            GPU_SPECS["example-large-memory"].bandwidth_gbps,
            h100.bandwidth_gbps,
        )
        h200_eval = evaluate_gpu_for_workload(
            GPU_SPECS["example-large-memory"], workload
        )
        self.assertLess(h200_eval["tpot_ms"], h100_eval["tpot_ms"])

    def test_insufficient_vram_rejects_single_card_fit(self) -> None:
        """A workload whose weights + KV cache + activations exceed GPU VRAM raises ValueError."""
        large_workload = ModelWorkload(
            model_name="Qwen-32B-BF16-LongContext",
            active_params_b=32.0,
            bytes_per_param=2,
            kv_bytes_per_token=262144,
            prompt_tokens=4096,
            output_tokens=512,
            batch_size=16,
        )
        with self.assertRaisesRegex(ValueError, "below required"):
            evaluate_gpu_for_workload(
                GPU_SPECS["example-small"], large_workload, require_single_card_fit=True
            )
        with self.assertRaisesRegex(ValueError, "below required"):
            evaluate_gpu_for_workload(
                GPU_SPECS["example-fast"], large_workload, require_single_card_fit=True
            )
        h200_fit = evaluate_gpu_for_workload(
            GPU_SPECS["example-large-memory"],
            large_workload,
            require_single_card_fit=True,
        )
        self.assertTrue(h200_fit["fits_single_gpu"])

    def test_report_structure_is_deterministic(self) -> None:
        report = build_report()
        self.assertEqual(len(report["gpu_catalog"]), 4)
        self.assertEqual(len(report["llama_8b_batch8"]), 4)
        self.assertEqual(len(report["h100_batch_sweep"]), 5)


class RooflineUnitsTests(unittest.TestCase):
    def test_first_output_token_has_no_decode_interval(self):
        from lab import GpuSpec, ModelWorkload, evaluate_gpu_for_workload

        gpu = GpuSpec("test", 100, 100, 10, 2)
        work = ModelWorkload("test", 0.01, 2, 16, 8, 1, 1)
        result = evaluate_gpu_for_workload(gpu, work)
        expected = 1000 / result["prefill"]["latency_ms"]
        self.assertAlmostEqual(result["end_to_end_tokens_per_sec"], expected, delta=0.2)
        self.assertAlmostEqual(
            result["tokens_per_dollar"],
            result["end_to_end_tokens_per_sec"] * 1800,
            delta=10,
        )


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('ModelWorkload("test",0,2,2,1,1,1).validate()', 'Model parameter'), ('ModelWorkload("test",1,2,2,0,1,1).validate()', 'Prompt tokens')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
