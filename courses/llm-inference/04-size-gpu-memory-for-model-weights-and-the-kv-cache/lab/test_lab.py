"""Unit and failure-boundary tests for the GPU memory and KV cache calculator."""

from __future__ import annotations

import unittest

from lab import ModelConfig, size_inference_memory, validate_node_deployment


class GpuMemorySizingTests(unittest.TestCase):
    def test_exact_kv_cache_formulas_for_mha_and_gqa(self) -> None:
        mha = ModelConfig(
            name="mha-bf16",
            params_billions=70.0,
            num_layers=80,
            num_query_heads=64,
            num_kv_heads=64,
            head_dim=128,
            weight_bytes=2,
            kv_bytes=2,
        )
        gqa_bf16 = ModelConfig(
            name="gqa-bf16",
            params_billions=70.0,
            num_layers=80,
            num_query_heads=64,
            num_kv_heads=8,
            head_dim=128,
            weight_bytes=2,
            kv_bytes=2,
        )
        gqa_fp8 = ModelConfig(
            name="gqa-fp8",
            params_billions=70.0,
            num_layers=80,
            num_query_heads=64,
            num_kv_heads=8,
            head_dim=128,
            weight_bytes=1,
            kv_bytes=1,
        )

        mha_res = size_inference_memory(mha, seq_len=32768, batch_size=100)
        gqa_bf16_res = size_inference_memory(gqa_bf16, seq_len=32768, batch_size=100)
        gqa_fp8_res = size_inference_memory(gqa_fp8, seq_len=32768, batch_size=100)

        self.assertEqual(mha_res.kv_mib_per_token, 2.5)
        self.assertEqual(mha_res.kv_cache_gib, 8000.0)
        self.assertEqual(gqa_bf16_res.kv_kib_per_token, 320.0)
        self.assertEqual(gqa_bf16_res.kv_cache_gb, 1073.74)
        self.assertEqual(gqa_fp8_res.kv_kib_per_token, 160.0)
        self.assertEqual(gqa_fp8_res.kv_cache_gb, 536.87)
        self.assertTrue(gqa_fp8_res.fits_single_8x_h100_node)

    def test_mha_kv_cache_overflows_8x_h100_node(self) -> None:
        mha = ModelConfig(
            name="llama70b-mha-bf16",
            params_billions=70.0,
            num_layers=80,
            num_query_heads=64,
            num_kv_heads=64,
            head_dim=128,
            weight_bytes=2,
            kv_bytes=2,
        )
        breakdown = size_inference_memory(mha, seq_len=32768, batch_size=100)
        self.assertFalse(breakdown.fits_single_8x_h100_node)
        self.assertGreater(breakdown.min_h100_80gb_gpus, 100)
        with self.assertRaisesRegex(MemoryError, "exceeding 8xH100 node"):
            validate_node_deployment(breakdown, node_vram_gb=640.0)

    def test_ignoring_activation_headroom_causes_prefill_oom(self) -> None:
        gqa_fp8 = ModelConfig(
            name="llama70b-gqa-fp8-tight",
            params_billions=70.0,
            num_layers=80,
            num_query_heads=64,
            num_kv_heads=8,
            head_dim=128,
            weight_bytes=1,
            kv_bytes=1,
        )
        # Decimal GB throughout: the unbudgeted total fits, but the explicit workspace reserve does not.
        unbudgeted = size_inference_memory(
            gqa_fp8,
            seq_len=32768,
            batch_size=104,
            include_activation_headroom=False,
        )
        self.assertLessEqual(unbudgeted.total_required_gb, 640.0)
        with self.assertRaisesRegex(MemoryError, "Prefill OOM: unbudgeted activations"):
            validate_node_deployment(
                unbudgeted, actual_activation_gb=19.47, node_vram_gb=640.0
            )


class DecimalBudgetTests(unittest.TestCase):
    def test_total_budget_adds_decimal_gb(self):
        model = ModelConfig("example", 70, 80, 64, 8, 128)
        result = size_inference_memory(model)
        self.assertEqual(result.total_required_gb, 1233.21)
        self.assertEqual(result.kv_cache_gb, 1073.74)


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('size_inference_memory(ModelConfig("test",1,1,1,1,1),seq_len=0)', 'seq_len and')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
