"""Throughput-latency Pareto optimizer for LLM decode serving configurations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json


@dataclass(frozen=True)
class ServingConfig:
    name: str
    precision: str  # "bf16" or "fp8"
    tp_degree: int  # 1, 2, 4, 8
    batch_size: int
    interconnect: str = "nvlink"  # "nvlink" or "pcie"
    context_len: int = 4096
    params_b: float = 70.0
    num_layers: int = 80
    hidden_dim: int = 8192
    num_kv_heads: int = 8
    head_dim: int = 128
    gpu_mem_gb: float = 80.0


@dataclass(frozen=True)
class DecodeStepProfile:
    name: str
    precision: str
    tp_degree: int
    batch_size: int
    interconnect: str
    fits_hbm: bool
    memory_per_gpu_gb: float
    weight_read_ms: float
    kv_read_ms: float
    compute_ms: float
    allreduce_ms: float
    tpot_ms: float
    total_tokens_per_s: float
    tokens_per_s_per_gpu: float
    bottleneck: str


def compute_decode_step_profile(config: ServingConfig) -> DecodeStepProfile:
    if config.tp_degree not in (1, 2, 4, 8):
        raise ValueError(f"Unsupported tp_degree: {config.tp_degree}")
    if config.batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if config.precision not in ("bf16", "fp8"):
        raise ValueError(f"Unsupported precision: {config.precision}")
    if config.interconnect not in ("nvlink", "pcie"):
        raise ValueError(f"Unsupported interconnect: {config.interconnect}")

    elem_bytes = 2 if config.precision == "bf16" else 1
    eff_tflops = 650.0 if config.precision == "bf16" else 1300.0
    hbm_eff_gb_s = 2680.0  # H100 SXM effective HBM3 stream bandwidth

    weight_bytes_per_gpu = (config.params_b * 1e9 * elem_bytes) / config.tp_degree
    kv_bytes_per_token = (
        2 * config.num_layers * config.num_kv_heads * config.head_dim * elem_bytes
    )
    kv_bytes_per_gpu = (
        config.batch_size * config.context_len * kv_bytes_per_token
    ) / config.tp_degree
    activation_reserve_gb = 3.5

    memory_per_gpu_gb = (
        (weight_bytes_per_gpu + kv_bytes_per_gpu) / 1e9
    ) + activation_reserve_gb
    fits_hbm = memory_per_gpu_gb <= config.gpu_mem_gb

    weight_read_ms = (weight_bytes_per_gpu / (hbm_eff_gb_s * 1e9)) * 1000.0
    kv_read_ms = (kv_bytes_per_gpu / (hbm_eff_gb_s * 1e9)) * 1000.0
    mem_ms = weight_read_ms + kv_read_ms

    linear_flops = 2.0 * config.params_b * 1e9 * config.batch_size
    attn_flops = (
        4.0
        * config.num_layers
        * config.batch_size
        * config.context_len
        * config.hidden_dim
    )
    flops_per_gpu = (linear_flops + attn_flops) / config.tp_degree
    compute_ms = (flops_per_gpu / (eff_tflops * 1e12)) * 1000.0

    kernel_ms = max(mem_ms, compute_ms) + 0.15 * min(mem_ms, compute_ms)

    if config.tp_degree == 1:
        allreduce_ms = 0.0
    else:
        if config.interconnect == "nvlink":
            bw_gb_s = 400.0
            sync_us = 3.5
        else:
            bw_gb_s = 16.0
            sync_us = 25.0
        # 2 all-reduces per transformer layer on BF16 (2-byte) hidden activations
        payload_bytes = config.batch_size * config.hidden_dim * 2
        ring_bytes_per_ar = (
            2.0 * ((config.tp_degree - 1) / config.tp_degree) * payload_bytes
        )
        total_ar_bytes = 2 * config.num_layers * ring_bytes_per_ar
        ar_transfer_ms = (total_ar_bytes / (bw_gb_s * 1e9)) * 1000.0
        ar_sync_ms = (2 * config.num_layers * sync_us) / 1000.0
        allreduce_ms = ar_transfer_ms + ar_sync_ms

    fixed_launch_ms = 0.35
    tpot_ms = kernel_ms + allreduce_ms + fixed_launch_ms

    total_tokens_per_s = config.batch_size / (tpot_ms / 1000.0)
    tokens_per_s_per_gpu = total_tokens_per_s / config.tp_degree

    if allreduce_ms >= max(weight_read_ms, kv_read_ms, compute_ms):
        bottleneck = "allreduce_comm"
    elif compute_ms >= mem_ms:
        bottleneck = "tensor_compute"
    elif kv_read_ms > weight_read_ms:
        bottleneck = "kv_bandwidth"
    else:
        bottleneck = "weight_bandwidth"

    return DecodeStepProfile(
        name=config.name,
        precision=config.precision,
        tp_degree=config.tp_degree,
        batch_size=config.batch_size,
        interconnect=config.interconnect,
        fits_hbm=fits_hbm,
        memory_per_gpu_gb=round(memory_per_gpu_gb, 2),
        weight_read_ms=round(weight_read_ms, 2),
        kv_read_ms=round(kv_read_ms, 2),
        compute_ms=round(compute_ms, 2),
        allreduce_ms=round(allreduce_ms, 2),
        tpot_ms=round(tpot_ms, 2),
        total_tokens_per_s=round(total_tokens_per_s, 1),
        tokens_per_s_per_gpu=round(tokens_per_s_per_gpu, 1),
        bottleneck=bottleneck,
    )


def pareto_frontier(profiles: list[DecodeStepProfile]) -> list[DecodeStepProfile]:
    feasible = [p for p in profiles if p.fits_hbm]
    frontier: list[DecodeStepProfile] = []
    for candidate in feasible:
        dominated = False
        for other in feasible:
            if other is candidate:
                continue
            if (
                other.tpot_ms <= candidate.tpot_ms
                and other.tokens_per_s_per_gpu >= candidate.tokens_per_s_per_gpu
                and (
                    other.tpot_ms < candidate.tpot_ms
                    or other.tokens_per_s_per_gpu > candidate.tokens_per_s_per_gpu
                )
            ):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return sorted(frontier, key=lambda p: (p.tpot_ms, -p.tokens_per_s_per_gpu))


def select_pareto_config(
    configs: list[ServingConfig], sla_tpot_ms: float = 25.0
) -> dict[str, object]:
    profiles = [compute_decode_step_profile(c) for c in configs]
    frontier = pareto_frontier(profiles)
    sla_matches = [p for p in frontier if p.tpot_ms <= sla_tpot_ms]
    if not sla_matches:
        raise ValueError(
            f"No HBM-feasible configuration satisfies tpot_ms <= {sla_tpot_ms}"
        )
    best = max(sla_matches, key=lambda p: (p.tokens_per_s_per_gpu, -p.tpot_ms))
    return {
        "sla_tpot_ms": sla_tpot_ms,
        "selected": asdict(best),
        "pareto_frontier": [asdict(p) for p in frontier],
        "all_profiles": [asdict(p) for p in profiles],
    }


def build_candidate_sweep() -> list[ServingConfig]:
    candidates: list[ServingConfig] = []
    for precision in ("bf16", "fp8"):
        for tp in (1, 2, 4, 8):
            for batch in (1, 8, 16, 32, 64, 96, 128):
                candidates.append(
                    ServingConfig(
                        name=f"{precision}-tp{tp}-b{batch}-nvlink",
                        precision=precision,
                        tp_degree=tp,
                        batch_size=batch,
                        interconnect="nvlink",
                    )
                )
    return candidates


def main() -> None:
    sweep = build_candidate_sweep()
    decision = select_pareto_config(sweep, sla_tpot_ms=25.0)
    pcie_comparison = compute_decode_step_profile(
        ServingConfig(
            name="fp8-tp4-b64-pcie",
            precision="fp8",
            tp_degree=4,
            batch_size=64,
            interconnect="pcie",
        )
    )
    naive_low_latency = compute_decode_step_profile(
        ServingConfig(
            name="bf16-tp8-b1-nvlink",
            precision="bf16",
            tp_degree=8,
            batch_size=1,
            interconnect="nvlink",
        )
    )
    tp2_b64 = compute_decode_step_profile(
        ServingConfig(
            name="fp8-tp2-b64-nvlink",
            precision="fp8",
            tp_degree=2,
            batch_size=64,
            interconnect="nvlink",
        )
    )
    tp2_b128 = compute_decode_step_profile(
        ServingConfig(
            name="fp8-tp2-b128-nvlink",
            precision="fp8",
            tp_degree=2,
            batch_size=128,
            interconnect="nvlink",
        )
    )
    report = {
        "model": "70B-GQA-80L",
        "context_len": 4096,
        "sla_tpot_ms": decision["sla_tpot_ms"],
        "selected": decision["selected"],
        "naive_low_latency_baseline": asdict(naive_low_latency),
        "pcie_tp4_b64_comparison": asdict(pcie_comparison),
        "tp2_batch_scaling": [asdict(tp2_b64), asdict(tp2_b128)],
        "pareto_frontier": decision["pareto_frontier"],
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
