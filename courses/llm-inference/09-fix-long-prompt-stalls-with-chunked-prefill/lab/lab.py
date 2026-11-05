from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Literal


@dataclass
class InferenceRequest:
    request_id: str
    prompt_tokens: int
    max_new_tokens: int
    arrival_ms: float = 0.0
    prefilled_tokens: int = 0
    generated_tokens: int = 0
    first_token_ms: float | None = None
    completion_ms: float | None = None
    decode_step_timestamps_ms: list[float] = field(default_factory=list)

    @property
    def is_prefill_complete(self) -> bool:
        return self.prefilled_tokens >= self.prompt_tokens

    @property
    def is_finished(self) -> bool:
        return self.is_prefill_complete and self.generated_tokens >= self.max_new_tokens


def estimate_step_latency_ms(
    decode_tokens: int,
    prefill_chunks: list[tuple[int, int]],
    base_weight_read_ms: float = 14.0,
    compute_ms_per_token: float = 0.0085,
    kv_attend_ms_per_1k_tokens: float = 0.00008,
    ridge_tokens: int = 128,
) -> float:
    """Estimate one forward-pass step duration on a tensor-parallel GPU node.

    - base_weight_read_ms: HBM weight-streaming floor paid once per forward pass.
    - compute_ms_per_token: GEMM compute cost for tokens beyond the roofline ridge point.
    - kv_attend_ms_per_1k_tokens: GQA causal KV attention cost per prefill token
      multiplied by its effective prefix length in thousands of tokens.
    """
    if decode_tokens < 0:
        raise ValueError("decode_tokens must be non-negative")
    total_prefill = sum(chunk_len for _, chunk_len in prefill_chunks)
    total_tokens = decode_tokens + total_prefill
    if total_tokens == 0:
        return 0.0

    extra_compute_tokens = max(0, total_tokens - ridge_tokens)
    gemm_ms = extra_compute_tokens * compute_ms_per_token

    attention_ms = 0.0
    for start_pos, chunk_len in prefill_chunks:
        avg_context_len = start_pos + (chunk_len / 2.0)
        attention_ms += (
            chunk_len * (avg_context_len / 1000.0) * kv_attend_ms_per_1k_tokens
        )

    decode_kv_ms = decode_tokens * 0.035
    return round(base_weight_read_ms + gemm_ms + attention_ms + decode_kv_ms, 4)


class ChunkedPrefillScheduler:
    """Step-level simulator comparing monolithic prefill vs Sarathi-style chunked prefill."""

    def __init__(
        self,
        mode: Literal["monolithic", "chunked"] = "chunked",
        token_budget: int = 2048,
        tpot_slo_ms: float = 50.0,
    ) -> None:
        if mode not in ("monolithic", "chunked"):
            raise ValueError(f"Unsupported mode: {mode}")
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        self.mode = mode
        self.token_budget = token_budget
        self.tpot_slo_ms = tpot_slo_ms

    def run(self, requests: list[InferenceRequest]) -> dict[str, object]:
        cloned = [
            InferenceRequest(
                request_id=r.request_id,
                prompt_tokens=r.prompt_tokens,
                max_new_tokens=r.max_new_tokens,
                arrival_ms=r.arrival_ms,
                prefilled_tokens=r.prefilled_tokens,
                generated_tokens=r.generated_tokens,
                first_token_ms=r.first_token_ms,
                decode_step_timestamps_ms=list(r.decode_step_timestamps_ms),
            )
            for r in requests
        ]

        clock_ms = 0.0
        steps_log: list[dict[str, object]] = []

        while not all(r.is_finished for r in cloned):
            arrived = [
                r for r in cloned if r.arrival_ms <= clock_ms and not r.is_finished
            ]
            if not arrived:
                next_arrival = min(r.arrival_ms for r in cloned if not r.is_finished)
                clock_ms = next_arrival
                arrived = [
                    r for r in cloned if r.arrival_ms <= clock_ms and not r.is_finished
                ]

            active_decodes = [r for r in arrived if r.is_prefill_complete]
            pending_prefills = [r for r in arrived if not r.is_prefill_complete]

            scheduled_decodes: list[InferenceRequest] = []
            scheduled_prefills: list[tuple[InferenceRequest, int, int]] = []

            if self.mode == "monolithic" and pending_prefills:
                target = pending_prefills[0]
                remaining = target.prompt_tokens - target.prefilled_tokens
                scheduled_prefills.append((target, target.prefilled_tokens, remaining))
            else:
                if len(active_decodes) > self.token_budget:
                    raise ValueError(
                        f"Active decode count ({len(active_decodes)}) exceeds token_budget ({self.token_budget})"
                    )
                scheduled_decodes = list(active_decodes)
                remaining_budget = self.token_budget - len(scheduled_decodes)

                # Prioritize newly arrived short prefills at chunk boundaries so 100K prompts do not head-of-line block them
                ordered_prefills = sorted(
                    pending_prefills,
                    key=lambda r: (r.prompt_tokens - r.prefilled_tokens, r.arrival_ms),
                )
                for req in ordered_prefills:
                    if remaining_budget <= 0:
                        break
                    need = req.prompt_tokens - req.prefilled_tokens
                    take = min(need, remaining_budget)
                    scheduled_prefills.append((req, req.prefilled_tokens, take))
                    remaining_budget -= take

            step_ms = estimate_step_latency_ms(
                decode_tokens=len(scheduled_decodes),
                prefill_chunks=[
                    (start, length) for _, start, length in scheduled_prefills
                ],
            )
            clock_ms = round(clock_ms + step_ms, 4)

            for req in scheduled_decodes:
                req.generated_tokens += 1
                req.decode_step_timestamps_ms.append(clock_ms)
                if req.first_token_ms is None:
                    req.first_token_ms = clock_ms
                if req.is_finished:
                    req.completion_ms = clock_ms

            for req, _, chunk_len in scheduled_prefills:
                req.prefilled_tokens += chunk_len
                if req.is_prefill_complete:
                    req.generated_tokens += 1
                    req.decode_step_timestamps_ms.append(clock_ms)
                    req.first_token_ms = clock_ms
                    if req.is_finished:
                        req.completion_ms = clock_ms

            steps_log.append(
                {
                    "step_index": len(steps_log),
                    "clock_ms": clock_ms,
                    "step_ms": step_ms,
                    "decode_tokens": len(scheduled_decodes),
                    "prefill_tokens": sum(
                        length for _, _, length in scheduled_prefills
                    ),
                }
            )

        all_itls: list[float] = []
        per_request: dict[str, dict[str, object]] = {}
        for req in cloned:
            stamps = req.decode_step_timestamps_ms
            itls = [round(stamps[i] - stamps[i - 1], 4) for i in range(1, len(stamps))]
            if req.request_id.startswith("chat-"):
                all_itls.extend(itls)
            per_request[req.request_id] = {
                "prompt_tokens": req.prompt_tokens,
                "generated_tokens": req.generated_tokens,
                "ttft_ms": (
                    round(req.first_token_ms - req.arrival_ms, 2)
                    if req.first_token_ms is not None
                    else None
                ),
                "completion_ms": round(req.completion_ms or 0.0, 2),
                "max_itl_ms": round(max(itls), 2) if itls else 0.0,
                "mean_itl_ms": round(sum(itls) / len(itls), 2) if itls else 0.0,
            }

        max_chat_itl = round(max(all_itls), 2) if all_itls else 0.0
        mean_chat_itl = round(sum(all_itls) / len(all_itls), 2) if all_itls else 0.0
        return {
            "mode": self.mode,
            "token_budget": self.token_budget,
            "tpot_slo_ms": self.tpot_slo_ms,
            "total_steps": len(steps_log),
            "total_time_ms": round(clock_ms, 2),
            "max_itl_ms": max_chat_itl,
            "mean_itl_ms": mean_chat_itl,
            "short_chat_ttft_ms": per_request.get("chat-5", {}).get("ttft_ms"),
            "doc_100k_ttft_ms": per_request.get("doc-100k", {}).get("ttft_ms"),
            "tpot_slo_met": max_chat_itl <= self.tpot_slo_ms,
            "requests": per_request,
        }


def build_default_workload() -> list[InferenceRequest]:
    """Four active chat decode streams, an arriving 100K document prompt, and a short chat arriving at 10ms."""
    return [
        InferenceRequest(
            request_id=f"chat-{i}",
            prompt_tokens=512,
            max_new_tokens=60,
            arrival_ms=0.0,
            prefilled_tokens=512,
            generated_tokens=1,
            first_token_ms=0.0,
            decode_step_timestamps_ms=[0.0],
        )
        for i in range(1, 5)
    ] + [
        InferenceRequest(
            request_id="doc-100k",
            prompt_tokens=100_000,
            max_new_tokens=8,
            arrival_ms=0.0,
        ),
        InferenceRequest(
            request_id="chat-5",
            prompt_tokens=256,
            max_new_tokens=16,
            arrival_ms=10.0,
        ),
    ]


def simulate_long_prompt_arrival(
    token_budget: int = 2048, tpot_slo_ms: float = 50.0
) -> dict[str, object]:
    workload = build_default_workload()
    monolithic = ChunkedPrefillScheduler(
        mode="monolithic", token_budget=token_budget, tpot_slo_ms=tpot_slo_ms
    ).run(workload)
    chunked = ChunkedPrefillScheduler(
        mode="chunked", token_budget=token_budget, tpot_slo_ms=tpot_slo_ms
    ).run(workload)

    budget_sweep = []
    for budget in (512, 1024, 2048, 4096, 8192):
        res = ChunkedPrefillScheduler(
            mode="chunked", token_budget=budget, tpot_slo_ms=tpot_slo_ms
        ).run(workload)
        budget_sweep.append(
            {
                "token_budget": budget,
                "num_prefill_chunks": (100_000 + (budget - 5) - 1) // (budget - 5),
                "max_itl_ms": res["max_itl_ms"],
                "mean_itl_ms": res["mean_itl_ms"],
                "short_chat_ttft_ms": res["short_chat_ttft_ms"],
                "doc_100k_ttft_ms": res["doc_100k_ttft_ms"],
                "tpot_slo_met": res["tpot_slo_met"],
            }
        )

    return {
        "workload": {
            "active_chat_streams": 4,
            "arriving_short_chat_tokens": 256,
            "long_prompt_tokens": 100_000,
            "tpot_slo_ms": tpot_slo_ms,
        },
        "monolithic": monolithic,
        "chunked_2048": chunked,
        "stall_reduction_factor": round(
            monolithic["max_itl_ms"] / chunked["max_itl_ms"], 2
        ),
        "budget_sweep": budget_sweep,
    }


def main() -> None:
    report = simulate_long_prompt_arrival(token_budget=2048, tpot_slo_ms=50.0)
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
