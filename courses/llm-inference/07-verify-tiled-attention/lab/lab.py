"""Compare dense and tiled CPU attention with online softmax; device traffic is not measured."""

from __future__ import annotations

import json
import math
import random


def make_qkv(
    seq_len: int,
    head_dim: int,
    seed: int = 42,
) -> tuple[list[list[float]], list[list[float]], list[list[float]]]:
    rng = random.Random(seed)
    q = [[rng.uniform(-0.8, 0.8) for _ in range(head_dim)] for _ in range(seq_len)]
    k = [[rng.uniform(-0.8, 0.8) for _ in range(head_dim)] for _ in range(seq_len)]
    v = [[rng.uniform(-0.8, 0.8) for _ in range(head_dim)] for _ in range(seq_len)]
    return q, k, v


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def standard_attention(
    q: list[list[float]],
    k: list[list[float]],
    v: list[list[float]],
    causal: bool = True,
    subtract_max: bool = True,
) -> tuple[list[list[float]], dict[str, int]]:
    """Materializes the full N x N score and probability matrices before multiplying by V."""
    n = len(q)
    d = len(q[0])
    scale = 1.0 / math.sqrt(d)

    # 1. Compute S = Q K^T * scale (materialized N x N in HBM)
    scores: list[list[float]] = []
    for i in range(n):
        limit = (i + 1) if causal else n
        row_scores = [dot(q[i], k[j]) * scale for j in range(limit)]
        scores.append(row_scores)

    # 2. Row-wise softmax P = softmax(S) (materialized N x N in HBM)
    probs: list[list[float]] = []
    for row_scores in scores:
        m = max(row_scores) if subtract_max else 0.0
        exps = [math.exp(s - m) for s in row_scores]
        denom = sum(exps)
        probs.append([e / denom for e in exps])

    # 3. Output O = P V
    out: list[list[float]] = []
    for i in range(n):
        row_out = [0.0] * d
        for j, p_ij in enumerate(probs[i]):
            for col in range(d):
                row_out[col] += p_ij * v[j][col]
        out.append(row_out)

    materialized_nxn_elements = sum(len(r) for r in scores) + sum(len(r) for r in probs)
    return out, {"materialized_nxn_elements": materialized_nxn_elements}


def tiled_flash_attention(
    q: list[list[float]],
    k: list[list[float]],
    v: list[list[float]],
    block_q: int = 16,
    block_kv: int = 16,
    causal: bool = True,
    rescale_previous_acc: bool = True,
) -> tuple[list[list[float]], dict[str, int]]:
    """Tiles Q, K, and V in SRAM using online softmax without materializing N x N in HBM."""
    n = len(q)
    d = len(q[0])
    scale = 1.0 / math.sqrt(d)
    out: list[list[float]] = [[0.0] * d for _ in range(n)]
    sram_tile_score_peak = block_q * block_kv
    tiles_visited = 0

    for q_start in range(0, n, block_q):
        q_end = min(q_start + block_q, n)
        q_rows = q_end - q_start
        running_max = [-math.inf] * q_rows
        running_sum = [0.0] * q_rows
        output_acc = [[0.0] * d for _ in range(q_rows)]

        for kv_start in range(0, n, block_kv):
            if causal and kv_start >= q_end:
                break
            kv_end = min(kv_start + block_kv, n)
            tiles_visited += 1

            for local_i in range(q_rows):
                global_i = q_start + local_i
                valid_kv_indices = [
                    j for j in range(kv_start, kv_end) if (not causal or j <= global_i)
                ]
                if not valid_kv_indices:
                    continue

                tile_scores = [dot(q[global_i], k[j]) * scale for j in valid_kv_indices]
                tile_max = max(tile_scores)
                prev_max = running_max[local_i]
                new_max = max(prev_max, tile_max)

                # Rescale factor for previous running_sum and output_acc
                alpha = math.exp(prev_max - new_max) if prev_max > -math.inf else 0.0
                tile_exps = [math.exp(s - new_max) for s in tile_scores]
                tile_sum = sum(tile_exps)

                running_sum[local_i] = running_sum[local_i] * alpha + tile_sum
                acc_scale = alpha if rescale_previous_acc else 1.0
                for col in range(d):
                    acc_val = output_acc[local_i][col] * acc_scale
                    for exp_val, j in zip(tile_exps, valid_kv_indices):
                        acc_val += exp_val * v[j][col]
                    output_acc[local_i][col] = acc_val

                running_max[local_i] = new_max

        for local_i in range(q_rows):
            global_i = q_start + local_i
            inv_sum = 1.0 / running_sum[local_i]
            out[global_i] = [val * inv_sum for val in output_acc[local_i]]

    return out, {
        "materialized_nxn_elements": 0,
        "max_sram_score_tile_elements": sram_tile_score_peak,
        "tiles_visited": tiles_visited,
    }


def max_abs_diff(a: list[list[float]], b: list[list[float]]) -> float:
    return max(abs(x - y) for row_a, row_b in zip(a, b) for x, y in zip(row_a, row_b))


def estimate_hbm_bytes(
    seq_len: int,
    num_heads: int = 32,
    head_dim: int = 128,
    bytes_per_elem: int = 2,
    block_q: int = 128,
    block_kv: int = 128,
) -> dict[str, object]:
    """Compare single-layer multi-head attention HBM traffic for standard vs FlashAttention."""
    qkv_o_bytes = 4 * num_heads * seq_len * head_dim * bytes_per_elem
    # Standard attention writes S (N x N), reads S, writes P (N x N), reads P across all heads
    attention_matrix_rw_bytes = 4 * num_heads * (seq_len * seq_len) * bytes_per_elem
    standard_total_bytes = qkv_o_bytes + attention_matrix_rw_bytes

    # Logical tensor accesses for causal outer-Q tiling, assuming no inter-block cache reuse.
    # Hardware HBM traffic requires profiling; this is an access-count model.
    num_q_blocks = math.ceil(seq_len / block_q)
    kv_rows_read = sum(
        min(seq_len, start + block_q) for start in range(0, seq_len, block_q)
    )
    tiled_bytes = (
        2 * num_heads * seq_len * head_dim + 2 * num_heads * kv_rows_read * head_dim
    ) * bytes_per_elem
    return {
        "seq_len": seq_len,
        "num_heads": num_heads,
        "head_dim": head_dim,
        "standard_qkv_o_mb": round(qkv_o_bytes / 1e6, 2),
        "standard_nxn_matrix_hbm_mb": round(attention_matrix_rw_bytes / 1e6, 2),
        "standard_total_hbm_mb": round(standard_total_bytes / 1e6, 2),
        "tiled_logical_access_mb_no_cache_reuse": round(tiled_bytes / 1e6, 2),
        "qkvo_compulsory_bytes_mb": round(qkv_o_bytes / 1e6, 2),
        "num_q_blocks": num_q_blocks,
        "accounting": "logical accesses, not measured HBM traffic; dense baseline and causal tiled loop differ in work",
    }


def build_report() -> dict[str, object]:
    q, k, v = make_qkv(seq_len=64, head_dim=16, seed=42)
    std_out, std_meta = standard_attention(q, k, v, causal=True)
    flash_out, flash_meta = tiled_flash_attention(
        q, k, v, block_q=16, block_kv=16, causal=True
    )
    diff = max_abs_diff(std_out, flash_out)

    hbm_sweep = [
        estimate_hbm_bytes(seq_len=n, num_heads=32, head_dim=128, bytes_per_elem=2)
        for n in (1024, 4096, 16384, 32768)
    ]

    return {
        "equivalence_check": {
            "seq_len": 64,
            "head_dim": 16,
            "block_q": 16,
            "block_kv": 16,
            "max_abs_diff": float(f"{diff:.3e}"),
            "standard_materialized_elements": std_meta["materialized_nxn_elements"],
            "flash_materialized_hbm_elements": flash_meta["materialized_nxn_elements"],
            "flash_sram_tile_elements": flash_meta["max_sram_score_tile_elements"],
            "flash_tiles_visited": flash_meta["tiles_visited"],
            "sample_row0_first4": [round(x, 6) for x in flash_out[0][:4]],
            "sample_last_row_first4": [round(x, 6) for x in flash_out[-1][:4]],
        },
        "hbm_traffic_sweep": hbm_sweep,
    }


def main() -> None:
    print(
        json.dumps(
            {
                "execution_mode": "CPU algorithm with controlled inputs; any latency/capacity coefficients are assumptions",
                **build_report(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
