"""Disaggregated prefill/decode pool sizer and large Mixture-of-Experts (MoE) parallelism analyzer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from typing import Literal

InterconnectKind = Literal["nvlink_900gbs", "rdma_roce_50gbs", "tcp_ethernet_12_5gbs"]

INTERCONNECT_BANDWIDTH_GBS: dict[InterconnectKind, float] = {
    "nvlink_900gbs": 900.0,
    "rdma_roce_50gbs": 50.0,
    "tcp_ethernet_12_5gbs": 12.5,
}


@dataclass(frozen=True)
class ModelKVSpec:
    name: str = "Llama-3-70B-GQA"
    layers: int = 80
    kv_heads: int = 8
    head_dim: int = 128
    bytes_per_element: int = 2  # BF16 = 2 bytes, FP8 = 1 byte

    def kv_bytes_per_token(self) -> int:
        return 2 * self.layers * self.kv_heads * self.head_dim * self.bytes_per_element

    def kv_transfer_bytes(self, prompt_tokens: int) -> int:
        if prompt_tokens <= 0:
            raise ValueError("prompt_tokens must be positive")
        return self.kv_bytes_per_token() * prompt_tokens


@dataclass(frozen=True)
class DisaggregationWorkload:
    prompt_tokens: int = 4096
    decode_tokens: int = 256
    target_qps: float = 36.0
    prefill_tokens_per_sec_per_gpu: float = 18_500.0
    decode_tokens_per_sec_per_gpu: float = 1_600.0
    colocated_interference_tpot_penalty_ms: float = 29.5
    base_decode_tpot_ms: float = 21.0


def evaluate_pd_disaggregation(
    kv_spec: ModelKVSpec = ModelKVSpec(),
    workload: DisaggregationWorkload = DisaggregationWorkload(),
    interconnect: InterconnectKind = "rdma_roce_50gbs",
) -> dict[str, object]:
    """Compares co-located continuous batching against disaggregated Prefill (P) and Decode (D) GPU pools."""
    kv_bytes = kv_spec.kv_transfer_bytes(workload.prompt_tokens)
    kv_megabytes = round(kv_bytes / (1024 * 1024), 2)
    bw_gbs = INTERCONNECT_BANDWIDTH_GBS[interconnect]
    # Scenario assumptions only: these link efficiencies are not measured.
    link_efficiency = 0.52 if interconnect == "tcp_ethernet_12_5gbs" else 0.82
    effective_bw_bytes_per_ms = (bw_gbs * 1e9 * link_efficiency) / 1000.0
    kv_transfer_ms = round(kv_bytes / effective_bw_bytes_per_ms, 2)

    prefill_compute_ms = round(
        (workload.prompt_tokens / workload.prefill_tokens_per_sec_per_gpu) * 1000.0, 2
    )
    # In co-located pools, long prefills queue behind mixed decode steps and inject chunk-prefill stalls into TPOT.
    colocated_p99_ttft_ms = round(prefill_compute_ms * 1.48 + 95.0, 2)
    colocated_p99_tpot_ms = round(
        workload.base_decode_tpot_ms + workload.colocated_interference_tpot_penalty_ms,
        2,
    )

    # Scenario assumes partial transfer overlap; no connector was executed.
    # unpipelined TCP waits for full prompt completion and pays host bounce-buffer latency.
    overlap_factor = 0.35 if interconnect != "tcp_ethernet_12_5gbs" else 1.05
    disagg_p99_ttft_ms = round(
        prefill_compute_ms + 32.0 + kv_transfer_ms * overlap_factor, 2
    )
    disagg_p99_tpot_ms = round(workload.base_decode_tpot_ms, 2)

    # Size dedicated P and D GPU pools with 25% headroom.
    prefill_token_rate = workload.target_qps * workload.prompt_tokens
    decode_token_rate = workload.target_qps * workload.decode_tokens
    prefill_gpus = math.ceil(
        (prefill_token_rate / workload.prefill_tokens_per_sec_per_gpu) * 1.25
    )
    decode_gpus = math.ceil(
        (decode_token_rate / workload.decode_tokens_per_sec_per_gpu) * 1.25
    )
    colocated_gpus = math.ceil((prefill_gpus + decode_gpus) * 1.22)

    return {
        "interconnect": interconnect,
        "interconnect_bandwidth_gbs": bw_gbs,
        "prompt_tokens": workload.prompt_tokens,
        "decode_tokens": workload.decode_tokens,
        "kv_bytes_per_token": kv_spec.kv_bytes_per_token(),
        "kv_transfer_mib": kv_megabytes,
        "raw_kv_transfer_ms": kv_transfer_ms,
        "prefill_compute_ms": prefill_compute_ms,
        "colocated": {
            "total_gpus": colocated_gpus,
            "p99_ttft_ms": colocated_p99_ttft_ms,
            "p99_tpot_ms": colocated_p99_tpot_ms,
        },
        "disaggregated": {
            "prefill_gpus": prefill_gpus,
            "decode_gpus": decode_gpus,
            "total_gpus": prefill_gpus + decode_gpus,
            "pd_ratio": f"{prefill_gpus}:{decode_gpus}",
            "p99_ttft_ms": disagg_p99_ttft_ms,
            "p99_tpot_ms": disagg_p99_tpot_ms,
            "ttft_improved_vs_colocated": disagg_p99_ttft_ms < colocated_p99_ttft_ms,
            "tpot_reduction_ms": round(colocated_p99_tpot_ms - disagg_p99_tpot_ms, 2),
        },
    }


@dataclass(frozen=True)
class MoEArchitectureSpec:
    name: str = "hypothetical-moe-scenario"
    total_params_b: float = 671.0
    active_params_b: float = 37.0
    layers: int = 61
    routed_experts: int = 64
    top_k: int = 8
    hidden_dim: int = 7168
    expert_intermediate_dim: int = 2048
    bytes_per_weight: int = 1  # FP8 weights


def evaluate_moe_parallelism(
    moe: MoEArchitectureSpec = MoEArchitectureSpec(),
    *,
    num_gpus: int = 16,
    batch_tokens: int = 512,
    strategy: Literal["pure_tp16", "hybrid_tp2_ep8"] = "hybrid_tp2_ep8",
    hot_expert_skew_factor: float = 1.15,
    enable_redundant_hot_experts: bool = True,
) -> dict[str, object]:
    """Compares Tensor Parallelism (TP) against hybrid TP + Expert Parallelism (EP) for large MoE decode."""
    if num_gpus <= 0 or batch_tokens <= 0:
        raise ValueError("num_gpus and batch_tokens must be positive")
    if hot_expert_skew_factor < 1.0:
        raise ValueError("hot_expert_skew_factor must be >= 1.0")

    expert_weight_bytes_per_layer = (
        moe.routed_experts
        * 3
        * moe.hidden_dim
        * moe.expert_intermediate_dim
        * moe.bytes_per_weight
    )
    hbm_bw_bytes_per_ms = (
        3200.0 * 1e9 * 0.72
    ) / 1000.0  # H100-class effective HBM bandwidth

    if strategy == "pure_tp16":
        # Pure TP16 slices every expert into 16 tiny shards and executes 2 all-reduce barriers per layer across 16 GPUs.
        per_gpu_weight_read = expert_weight_bytes_per_layer / num_gpus
        compute_and_hbm_ms_per_layer = (
            per_gpu_weight_read / hbm_bw_bytes_per_ms
        ) / 0.42
        comm_ms_per_layer = 0.24 + (batch_tokens * moe.hidden_dim * 2 * 2) / (
            50.0 * 1e9 / 1000.0
        )
        straggler_multiplier = 1.0
        layer_tpot_ms = compute_and_hbm_ms_per_layer + comm_ms_per_layer
    else:
        # Generic hybrid TP/EP placement scenario; experts per rank depend on this input.
        # replacing 16-way all-reduce with compact all-to-all token dispatch + combine.
        ep_degree = 8
        active_fraction = min(1.0, (batch_tokens * moe.top_k) / moe.routed_experts)
        per_gpu_weight_read = (expert_weight_bytes_per_layer / ep_degree) * min(
            1.0, active_fraction
        )
        compute_and_hbm_ms_per_layer = (
            per_gpu_weight_read / hbm_bw_bytes_per_ms
        ) / 0.86
        routed_bytes = batch_tokens * moe.top_k * moe.hidden_dim * 1  # FP8 dispatch
        comm_ms_per_layer = 0.07 + (2 * routed_bytes) / (150.0 * 1e9 / 1000.0)
        # If one expert rank receives skewed traffic without redundant hot-expert replication,
        # both expert GEMM time and incast all-to-all combine stall on the hottest EP rank.
        straggler_multiplier = (
            min(1.18, 1.0 + (hot_expert_skew_factor - 1.0) * 0.12)
            if enable_redundant_hot_experts
            else hot_expert_skew_factor
        )
        layer_tpot_ms = (
            compute_and_hbm_ms_per_layer + comm_ms_per_layer
        ) * straggler_multiplier

    step_tpot_ms = round(layer_tpot_ms * moe.layers, 2)
    throughput_tokens_per_sec = round((batch_tokens / step_tpot_ms) * 1000.0, 1)

    return {
        "model": moe.name,
        "strategy": strategy,
        "num_gpus": num_gpus,
        "batch_tokens": batch_tokens,
        "hot_expert_skew_factor": hot_expert_skew_factor,
        "enable_redundant_hot_experts": enable_redundant_hot_experts,
        "effective_straggler_multiplier": round(straggler_multiplier, 3),
        "compute_and_hbm_ms_per_layer": round(
            compute_and_hbm_ms_per_layer * straggler_multiplier, 4
        ),
        "comm_ms_per_layer": round(comm_ms_per_layer * straggler_multiplier, 4),
        "step_tpot_ms": step_tpot_ms,
        "cluster_decode_tokens_per_sec": throughput_tokens_per_sec,
    }


def run_all_evaluations() -> dict[str, object]:
    kv_spec = ModelKVSpec()
    workload = DisaggregationWorkload()
    pd_by_network = {
        net: evaluate_pd_disaggregation(kv_spec, workload, net)
        for net in ("nvlink_900gbs", "rdma_roce_50gbs", "tcp_ethernet_12_5gbs")
    }
    moe_comparisons = {
        "pure_tp16_baseline": evaluate_moe_parallelism(strategy="pure_tp16"),
        "hybrid_tp2_ep8_balanced": evaluate_moe_parallelism(
            strategy="hybrid_tp2_ep8",
            hot_expert_skew_factor=1.15,
            enable_redundant_hot_experts=True,
        ),
        "hybrid_tp2_ep8_skewed_no_redundancy": evaluate_moe_parallelism(
            strategy="hybrid_tp2_ep8",
            hot_expert_skew_factor=2.6,
            enable_redundant_hot_experts=False,
        ),
        "hybrid_tp2_ep8_skewed_with_redundancy": evaluate_moe_parallelism(
            strategy="hybrid_tp2_ep8",
            hot_expert_skew_factor=2.6,
            enable_redundant_hot_experts=True,
        ),
    }
    return {
        "experiment": "prefill-decode-disaggregation-and-moe-expert-parallelism",
        "kv_spec": asdict(kv_spec),
        "pd_disaggregation_by_interconnect": pd_by_network,
        "moe_parallelism": moe_comparisons,
    }


def main() -> None:
    print(
        json.dumps(
            {
                "execution_mode": "CPU algorithm with controlled inputs; any latency/capacity coefficients are assumptions",
                **run_all_evaluations(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
