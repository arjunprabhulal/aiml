"""Aggregate controlled request logs and report tail-latency diagnostic hypotheses."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math


@dataclass(frozen=True)
class RequestLog:
    request_id: str
    prompt_tokens: int
    output_tokens: int
    queue_wait_ms: float
    prefill_ms: float
    decode_tpot_ms: float
    preempted: bool
    recompute_penalty_ms: float
    prefix_cached_tokens: int
    kv_occupancy_pct_at_arrival: float

    def __post_init__(self):
        if (
            self.prompt_tokens < 1
            or self.output_tokens < 1
            or not 0 <= self.prefix_cached_tokens <= self.prompt_tokens
        ):
            raise ValueError("Invalid completed request token counts")
        values = [
            self.queue_wait_ms,
            self.prefill_ms,
            self.decode_tpot_ms,
            self.recompute_penalty_ms,
            self.kv_occupancy_pct_at_arrival,
        ]
        if (
            any(not math.isfinite(v) or v < 0 for v in values)
            or self.kv_occupancy_pct_at_arrival > 100
        ):
            raise ValueError("Invalid completed request measurements")

    @property
    def ttft_ms(self) -> float:
        return self.queue_wait_ms + self.prefill_ms

    @property
    def e2e_ms(self) -> float:
        return (
            self.ttft_ms
            + (max(0, self.output_tokens - 1) * self.decode_tpot_ms)
            + self.recompute_penalty_ms
        )


@dataclass(frozen=True)
class TelemetrySnapshot:
    window_name: str
    request_count: int
    mean_e2e_ms: float
    p50_e2e_ms: float
    p95_e2e_ms: float
    p99_e2e_ms: float
    p99_to_p50_ratio: float | None
    p50_ttft_ms: float
    p99_ttft_ms: float
    p50_tpot_ms: float | None
    p99_tpot_ms: float | None
    p99_queue_wait_ms: float
    peak_kv_occupancy_pct: float
    preemption_count: int
    estimated_recompute_tokens: int
    prefix_cache_hit_rate_pct: float
    modeled_cost_per_1k_requests_usd: float
    diagnostic_hypothesis: str


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("Cannot compute percentile of empty list")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((q / 100.0) * len(ordered)) - 1))
    return ordered[idx]


def diagnose_p99_spike(
    window_name: str,
    logs: list[RequestLog],
    gpu_hourly_cost_usd: float = 4.00,
    effective_concurrency: float = 32.0,
) -> TelemetrySnapshot:
    if not logs:
        raise ValueError("logs must not be empty")

    e2e_vals = [r.e2e_ms for r in logs]
    ttft_vals = [r.ttft_ms for r in logs]
    tpot_vals = [
        r.decode_tpot_ms + (r.recompute_penalty_ms / (r.output_tokens - 1))
        for r in logs if r.output_tokens > 1
    ]
    queue_vals = [r.queue_wait_ms for r in logs]

    mean_e2e = sum(e2e_vals) / len(e2e_vals)
    p50_e2e = percentile(e2e_vals, 50.0)
    p95_e2e = percentile(e2e_vals, 95.0)
    p99_e2e = percentile(e2e_vals, 99.0)
    ratio = p99_e2e / p50_e2e if p50_e2e else None

    p50_ttft = percentile(ttft_vals, 50.0)
    p99_ttft = percentile(ttft_vals, 99.0)
    p50_tpot = percentile(tpot_vals, 50.0) if tpot_vals else None
    p99_tpot = percentile(tpot_vals, 99.0) if tpot_vals else None
    p99_queue = percentile(queue_vals, 99.0)

    peak_kv = max(r.kv_occupancy_pct_at_arrival for r in logs)
    preemptions = sum(1 for r in logs if r.preempted)
    recompute_tokens = sum(
        (r.prompt_tokens + r.output_tokens // 2) for r in logs if r.preempted
    )

    total_prompt = sum(r.prompt_tokens for r in logs)
    cached_prompt = sum(r.prefix_cached_tokens for r in logs)
    prefix_hit_pct = (cached_prompt / total_prompt) * 100.0 if total_prompt else 0.0

    # Illustrative allocation proxy includes waiting; it is not measured GPU usage or a bill.
    avg_gpu_s_per_req = (mean_e2e / 1000.0) / effective_concurrency
    cost_per_1k = avg_gpu_s_per_req * 1000.0 * (gpu_hourly_cost_usd / 3600.0)

    if preemptions > 0 and peak_kv >= 95.0:
        diagnostic_hypothesis = "kv_cache_preemption_and_recompute_thrashing"
    elif p99_ttft > p50_ttft * 5.0 and preemptions == 0:
        diagnostic_hypothesis = "head_of_line_prefill_queue_blocking"
    elif prefix_hit_pct < 20.0 and p99_ttft > 1000.0:
        diagnostic_hypothesis = "cold_prefix_cache_miss_burst"
    else:
        diagnostic_hypothesis = "no_rule_matched"

    return TelemetrySnapshot(
        window_name=window_name,
        request_count=len(logs),
        mean_e2e_ms=round(mean_e2e, 1),
        p50_e2e_ms=round(p50_e2e, 1),
        p95_e2e_ms=round(p95_e2e, 1),
        p99_e2e_ms=round(p99_e2e, 1),
        p99_to_p50_ratio=round(ratio, 2) if ratio is not None else None,
        p50_ttft_ms=round(p50_ttft, 1),
        p99_ttft_ms=round(p99_ttft, 1),
        p50_tpot_ms=round(p50_tpot, 2) if p50_tpot is not None else None,
        p99_tpot_ms=round(p99_tpot, 2) if p99_tpot is not None else None,
        p99_queue_wait_ms=round(p99_queue, 1),
        peak_kv_occupancy_pct=round(peak_kv, 1),
        preemption_count=preemptions,
        estimated_recompute_tokens=recompute_tokens,
        prefix_cache_hit_rate_pct=round(prefix_hit_pct, 1),
        modeled_cost_per_1k_requests_usd=round(cost_per_1k, 4),
        diagnostic_hypothesis=diagnostic_hypothesis,
    )


def simulate_workload_logs(
    admit_watermark_pct: float = 98.5, chunked_prefill: bool = False
) -> list[RequestLog]:
    logs: list[RequestLog] = []
    for i in range(100):
        is_tail_burst = i >= 95
        if not is_tail_burst:
            logs.append(
                RequestLog(
                    request_id=f"req-{i:03d}",
                    prompt_tokens=1024,
                    output_tokens=128,
                    queue_wait_ms=14.0 + (i % 6) * 2.0,
                    prefill_ms=38.0 if chunked_prefill else 42.0,
                    decode_tpot_ms=14.5,
                    preempted=False,
                    recompute_penalty_ms=0.0,
                    prefix_cached_tokens=640,
                    kv_occupancy_pct_at_arrival=76.0 + (i % 9),
                )
            )
        else:
            burst_idx = i - 95
            if admit_watermark_pct > 90.0:
                # Over-admitting requests drives KV occupancy to 98.4% and triggers decode eviction + full recompute cascade
                cascade_queue_ms = 3200.0 + burst_idx * 850.0
                recompute_ms = 11200.0 + burst_idx * 1300.0
                logs.append(
                    RequestLog(
                        request_id=f"req-{i:03d}",
                        prompt_tokens=4096,
                        output_tokens=192,
                        queue_wait_ms=cascade_queue_ms,
                        prefill_ms=310.0,
                        decode_tpot_ms=22.0,
                        preempted=True,
                        recompute_penalty_ms=recompute_ms,
                        prefix_cached_tokens=1024,
                        kv_occupancy_pct_at_arrival=96.0 + burst_idx * 0.6,
                    )
                )
            else:
                # Admission watermark holds burst requests briefly at the gate; chunked prefill prevents HoL blocking
                gated_queue_ms = 85.0 + burst_idx * 18.0
                logs.append(
                    RequestLog(
                        request_id=f"req-{i:03d}",
                        prompt_tokens=4096,
                        output_tokens=192,
                        queue_wait_ms=gated_queue_ms,
                        prefill_ms=75.0 if chunked_prefill else 260.0,
                        decode_tpot_ms=15.0,
                        preempted=False,
                        recompute_penalty_ms=0.0,
                        prefix_cached_tokens=2048,
                        kv_occupancy_pct_at_arrival=84.5,
                    )
                )
    return logs


def main() -> None:
    unbounded_logs = simulate_workload_logs(
        admit_watermark_pct=98.5, chunked_prefill=False
    )
    gated_logs = simulate_workload_logs(admit_watermark_pct=85.0, chunked_prefill=True)

    before = diagnose_p99_spike("unbounded_98pct_kv_watermark", unbounded_logs)
    after = diagnose_p99_spike("gated_85pct_kv_plus_chunked_prefill", gated_logs)

    report = {
        "before_remediation": asdict(before),
        "after_remediation": asdict(after),
        "p99_reduction_x": round(before.p99_e2e_ms / after.p99_e2e_ms, 2),
        "recompute_tokens_eliminated": before.estimated_recompute_tokens
        - after.estimated_recompute_tokens,
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
