"""GPU memory calculator for model weights, MHA vs GQA KV cache, activations, and fleet sizing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math


@dataclass(frozen=True)
class ModelConfig:
    name: str
    params_billions: float
    num_layers: int
    num_query_heads: int
    num_kv_heads: int
    head_dim: int
    weight_bytes: int = 2
    kv_bytes: int = 2


@dataclass(frozen=True)
class MemoryBreakdown:
    config_name: str
    seq_len: int
    batch_size: int
    weights_gb: float
    kv_bytes_per_token: int
    kv_kib_per_token: float
    kv_mib_per_token: float
    kv_cache_gib: float
    kv_cache_gb: float
    activation_and_cuda_gb: float
    total_required_gb: float
    min_h100_80gb_gpus: int
    min_h200_141gb_gpus: int
    fits_single_8x_h100_node: bool


def size_inference_memory(
    config: ModelConfig,
    seq_len: int = 32768,
    batch_size: int = 100,
    include_activation_headroom: bool = True,
) -> MemoryBreakdown:
    if seq_len <= 0 or batch_size <= 0:
        raise ValueError("seq_len and batch_size must be positive")

    # 1. Model weights: 70B parameters * bytes_per_param (e.g., 140 GB in BF16, 70 GB in FP8).
    weights_gb = round(config.params_billions * config.weight_bytes, 2)

    # 2. Exact KV cache per token: 2 (K and V) * layers * kv_heads * head_dim * kv_bytes.
    kv_bytes_per_token = (
        2 * config.num_layers * config.num_kv_heads * config.head_dim * config.kv_bytes
    )
    kv_kib_per_token = round(kv_bytes_per_token / 1024.0, 2)
    kv_mib_per_token = round(kv_bytes_per_token / (1024.0 * 1024.0), 4)

    total_kv_bytes = kv_bytes_per_token * seq_len * batch_size
    kv_cache_gib = round(total_kv_bytes / (1024.0**3), 2)
    kv_cache_gb = round(total_kv_bytes / 1e9, 2)

    # 3. Prefill activation workspace + CUDA context / NCCL communication buffers.
    if include_activation_headroom:
        prefill_workspace_gb = round(4.5 + 0.00035 * seq_len, 2)
        cuda_and_nccl_gb = 3.5
        activation_and_cuda_gb = round(prefill_workspace_gb + cuda_and_nccl_gb, 2)
    else:
        activation_and_cuda_gb = 0.0

    total_required_gb = round(
        weights_gb + total_kv_bytes / 1e9 + activation_and_cuda_gb, 2
    )

    min_h100 = max(1, int(math.ceil(total_required_gb / 80.0)))
    min_h200 = max(1, int(math.ceil(total_required_gb / 141.0)))

    return MemoryBreakdown(
        config_name=config.name,
        seq_len=seq_len,
        batch_size=batch_size,
        weights_gb=weights_gb,
        kv_bytes_per_token=kv_bytes_per_token,
        kv_kib_per_token=kv_kib_per_token,
        kv_mib_per_token=kv_mib_per_token,
        kv_cache_gib=kv_cache_gib,
        kv_cache_gb=kv_cache_gb,
        activation_and_cuda_gb=activation_and_cuda_gb,
        total_required_gb=total_required_gb,
        min_h100_80gb_gpus=min_h100,
        min_h200_141gb_gpus=min_h200,
        fits_single_8x_h100_node=(min_h100 <= 8),
    )


def validate_node_deployment(
    breakdown: MemoryBreakdown,
    actual_activation_gb: float = 19.47,
    node_vram_gb: float = 640.0,
) -> None:
    if (
        not breakdown.fits_single_8x_h100_node
        or breakdown.total_required_gb > node_vram_gb
    ):
        raise MemoryError(
            f"{breakdown.config_name} requires {breakdown.total_required_gb} GB, exceeding 8xH100 node ({node_vram_gb} GB)"
        )
    if breakdown.activation_and_cuda_gb < actual_activation_gb:
        peak_gb = round(
            breakdown.total_required_gb
            - breakdown.activation_and_cuda_gb
            + actual_activation_gb,
            2,
        )
        if peak_gb > node_vram_gb:
            raise MemoryError(
                f"Prefill OOM: unbudgeted activations ({actual_activation_gb} GB) push peak to {peak_gb} GB > {node_vram_gb} GB"
            )


def main() -> None:
    mha_bf16 = ModelConfig(
        name="llama70b-mha-bf16",
        params_billions=70.0,
        num_layers=80,
        num_query_heads=64,
        num_kv_heads=64,
        head_dim=128,
        weight_bytes=2,
        kv_bytes=2,
    )
    gqa_bf16 = ModelConfig(
        name="llama70b-gqa-bf16",
        params_billions=70.0,
        num_layers=80,
        num_query_heads=64,
        num_kv_heads=8,
        head_dim=128,
        weight_bytes=2,
        kv_bytes=2,
    )
    gqa_fp8 = ModelConfig(
        name="llama70b-gqa-fp8",
        params_billions=70.0,
        num_layers=80,
        num_query_heads=64,
        num_kv_heads=8,
        head_dim=128,
        weight_bytes=1,
        kv_bytes=1,
    )

    mha_res = size_inference_memory(mha_bf16, seq_len=32768, batch_size=100)
    gqa_bf16_res = size_inference_memory(gqa_bf16, seq_len=32768, batch_size=100)
    gqa_fp8_res = size_inference_memory(gqa_fp8, seq_len=32768, batch_size=100)

    report = {
        "experiment": "gpu-memory-sizing-weights-and-kv-cache",
        "workload": {"seq_len": 32768, "concurrent_users": 100},
        "configurations": {
            "mha_bf16_64kv": asdict(mha_res),
            "gqa_bf16_8kv": asdict(gqa_bf16_res),
            "gqa_fp8_8kv": asdict(gqa_fp8_res),
        },
        "reduction_factors": {
            "gqa_vs_mha_kv_ratio": round(
                mha_res.kv_bytes_per_token / gqa_bf16_res.kv_bytes_per_token, 1
            ),
            "gqa_fp8_vs_mha_bf16_kv_ratio": round(
                mha_res.kv_bytes_per_token / gqa_fp8_res.kv_bytes_per_token, 1
            ),
        },
    }
    print(
        json.dumps(
            {
                "execution_mode": "CPU algorithm with controlled inputs; any latency/capacity coefficients are assumptions",
                **report,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
