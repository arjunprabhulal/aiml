"""Discrete-event simulator comparing static padded batching vs continuous batching."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math


@dataclass(frozen=True)
class InferenceRequest:
    req_id: str
    arrival_ms: float
    prompt_tokens: int
    output_tokens: int


@dataclass
class CompletedRequest:
    req_id: str
    arrival_ms: float
    start_ms: float
    completion_ms: float
    prompt_tokens: int
    output_tokens: int

    @property
    def queue_delay_ms(self) -> float:
        return self.start_ms - self.arrival_ms

    @property
    def e2e_latency_ms(self) -> float:
        return self.completion_ms - self.arrival_ms


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((p / 100.0) * len(ordered)) - 1))
    return ordered[idx]


class StaticBatchRunner:
    """Locks a batch of up to max_batch_size requests until the longest output finishes."""

    def __init__(
        self,
        max_batch_size: int = 4,
        prefill_ms_per_token: float = 0.08,
        decode_step_ms: float = 12.0,
    ) -> None:
        self.max_batch_size = max_batch_size
        self.prefill_ms_per_token = prefill_ms_per_token
        self.decode_step_ms = decode_step_ms

    def run(self, requests: list[InferenceRequest]) -> dict[str, object]:
        pending = sorted(requests, key=lambda r: r.arrival_ms)
        clock_ms = 0.0
        completed: list[CompletedRequest] = []
        wasted_pad_token_steps = 0
        valid_token_steps = 0

        for idx in range(0, len(pending), self.max_batch_size):
            batch = pending[idx : idx + self.max_batch_size]
            latest_arrival = max(r.arrival_ms for r in batch)
            clock_ms = max(clock_ms, latest_arrival)
            batch_start_ms = clock_ms

            # Both policies use the same packed-prefill cost assumption.
            prefill_duration_ms = (
                sum(r.prompt_tokens for r in batch) * self.prefill_ms_per_token
            )
            clock_ms += prefill_duration_ms

            # Decode until the longest sequence in the batch emits EOS
            max_output = max(r.output_tokens for r in batch)
            decode_duration_ms = (max_output - 1) * self.decode_step_ms
            clock_ms += decode_duration_ms

            for r in batch:
                valid_token_steps += r.output_tokens
                wasted_pad_token_steps += max_output - r.output_tokens
                completed.append(
                    CompletedRequest(
                        req_id=r.req_id,
                        arrival_ms=r.arrival_ms,
                        start_ms=batch_start_ms,
                        completion_ms=batch_start_ms
                        + prefill_duration_ms
                        + (r.output_tokens - 1) * self.decode_step_ms,
                        prompt_tokens=r.prompt_tokens,
                        output_tokens=r.output_tokens,
                    )
                )

        return _summarize_run(
            mode="static_batching",
            completed=completed,
            total_elapsed_ms=clock_ms,
            valid_token_steps=valid_token_steps,
            wasted_pad_token_steps=wasted_pad_token_steps,
        )


class ContinuousBatchScheduler:
    """Iteration-level scheduler: finished sequences exit each step and waiting requests join."""

    def __init__(
        self,
        max_batch_size: int = 4,
        max_kv_tokens: int = 8192,
        prefill_ms_per_token: float = 0.08,
        decode_step_ms: float = 12.0,
        enforce_kv_limit: bool = True,
    ) -> None:
        self.max_batch_size = max_batch_size
        self.max_kv_tokens = max_kv_tokens
        self.prefill_ms_per_token = prefill_ms_per_token
        self.decode_step_ms = decode_step_ms
        self.enforce_kv_limit = enforce_kv_limit

    def run(self, requests: list[InferenceRequest]) -> dict[str, object]:
        if not requests or self.max_batch_size < 1 or self.max_kv_tokens < 1:
            raise ValueError("Requests and capacities must be positive")
        if any(
            q.prompt_tokens < 1 or q.output_tokens < 1 or q.arrival_ms < 0
            for q in requests
        ):
            raise ValueError("Invalid request shape")
        waiting = sorted(requests, key=lambda q: q.arrival_ms)
        active = []
        completed = []
        clock_ms = 0.0
        valid_token_steps = 0
        peak_kv_tokens = 0

        def finish_done():
            nonlocal active
            keep = []
            for slot in active:
                q = slot["req"]
                if slot["remaining"] == 0:
                    completed.append(
                        CompletedRequest(
                            q.req_id,
                            q.arrival_ms,
                            slot["start_ms"],
                            clock_ms,
                            q.prompt_tokens,
                            q.output_tokens,
                        )
                    )
                else:
                    keep.append(slot)
            active = keep

        while waiting or active:
            if not active and waiting:
                clock_ms = max(clock_ms, waiting[0].arrival_ms)
            admitted = []
            reserved = sum(s["kv_tokens"] + s["remaining"] for s in active)
            while (
                waiting
                and len(active) < self.max_batch_size
                and waiting[0].arrival_ms <= clock_ms
            ):
                q = waiting[0]
                need = q.prompt_tokens + q.output_tokens - 1
                if self.enforce_kv_limit and reserved + need > self.max_kv_tokens:
                    if not active:
                        raise MemoryError("Request exceeds total KV capacity")
                    break
                waiting.pop(0)
                reserved += need
                slot = {
                    "req": q,
                    "start_ms": clock_ms,
                    "remaining": q.output_tokens - 1,
                    "kv_tokens": q.prompt_tokens,
                }
                active.append(slot)
                admitted.append(slot)
            if admitted:
                clock_ms += (
                    sum(s["req"].prompt_tokens for s in admitted)
                    * self.prefill_ms_per_token
                )
                valid_token_steps += len(
                    admitted
                )  # prefill supplies the first output token
                peak_kv_tokens = max(
                    peak_kv_tokens, sum(s["kv_tokens"] for s in active)
                )
                finish_done()
            if active:
                clock_ms += self.decode_step_ms
                for slot in active:
                    slot["remaining"] -= 1
                    slot["kv_tokens"] += 1
                    valid_token_steps += 1
                peak_kv_tokens = max(
                    peak_kv_tokens, sum(s["kv_tokens"] for s in active)
                )
                if peak_kv_tokens > self.max_kv_tokens:
                    raise MemoryError("Active KV tokens exceeded max_kv_tokens")
                finish_done()
        summary = _summarize_run(
            "continuous_batching", completed, clock_ms, valid_token_steps, 0
        )
        summary["peak_kv_tokens"] = peak_kv_tokens
        return summary


def _summarize_run(
    mode: str,
    completed: list[CompletedRequest],
    total_elapsed_ms: float,
    valid_token_steps: int,
    wasted_pad_token_steps: int,
) -> dict[str, object]:
    queue_delays = [c.queue_delay_ms for c in completed]
    e2e_latencies = [c.e2e_latency_ms for c in completed]
    short_e2e = [c.e2e_latency_ms for c in completed if c.output_tokens <= 64]
    total_steps = valid_token_steps + wasted_pad_token_steps
    effective_tps = valid_token_steps / (total_elapsed_ms / 1000.0)
    return {
        "mode": mode,
        "requests_completed": len(completed),
        "total_elapsed_ms": round(total_elapsed_ms, 2),
        "valid_output_tokens": valid_token_steps,
        "wasted_pad_token_steps": wasted_pad_token_steps,
        "pad_waste_ratio": round(wasted_pad_token_steps / total_steps, 4)
        if total_steps
        else 0.0,
        "avg_queue_delay_ms": round(sum(queue_delays) / len(queue_delays), 2),
        "avg_short_request_e2e_ms": round(sum(short_e2e) / len(short_e2e), 2)
        if short_e2e
        else 0.0,
        "p50_e2e_latency_ms": round(percentile(e2e_latencies, 50), 2),
        "p95_e2e_latency_ms": round(percentile(e2e_latencies, 95), 2),
        "effective_tokens_per_sec": round(effective_tps, 2),
        "per_request": [
            {
                "req_id": c.req_id,
                "output_tokens": c.output_tokens,
                "queue_delay_ms": round(c.queue_delay_ms, 2),
                "e2e_latency_ms": round(c.e2e_latency_ms, 2),
            }
            for c in sorted(completed, key=lambda x: x.req_id)
        ],
    }


def make_heterogeneous_workload() -> list[InferenceRequest]:
    """12 requests mixing short chat replies (32-64 tokens) with long generations (512 tokens)."""
    specs = [
        ("req-01", 0.0, 256, 512),
        ("req-02", 0.0, 128, 32),
        ("req-03", 0.0, 128, 48),
        ("req-04", 0.0, 128, 64),
        ("req-05", 60.0, 192, 48),
        ("req-06", 120.0, 128, 32),
        ("req-07", 180.0, 256, 512),
        ("req-08", 240.0, 128, 64),
        ("req-09", 300.0, 160, 48),
        ("req-10", 360.0, 128, 32),
        ("req-11", 420.0, 192, 64),
        ("req-12", 480.0, 128, 48),
    ]
    return [InferenceRequest(*s) for s in specs]


def compare_batching_modes() -> dict[str, object]:
    workload = make_heterogeneous_workload()
    static_res = StaticBatchRunner(max_batch_size=4).run(workload)
    cont_res = ContinuousBatchScheduler(max_batch_size=4, max_kv_tokens=4096).run(
        workload
    )
    return {
        "workload_summary": {
            "num_requests": len(workload),
            "max_batch_size": 4,
            "total_generated_tokens": sum(r.output_tokens for r in workload),
        },
        "static_batching": static_res,
        "continuous_batching": cont_res,
        "speedup_metrics": {
            "throughput_gain_x": round(
                float(cont_res["effective_tokens_per_sec"])
                / float(static_res["effective_tokens_per_sec"]),
                2,
            ),
            "short_request_latency_reduction_x": round(
                float(static_res["avg_short_request_e2e_ms"])
                / float(cont_res["avg_short_request_e2e_ms"]),
                2,
            ),
            "p95_latency_reduction_x": round(
                float(static_res["p95_e2e_latency_ms"])
                / float(cont_res["p95_e2e_latency_ms"]),
                2,
            ),
        },
    }


def main() -> None:
    print(
        json.dumps(
            {
                "execution_mode": "CPU algorithm with controlled inputs; any latency/capacity coefficients are assumptions",
                **compare_batching_modes(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
