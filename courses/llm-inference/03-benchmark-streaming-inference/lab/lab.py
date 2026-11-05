"""Replay generic workload scenarios with assumed coefficients; use benchmark.py for actual HTTP measurements."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import random


@dataclass(frozen=True)
class WorkloadRequest:
    request_id: str
    arrival_ms: float
    shared_prefix_tokens: int
    unique_prompt_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class EngineProfile:
    name: str
    prefill_tokens_per_ms: float
    prefix_cache_hit_efficiency: float
    base_tpot_ms: float
    batch_tpot_slope_ms: float
    max_batch_slots: int


@dataclass(frozen=True)
class BenchmarkSummary:
    engine: str
    workload: str
    total_requests: int
    duration_s: float
    ttft_p50_ms: float
    ttft_p99_ms: float
    tpot_p50_ms: float
    tpot_p99_ms: float
    raw_output_tokens_per_s: float
    request_throughput_rps: float
    slo_goodput_rps: float
    slo_attainment_ratio: float


SCENARIO_PROFILES: dict[str, EngineProfile] = {
    "baseline": EngineProfile(
        name="baseline",
        prefill_tokens_per_ms=26.0,
        prefix_cache_hit_efficiency=0.45,
        base_tpot_ms=17.5,
        batch_tpot_slope_ms=0.62,
        max_batch_slots=16,
    ),
    "prefix_reuse": EngineProfile(
        name="prefix_reuse",
        prefill_tokens_per_ms=27.0,
        prefix_cache_hit_efficiency=0.92,
        base_tpot_ms=16.8,
        batch_tpot_slope_ms=0.58,
        max_batch_slots=16,
    ),
    "faster_decode": EngineProfile(
        name="faster_decode",
        prefill_tokens_per_ms=34.0,
        prefix_cache_hit_efficiency=0.50,
        base_tpot_ms=12.4,
        batch_tpot_slope_ms=0.44,
        max_batch_slots=16,
    ),
}


def build_agent_trace(
    num_requests: int = 80, seed: int = 42, mean_rps: float = 8.5
) -> list[WorkloadRequest]:
    rng = random.Random(seed)
    trace: list[WorkloadRequest] = []
    current_ms = 0.0
    for idx in range(num_requests):
        # Bursty gamma-like arrivals: alternating bursts (short inter-arrival) and lulls.
        burst_factor = 0.32 if (idx % 10) in (2, 3, 4, 5, 6) else 1.55
        inter_arrival_ms = rng.expovariate(mean_rps / 1000.0) * burst_factor
        current_ms += inter_arrival_ms
        shared_prefix = 3072 if idx % 4 != 0 else 2048
        unique_prompt = 256 + (idx % 5) * 64
        output_len = 96 + (idx % 4) * 32
        trace.append(
            WorkloadRequest(
                request_id=f"req-{idx:03d}",
                arrival_ms=round(current_ms, 2),
                shared_prefix_tokens=shared_prefix,
                unique_prompt_tokens=unique_prompt,
                output_tokens=output_len,
            )
        )
    return trace


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = min(len(sorted_vals) - 1, max(0, int(math.ceil(q * len(sorted_vals)) - 1)))
    return sorted_vals[pos]


def evaluate_engine_benchmark(
    trace: list[WorkloadRequest],
    profile: EngineProfile,
    workload_name: str = "agent-shared-prefix",
    ttft_slo_ms: float = 500.0,
    tpot_slo_ms: float = 35.0,
    closed_loop: bool = False,
) -> BenchmarkSummary:
    if profile.max_batch_slots < 1 or profile.prefill_tokens_per_ms <= 0:
        raise ValueError("Capacity and prefill rate must be positive")
    if not trace:
        raise ValueError("Workload trace must not be empty")

    prefill_free_at_ms = 0.0
    active_completions_ms: list[float] = []
    ttft_samples: list[float] = []
    tpot_samples: list[float] = []
    slo_passed = 0
    total_output_tokens = 0
    first_arrival_ms = trace[0].arrival_ms
    last_completion_ms = 0.0

    for req in trace:
        effective_arrival_ms = last_completion_ms if closed_loop else req.arrival_ms
        # Enforce admission capacity instead of merely capping the reported batch.
        occupied = sorted(t for t in active_completions_ms if t > effective_arrival_ms)
        admitted_at_ms = effective_arrival_ms
        if len(occupied) >= profile.max_batch_slots:
            admitted_at_ms = occupied[len(occupied) - profile.max_batch_slots]
        active_completions_ms = [t for t in active_completions_ms if t > admitted_at_ms]
        active_batch = min(profile.max_batch_slots, len(active_completions_ms) + 1)

        queue_wait_ms = max(admitted_at_ms, prefill_free_at_ms) - effective_arrival_ms
        uncached_shared = req.shared_prefix_tokens * (
            1.0 - profile.prefix_cache_hit_efficiency
        )
        effective_prefill_tokens = uncached_shared + req.unique_prompt_tokens
        prefill_ms = 3.0 + (effective_prefill_tokens / profile.prefill_tokens_per_ms)

        ttft_ms = queue_wait_ms + prefill_ms
        prefill_free_at_ms = effective_arrival_ms + ttft_ms

        tpot_ms = profile.base_tpot_ms + profile.batch_tpot_slope_ms * active_batch
        decode_ms = (req.output_tokens - 1) * tpot_ms
        completion_ms = effective_arrival_ms + ttft_ms + decode_ms

        active_completions_ms.append(completion_ms)
        last_completion_ms = max(last_completion_ms, completion_ms)
        ttft_samples.append(round(ttft_ms, 2))
        tpot_samples.append(round(tpot_ms, 2))
        total_output_tokens += req.output_tokens

        if ttft_ms <= ttft_slo_ms and tpot_ms <= tpot_slo_ms:
            slo_passed += 1

    ttft_sorted = sorted(ttft_samples)
    tpot_sorted = sorted(tpot_samples)
    duration_s = max(
        0.001,
        (last_completion_ms - (0.0 if closed_loop else first_arrival_ms)) / 1000.0,
    )

    return BenchmarkSummary(
        engine=profile.name,
        workload=workload_name,
        total_requests=len(trace),
        duration_s=round(duration_s, 3),
        ttft_p50_ms=round(_percentile(ttft_sorted, 0.50), 2),
        ttft_p99_ms=round(_percentile(ttft_sorted, 0.99), 2),
        tpot_p50_ms=round(_percentile(tpot_sorted, 0.50), 2),
        tpot_p99_ms=round(_percentile(tpot_sorted, 0.99), 2),
        raw_output_tokens_per_s=round(total_output_tokens / duration_s, 2),
        request_throughput_rps=round(len(trace) / duration_s, 3),
        slo_goodput_rps=round(slo_passed / duration_s, 3),
        slo_attainment_ratio=round(slo_passed / len(trace), 4),
    )


def main() -> None:
    trace = build_agent_trace(num_requests=80, seed=42, mean_rps=8.5)
    summaries = {
        name: asdict(evaluate_engine_benchmark(trace, profile))
        for name, profile in SCENARIO_PROFILES.items()
    }

    overbatched_trace = build_agent_trace(num_requests=80, seed=42, mean_rps=15.0)
    overbatched_profile = EngineProfile(
        name="overbatched_unbounded",
        prefill_tokens_per_ms=42.0,
        prefix_cache_hit_efficiency=0.50,
        base_tpot_ms=22.0,
        batch_tpot_slope_ms=0.45,
        max_batch_slots=48,
    )
    overbatched = evaluate_engine_benchmark(
        overbatched_trace,
        overbatched_profile,
        workload_name="overbatched-tail-violation",
    )
    closed_loop_baseline = evaluate_engine_benchmark(
        trace,
        SCENARIO_PROFILES["baseline"],
        workload_name="closed-loop-illusion",
        closed_loop=True,
    )

    report = {
        "experiment": "synthetic-arrival-and-goodput-scenarios",
        "execution_mode": "CPU simulation; arbitrary scenario coefficients, no serving engine executed",
        "scenario_assumptions": {k: asdict(v) for k, v in SCENARIO_PROFILES.items()},
        "slo_targets": {"ttft_slo_ms": 500.0, "tpot_slo_ms": 35.0},
        "trace_requests": len(trace),
        "scenario_comparisons": summaries,
        "diagnostics": {
            "overbatched_unbounded": asdict(overbatched),
            "closed_loop_baseline": asdict(closed_loop_baseline),
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
