"""GPU roofline model and hardware selector for prefill and decode workloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json


@dataclass(frozen=True)
class GpuSpec:
    name: str
    memory_gb: float
    bandwidth_gbps: float
    bf16_tflops: float
    hourly_cost_usd: float

    @property
    def ridge_point_flops_per_byte(self) -> float:
        """Minimum operational intensity (FLOPs/byte) required to reach peak TFLOPS."""
        return (self.bf16_tflops * 1e12) / (self.bandwidth_gbps * 1e9)


@dataclass(frozen=True)
class ModelWorkload:
    model_name: str
    active_params_b: float
    bytes_per_param: int
    kv_bytes_per_token: int
    prompt_tokens: int
    output_tokens: int
    batch_size: int
    activation_overhead_gb: float = 2.0

    def validate(self) -> None:
        if self.active_params_b <= 0 or self.bytes_per_param <= 0:
            raise ValueError(
                "Model parameter count and bytes per parameter must be positive"
            )
        if self.prompt_tokens <= 0 or self.output_tokens <= 0 or self.batch_size <= 0:
            raise ValueError(
                "Prompt tokens, output tokens, and batch size must be positive integers"
            )

    @property
    def weight_bytes(self) -> float:
        return self.active_params_b * 1e9 * self.bytes_per_param

    @property
    def total_kv_bytes(self) -> float:
        seq_len = self.prompt_tokens + self.output_tokens
        return float(self.batch_size * seq_len * self.kv_bytes_per_token)

    @property
    def required_memory_gb(self) -> float:
        return (
            self.weight_bytes + self.total_kv_bytes
        ) / 1e9 + self.activation_overhead_gb


@dataclass(frozen=True)
class WorkloadPhaseMetrics:
    phase: str
    flops: float
    hbm_bytes: float
    operational_intensity: float
    ridge_point: float
    regime: str
    roofline_tflops_bound: float
    latency_ms: float


GPU_SPECS: dict[str, GpuSpec] = {
    "example-small": GpuSpec(
        name="example-small",
        memory_gb=48.0,
        bandwidth_gbps=864.0,
        bf16_tflops=362.0,
        hourly_cost_usd=1.55,
    ),
    "example-fast": GpuSpec(
        name="example-fast",
        memory_gb=80.0,
        bandwidth_gbps=3350.0,
        bf16_tflops=989.0,
        hourly_cost_usd=3.20,
    ),
    "example-large-memory": GpuSpec(
        name="example-large-memory",
        memory_gb=141.0,
        bandwidth_gbps=4800.0,
        bf16_tflops=989.0,
        hourly_cost_usd=3.80,
    ),
    "example-wide-bandwidth": GpuSpec(
        name="example-wide-bandwidth",
        memory_gb=192.0,
        bandwidth_gbps=8000.0,
        bf16_tflops=2250.0,
        hourly_cost_usd=6.20,
    ),
}


def compute_prefill_metrics(
    gpu: GpuSpec, workload: ModelWorkload
) -> WorkloadPhaseMetrics:
    workload.validate()
    total_prefill_tokens = workload.batch_size * workload.prompt_tokens
    flops = 2.0 * (workload.active_params_b * 1e9) * total_prefill_tokens
    kv_write_bytes = float(total_prefill_tokens * workload.kv_bytes_per_token)
    hbm_bytes = workload.weight_bytes + kv_write_bytes
    intensity = flops / hbm_bytes
    ridge = gpu.ridge_point_flops_per_byte
    regime = "compute-bound" if intensity >= ridge else "bandwidth-bound"
    compute_seconds = flops / (gpu.bf16_tflops * 1e12)
    memory_seconds = hbm_bytes / (gpu.bandwidth_gbps * 1e9)
    latency_s = max(compute_seconds, memory_seconds)
    roofline_tflops_bound = (flops / latency_s) / 1e12
    return WorkloadPhaseMetrics(
        phase="prefill",
        flops=round(flops, 2),
        hbm_bytes=round(hbm_bytes, 2),
        operational_intensity=round(intensity, 2),
        ridge_point=round(ridge, 2),
        regime=regime,
        roofline_tflops_bound=round(roofline_tflops_bound, 2),
        latency_ms=round(latency_s * 1000.0, 3),
    )


def compute_decode_step_metrics(
    gpu: GpuSpec, workload: ModelWorkload
) -> WorkloadPhaseMetrics:
    workload.validate()
    flops = 2.0 * (workload.active_params_b * 1e9) * workload.batch_size
    avg_context_len = workload.prompt_tokens + (workload.output_tokens / 2.0)
    kv_read_bytes = float(
        workload.batch_size * avg_context_len * workload.kv_bytes_per_token
    )
    hbm_bytes = workload.weight_bytes + kv_read_bytes
    intensity = flops / hbm_bytes
    ridge = gpu.ridge_point_flops_per_byte
    regime = "compute-bound" if intensity >= ridge else "bandwidth-bound"
    compute_seconds = flops / (gpu.bf16_tflops * 1e12)
    memory_seconds = hbm_bytes / (gpu.bandwidth_gbps * 1e9)
    latency_s = max(compute_seconds, memory_seconds)
    roofline_tflops_bound = (flops / latency_s) / 1e12
    return WorkloadPhaseMetrics(
        phase="decode_step",
        flops=round(flops, 2),
        hbm_bytes=round(hbm_bytes, 2),
        operational_intensity=round(intensity, 2),
        ridge_point=round(ridge, 2),
        regime=regime,
        roofline_tflops_bound=round(roofline_tflops_bound, 2),
        latency_ms=round(latency_s * 1000.0, 3),
    )


def evaluate_gpu_for_workload(
    gpu: GpuSpec,
    workload: ModelWorkload,
    require_single_card_fit: bool = True,
) -> dict[str, object]:
    workload.validate()
    required_gb = workload.required_memory_gb
    fits = required_gb <= gpu.memory_gb
    if require_single_card_fit and not fits:
        raise ValueError(
            f"{gpu.name} has {gpu.memory_gb:.1f} GB VRAM, below required {required_gb:.2f} GB"
        )
    prefill = compute_prefill_metrics(gpu, workload)
    decode = compute_decode_step_metrics(gpu, workload)
    ttft_ms = prefill.latency_ms
    tpot_ms = decode.latency_ms
    total_latency_s = (ttft_ms + tpot_ms * (workload.output_tokens - 1)) / 1000.0
    decode_tokens_per_sec = workload.batch_size / (tpot_ms / 1000.0)
    end_to_end_tokens_per_sec = (
        workload.batch_size * workload.output_tokens
    ) / total_latency_s
    tokens_per_dollar = end_to_end_tokens_per_sec * 3600 / gpu.hourly_cost_usd
    return {
        "gpu": gpu.name,
        "memory_gb": gpu.memory_gb,
        "required_memory_gb": round(required_gb, 2),
        "fits_single_gpu": fits,
        "ridge_point_flops_per_byte": round(gpu.ridge_point_flops_per_byte, 2),
        "prefill": asdict(prefill),
        "decode": asdict(decode),
        "ttft_ms": round(ttft_ms, 2),
        "tpot_ms": round(tpot_ms, 3),
        "decode_tokens_per_sec": round(decode_tokens_per_sec, 2),
        "end_to_end_tokens_per_sec": round(end_to_end_tokens_per_sec, 2),
        "tokens_per_dollar": round(tokens_per_dollar, 2),
    }


def build_report() -> dict[str, object]:
    # 8B BF16 model (16 GB weights, 128 KB/token KV cache for 32 layers GQA)
    small_model_comparisons = []
    for name, gpu in GPU_SPECS.items():
        workload = ModelWorkload(
            model_name="Llama-3-8B-BF16",
            active_params_b=8.0,
            bytes_per_param=2,
            kv_bytes_per_token=131072,
            prompt_tokens=2048,
            output_tokens=256,
            batch_size=8,
        )
        small_model_comparisons.append(evaluate_gpu_for_workload(gpu, workload))

    # 70B BF16 model (140 GB weights? Or 32B BF16 = 64 GB weights + KV cache)
    # Let's evaluate a 32B BF16 model (64 GB weights) with long context that fits H200/example-wide-bandwidth
    # and overflows example-small/H100 when KV cache grows.
    large_workload = ModelWorkload(
        model_name="Qwen-32B-BF16-LongContext",
        active_params_b=32.0,
        bytes_per_param=2,
        kv_bytes_per_token=262144,
        prompt_tokens=4096,
        output_tokens=512,
        batch_size=16,
    )
    large_model_comparisons = [
        evaluate_gpu_for_workload(gpu, large_workload, require_single_card_fit=False)
        for gpu in GPU_SPECS.values()
    ]

    batch_sweep = []
    for batch_size in (1, 8, 32, 128, 256):
        w = ModelWorkload(
            model_name="Llama-3-8B-BF16",
            active_params_b=8.0,
            bytes_per_param=2,
            kv_bytes_per_token=131072,
            prompt_tokens=1024,
            output_tokens=128,
            batch_size=batch_size,
        )
        metrics = evaluate_gpu_for_workload(GPU_SPECS["example-fast"], w)
        batch_sweep.append(
            {
                "batch_size": batch_size,
                "prefill_intensity": metrics["prefill"]["operational_intensity"],
                "prefill_regime": metrics["prefill"]["regime"],
                "decode_intensity": metrics["decode"]["operational_intensity"],
                "decode_regime": metrics["decode"]["regime"],
                "decode_roofline_tflops_bound": metrics["decode"][
                    "roofline_tflops_bound"
                ],
                "tpot_ms": metrics["tpot_ms"],
                "decode_tokens_per_sec": metrics["decode_tokens_per_sec"],
            }
        )

    return {
        "gpu_catalog": [
            {
                **asdict(gpu),
                "ridge_point_flops_per_byte": round(gpu.ridge_point_flops_per_byte, 2),
            }
            for gpu in GPU_SPECS.values()
        ],
        "llama_8b_batch8": small_model_comparisons,
        "qwen_32b_long_context": large_model_comparisons,
        "h100_batch_sweep": batch_sweep,
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
