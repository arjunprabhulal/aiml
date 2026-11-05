"""Unit and failure-boundary tests for standard vs tiled FlashAttention."""

from __future__ import annotations

import unittest

from lab import (
    estimate_hbm_bytes,
    make_qkv,
    max_abs_diff,
    standard_attention,
    tiled_flash_attention,
)


class FlashAttentionTest(unittest.TestCase):
    def test_tiled_flash_attention_matches_standard_attention_across_tile_sizes(
        self,
    ) -> None:
        q, k, v = make_qkv(seq_len=64, head_dim=16, seed=7)
        std_out, _ = standard_attention(q, k, v, causal=True)
        for bq, bkv in ((8, 8), (16, 16), (13, 19), (32, 8)):
            flash_out, meta = tiled_flash_attention(
                q, k, v, block_q=bq, block_kv=bkv, causal=True
            )
            self.assertLess(max_abs_diff(std_out, flash_out), 1e-12)
            self.assertEqual(meta["materialized_nxn_elements"], 0)

    def test_access_count_includes_repeated_kv_reads(self) -> None:
        small = estimate_hbm_bytes(seq_len=4096)
        large = estimate_hbm_bytes(seq_len=32768)
        self.assertGreater(
            small["tiled_logical_access_mb_no_cache_reuse"],
            small["qkvo_compulsory_bytes_mb"],
        )
        self.assertGreater(
            large["tiled_logical_access_mb_no_cache_reuse"]
            / small["tiled_logical_access_mb_no_cache_reuse"],
            8,
        )
        self.assertNotIn("hbm_traffic_reduction_x", large)

    def test_naive_softmax_overflows_without_max_shift(self) -> None:
        """Large attention logits overflow exp() when subtract_max=False, whereas online max shift stays finite."""
        q = [[500.0, 500.0], [500.0, 500.0]]
        k = [[1.0, 1.0], [2.0, 2.0]]
        v = [[1.0, 0.0], [0.0, 1.0]]
        with self.assertRaises(OverflowError):
            standard_attention(q, k, v, causal=False, subtract_max=False)
        safe_std, _ = standard_attention(q, k, v, causal=False, subtract_max=True)
        safe_flash, _ = tiled_flash_attention(
            q, k, v, block_q=1, block_kv=1, causal=False
        )
        self.assertLess(max_abs_diff(safe_std, safe_flash), 1e-12)

    def test_forgetting_output_rescaling_across_tiles_corrupts_attention(self) -> None:
        """Omitting the exp(prev_max - new_max) rescaling on output_acc produces wrong attention outputs."""
        q, k, v = make_qkv(seq_len=32, head_dim=8, seed=99)
        # Emphasize a late key so running_max increases on a subsequent KV tile
        k[-1] = [4.0] * 8
        std_out, _ = standard_attention(q, k, v, causal=True)
        correct_flash, _ = tiled_flash_attention(
            q, k, v, block_q=8, block_kv=8, causal=True, rescale_previous_acc=True
        )
        buggy_flash, _ = tiled_flash_attention(
            q, k, v, block_q=8, block_kv=8, causal=True, rescale_previous_acc=False
        )
        self.assertLess(max_abs_diff(std_out, correct_flash), 1e-12)
        self.assertGreater(max_abs_diff(std_out, buggy_flash), 0.1)


if __name__ == "__main__":
    unittest.main()
