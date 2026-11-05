"""Multi-tenant LLM inference scheduler with service-token deficit round-robin and KV-aware admission control."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import json
import math
from typing import Literal

PriorityClass = Literal["interactive", "batch"]


@dataclass(frozen=True)
class TenantQuota:
    tenant_id: str
    weight: float
    burst_service_tokens: int
    sustained_service_tokens_per_sec: int
    priority_class: PriorityClass = "interactive"

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError("tenant_id must be non-empty")
        if self.weight <= 0:
            raise ValueError("weight must be positive")
        if self.burst_service_tokens <= 0 or self.sustained_service_tokens_per_sec <= 0:
            raise ValueError("token quotas must be positive")


@dataclass(frozen=True)
class InferenceRequest:
    request_id: str
    tenant_id: str
    arrival_ms: int
    prefill_tokens: int
    decode_tokens: int
    priority_class: PriorityClass

    def service_tokens(self, decode_weight: int = 4) -> int:
        if decode_weight <= 0:
            raise ValueError("decode_weight must be positive")
        return self.prefill_tokens + decode_weight * self.decode_tokens

    def kv_blocks_required(self, block_tokens: int = 16) -> int:
        return math.ceil((self.prefill_tokens + self.decode_tokens) / block_tokens)


@dataclass(frozen=True)
class ScheduledOutcome:
    request_id: str
    tenant_id: str
    priority_class: PriorityClass
    status_code: int
    reason: str
    service_tokens: int
    ttft_ms: float
    queue_wait_ms: float
    kv_occupancy_ratio: float


class MultiTenantScheduler:
    """Schedules multi-tenant GPU inference requests using service-token DRR and KV admission watermarks."""

    def __init__(
        self,
        quotas: list[TenantQuota],
        *,
        total_kv_blocks: int = 1600,
        interactive_kv_watermark: float = 0.90,
        batch_kv_watermark: float = 0.65,
        max_interactive_wait_ms: float = 420.0,
        max_batch_wait_ms: float = 3500.0,
        decode_weight: int = 4,
        base_quantum_tokens: int = 1200,
        cluster_service_tokens_per_ms: float = 45.0,
        scheduling_mode: Literal[
            "service_token_drr", "request_count_fifo"
        ] = "service_token_drr",
        enable_admission_control: bool = True,
    ) -> None:
        if not quotas:
            raise ValueError("At least one TenantQuota is required")
        if not (0.0 < batch_kv_watermark <= interactive_kv_watermark <= 1.0):
            raise ValueError(
                "Watermarks must satisfy 0 < batch_kv_watermark <= interactive_kv_watermark <= 1"
            )
        self.quotas = {q.tenant_id: q for q in quotas}
        self.total_kv_blocks = total_kv_blocks
        self.interactive_kv_watermark = interactive_kv_watermark
        self.batch_kv_watermark = batch_kv_watermark
        self.max_interactive_wait_ms = max_interactive_wait_ms
        self.max_batch_wait_ms = max_batch_wait_ms
        self.decode_weight = decode_weight
        self.base_quantum_tokens = base_quantum_tokens
        self.cluster_service_tokens_per_ms = cluster_service_tokens_per_ms
        self.scheduling_mode = scheduling_mode
        self.enable_admission_control = enable_admission_control

    def run_trace(self, requests: list[InferenceRequest]) -> list[ScheduledOutcome]:
        ordered = sorted(requests, key=lambda r: (r.arrival_ms, r.request_id))
        if self.scheduling_mode == "request_count_fifo":
            return self._run_request_count_fifo(ordered)
        return self._run_service_token_drr(ordered)

    def _run_request_count_fifo(
        self, ordered: list[InferenceRequest]
    ) -> list[ScheduledOutcome]:
        """Naive per-tenant 1-request round-robin without priority lanes or service-token accounting."""
        queues: dict[str, deque[InferenceRequest]] = {
            tid: deque() for tid in self.quotas
        }
        tenant_order = list(self.quotas.keys())
        idx = 0
        clock_ms = 0.0
        active_releases: list[tuple[float, int]] = []
        outcomes: list[ScheduledOutcome] = []

        def used_blocks(now_ms: float) -> int:
            return sum(blocks for rel_ms, blocks in active_releases if rel_ms > now_ms)

        while idx < len(ordered) or any(queues.values()):
            if not any(queues.values()) and idx < len(ordered):
                clock_ms = max(clock_ms, float(ordered[idx].arrival_ms))
            while idx < len(ordered) and ordered[idx].arrival_ms <= clock_ms:
                req = ordered[idx]
                queues[req.tenant_id].append(req)
                idx += 1

            dispatched = False
            for tid in tenant_order:
                if not queues[tid]:
                    continue
                req = queues[tid].popleft()
                active_releases = [
                    (rel, blk) for rel, blk in active_releases if rel > clock_ms
                ]
                req_blocks = req.kv_blocks_required()
                occ = (used_blocks(clock_ms) + req_blocks) / self.total_kv_blocks
                svc_tokens = req.service_tokens(self.decode_weight)
                wait_ms = max(0.0, clock_ms - req.arrival_ms)
                if (
                    self.enable_admission_control
                    and occ > self.interactive_kv_watermark
                ):
                    outcomes.append(
                        ScheduledOutcome(
                            request_id=req.request_id,
                            tenant_id=req.tenant_id,
                            priority_class=req.priority_class,
                            status_code=429,
                            reason="shed_kv_watermark",
                            service_tokens=svc_tokens,
                            ttft_ms=0.0,
                            queue_wait_ms=round(wait_ms, 2),
                            kv_occupancy_ratio=round(occ, 4),
                        )
                    )
                    dispatched = True
                    continue

                prefill_ms = max(8.0, req.prefill_tokens / 48.0)
                exec_ms = svc_tokens / self.cluster_service_tokens_per_ms
                ttft_ms = wait_ms + prefill_ms
                active_releases.append((clock_ms + exec_ms * 5.5, req_blocks))
                clock_ms += exec_ms
                outcomes.append(
                    ScheduledOutcome(
                        request_id=req.request_id,
                        tenant_id=req.tenant_id,
                        priority_class=req.priority_class,
                        status_code=200,
                        reason="admitted",
                        service_tokens=svc_tokens,
                        ttft_ms=round(ttft_ms, 2),
                        queue_wait_ms=round(wait_ms, 2),
                        kv_occupancy_ratio=round(occ, 4),
                    )
                )
                dispatched = True
                while idx < len(ordered) and ordered[idx].arrival_ms <= clock_ms:
                    queues[ordered[idx].tenant_id].append(ordered[idx])
                    idx += 1
            if not dispatched and idx < len(ordered):
                clock_ms = float(ordered[idx].arrival_ms)
        return outcomes

    def _run_service_token_drr(
        self, ordered: list[InferenceRequest]
    ) -> list[ScheduledOutcome]:
        """Priority-separated weighted deficit round-robin measured in service tokens with KV admission shedding."""
        interactive_q: dict[str, deque[InferenceRequest]] = {
            tid: deque() for tid in self.quotas
        }
        batch_q: dict[str, deque[InferenceRequest]] = {
            tid: deque() for tid in self.quotas
        }
        deficits: dict[str, float] = {tid: 0.0 for tid in self.quotas}
        token_buckets: dict[str, float] = {
            tid: float(q.burst_service_tokens) for tid, q in self.quotas.items()
        }
        last_refill_ms = 0.0
        clock_ms = 0.0
        idx = 0
        active_releases: list[tuple[float, int]] = []
        outcomes: list[ScheduledOutcome] = []

        def refill_buckets(now_ms: float) -> None:
            nonlocal last_refill_ms
            dt_sec = max(0.0, (now_ms - last_refill_ms) / 1000.0)
            if dt_sec <= 0.0:
                return
            for tid, quota in self.quotas.items():
                updated = (
                    token_buckets[tid] + dt_sec * quota.sustained_service_tokens_per_sec
                )
                token_buckets[tid] = min(float(quota.burst_service_tokens), updated)
            last_refill_ms = now_ms

        def current_kv_blocks(now_ms: float) -> int:
            return sum(blocks for rel_ms, blocks in active_releases if rel_ms > now_ms)

        def queued_kv_blocks(lane: dict[str, deque[InferenceRequest]]) -> int:
            return sum(req.kv_blocks_required() for q in lane.values() for req in q)

        def pending_service_tokens(lane: dict[str, deque[InferenceRequest]]) -> int:
            return sum(
                req.service_tokens(self.decode_weight)
                for q in lane.values()
                for req in q
            )

        def admit_or_shed(
            req: InferenceRequest, eval_ms: float
        ) -> tuple[bool, str, float]:
            svc = req.service_tokens(self.decode_weight)
            req_blocks = req.kv_blocks_required()
            reserved_blocks = (
                current_kv_blocks(eval_ms)
                + queued_kv_blocks(interactive_q)
                + (queued_kv_blocks(batch_q) if req.priority_class == "batch" else 0)
            )
            occ = (reserved_blocks + req_blocks) / self.total_kv_blocks
            if not self.enable_admission_control:
                return True, "admitted", occ

            watermark = (
                self.interactive_kv_watermark
                if req.priority_class == "interactive"
                else self.batch_kv_watermark
            )
            if occ > watermark:
                return False, "shed_kv_watermark", min(occ, watermark)

            lane_queues = (
                interactive_q if req.priority_class == "interactive" else batch_q
            )
            estimated_wait_ms = (
                pending_service_tokens(lane_queues) / self.cluster_service_tokens_per_ms
            )
            wait_limit = (
                self.max_interactive_wait_ms
                if req.priority_class == "interactive"
                else self.max_batch_wait_ms
            )
            if estimated_wait_ms > wait_limit:
                return False, "shed_queue_wait_slo", min(occ, watermark)

            if req.priority_class == "batch" and token_buckets[req.tenant_id] < svc:
                return False, "shed_tenant_token_quota", min(occ, watermark)
            return True, "admitted", occ

        def enqueue_arrivals(up_to_ms: float) -> None:
            nonlocal idx
            while idx < len(ordered) and ordered[idx].arrival_ms <= up_to_ms:
                req = ordered[idx]
                idx += 1
                refill_buckets(float(req.arrival_ms))
                eval_ms = max(clock_ms, float(req.arrival_ms))
                admitted, reason, occ = admit_or_shed(req, eval_ms)
                svc = req.service_tokens(self.decode_weight)
                if not admitted:
                    outcomes.append(
                        ScheduledOutcome(
                            request_id=req.request_id,
                            tenant_id=req.tenant_id,
                            priority_class=req.priority_class,
                            status_code=429,
                            reason=reason,
                            service_tokens=svc,
                            ttft_ms=0.0,
                            queue_wait_ms=0.0,
                            kv_occupancy_ratio=round(occ, 4),
                        )
                    )
                    continue
                token_buckets[req.tenant_id] = max(
                    0.0, token_buckets[req.tenant_id] - svc
                )
                target = (
                    interactive_q if req.priority_class == "interactive" else batch_q
                )
                target[req.tenant_id].append(req)

        tenant_ids = list(self.quotas.keys())
        while (
            idx < len(ordered) or any(interactive_q.values()) or any(batch_q.values())
        ):
            if (
                not any(interactive_q.values())
                and not any(batch_q.values())
                and idx < len(ordered)
            ):
                clock_ms = max(clock_ms, float(ordered[idx].arrival_ms))
            enqueue_arrivals(clock_ms)

            # Serve interactive lane first via weighted service-token DRR; only serve batch when interactive is empty.
            active_lane = interactive_q if any(interactive_q.values()) else batch_q
            if not any(active_lane.values()):
                continue

            dispatched_in_round = False
            for tid in tenant_ids:
                q = active_lane[tid]
                if not q:
                    deficits[tid] = 0.0
                    continue
                deficits[tid] += self.base_quantum_tokens * self.quotas[tid].weight
                while q:
                    head = q[0]
                    svc = head.service_tokens(self.decode_weight)
                    if deficits[tid] < svc:
                        break
                    q.popleft()
                    deficits[tid] -= svc
                    refill_buckets(clock_ms)
                    active_releases = [
                        (rel, blk) for rel, blk in active_releases if rel > clock_ms
                    ]
                    req_blocks = head.kv_blocks_required()
                    watermark = (
                        self.interactive_kv_watermark
                        if head.priority_class == "interactive"
                        else self.batch_kv_watermark
                    )
                    occ = (
                        current_kv_blocks(clock_ms) + req_blocks
                    ) / self.total_kv_blocks
                    if self.enable_admission_control and occ > watermark:
                        outcomes.append(
                            ScheduledOutcome(
                                request_id=head.request_id,
                                tenant_id=head.tenant_id,
                                priority_class=head.priority_class,
                                status_code=429,
                                reason="shed_kv_watermark",
                                service_tokens=svc,
                                ttft_ms=0.0,
                                queue_wait_ms=round(
                                    max(0.0, clock_ms - head.arrival_ms), 2
                                ),
                                kv_occupancy_ratio=round(occ, 4),
                            )
                        )
                        dispatched_in_round = True
                        continue

                    wait_ms = max(0.0, clock_ms - head.arrival_ms)
                    prefill_ms = max(8.0, head.prefill_tokens / 48.0)
                    # Non-preemptive service: consume the full request work, exactly as the FIFO baseline.
                    exec_ms = svc / self.cluster_service_tokens_per_ms
                    step_advance_ms = exec_ms
                    ttft_ms = wait_ms + prefill_ms
                    active_releases.append((clock_ms + exec_ms * 5.5, req_blocks))
                    clock_ms += step_advance_ms
                    outcomes.append(
                        ScheduledOutcome(
                            request_id=head.request_id,
                            tenant_id=head.tenant_id,
                            priority_class=head.priority_class,
                            status_code=200,
                            reason="admitted",
                            service_tokens=svc,
                            ttft_ms=round(ttft_ms, 2),
                            queue_wait_ms=round(wait_ms, 2),
                            kv_occupancy_ratio=round(occ, 4),
                        )
                    )
                    dispatched_in_round = True
                    enqueue_arrivals(clock_ms)
                    if active_lane is batch_q and any(interactive_q.values()):
                        break
                if active_lane is batch_q and any(interactive_q.values()):
                    break

            if not dispatched_in_round:
                needed = min(
                    (
                        (q[0].service_tokens(self.decode_weight) - deficits[tid])
                        / self.quotas[tid].weight
                        for tid, q in active_lane.items()
                        if q
                    ),
                    default=float(self.base_quantum_tokens),
                )
                boost = max(float(self.base_quantum_tokens), math.ceil(needed))
                for tid, q in active_lane.items():
                    if q:
                        deficits[tid] += boost * self.quotas[tid].weight

        return outcomes


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((p / 100.0) * len(ordered)) - 1))
    return round(ordered[idx], 2)


def build_noisy_neighbor_workload() -> tuple[list[TenantQuota], list[InferenceRequest]]:
    quotas = [
        TenantQuota(
            tenant_id="tenant_chat_pro",
            weight=2.0,
            burst_service_tokens=48_000,
            sustained_service_tokens_per_sec=180_000,
            priority_class="interactive",
        ),
        TenantQuota(
            tenant_id="tenant_ide_assist",
            weight=1.5,
            burst_service_tokens=36_000,
            sustained_service_tokens_per_sec=140_000,
            priority_class="interactive",
        ),
        TenantQuota(
            tenant_id="tenant_batch_rag",
            weight=1.0,
            burst_service_tokens=28_000,
            sustained_service_tokens_per_sec=60_000,
            priority_class="batch",
        ),
    ]
    requests: list[InferenceRequest] = []
    # Tenant batch_rag floods the gateway at t=0..170ms with 18 heavy document-extraction requests.
    for i in range(18):
        requests.append(
            InferenceRequest(
                request_id=f"batch-{i:02d}",
                tenant_id="tenant_batch_rag",
                arrival_ms=i * 10,
                prefill_tokens=3200,
                decode_tokens=350,
                priority_class="batch",
            )
        )
    # Interactive tenants send short, latency-sensitive requests across t=5..365ms.
    for i in range(24):
        requests.append(
            InferenceRequest(
                request_id=f"chat-{i:02d}",
                tenant_id="tenant_chat_pro",
                arrival_ms=5 + i * 15,
                prefill_tokens=280,
                decode_tokens=90,
                priority_class="interactive",
            )
        )
    for i in range(18):
        requests.append(
            InferenceRequest(
                request_id=f"ide-{i:02d}",
                tenant_id="tenant_ide_assist",
                arrival_ms=8 + i * 20,
                prefill_tokens=420,
                decode_tokens=60,
                priority_class="interactive",
            )
        )
    return quotas, requests


def summarize_outcomes(outcomes: list[ScheduledOutcome]) -> dict[str, object]:
    interactive_ok = [
        o
        for o in outcomes
        if o.priority_class == "interactive" and o.status_code == 200
    ]
    batch_ok = [
        o for o in outcomes if o.priority_class == "batch" and o.status_code == 200
    ]
    shed = [o for o in outcomes if o.status_code == 429]
    by_tenant: dict[str, dict[str, object]] = {}
    for tid in sorted({o.tenant_id for o in outcomes}):
        tenant_rows = [o for o in outcomes if o.tenant_id == tid]
        admitted = [o for o in tenant_rows if o.status_code == 200]
        rejected = [o for o in tenant_rows if o.status_code == 429]
        by_tenant[tid] = {
            "submitted": len(tenant_rows),
            "admitted": len(admitted),
            "shed_429": len(rejected),
            "admitted_service_tokens": sum(o.service_tokens for o in admitted),
            "p50_ttft_ms": percentile([o.ttft_ms for o in admitted], 50),
            "p99_ttft_ms": percentile([o.ttft_ms for o in admitted], 99),
        }
    shed_reasons: dict[str, int] = {}
    for row in shed:
        shed_reasons[row.reason] = shed_reasons.get(row.reason, 0) + 1
    return {
        "total_requests": len(outcomes),
        "admitted_requests": len(interactive_ok) + len(batch_ok),
        "shed_429_requests": len(shed),
        "interactive_p50_ttft_ms": percentile([o.ttft_ms for o in interactive_ok], 50),
        "interactive_p99_ttft_ms": percentile([o.ttft_ms for o in interactive_ok], 99),
        "batch_p99_ttft_ms": percentile([o.ttft_ms for o in batch_ok], 99),
        "peak_kv_occupancy_ratio": round(
            max((o.kv_occupancy_ratio for o in outcomes), default=0.0), 4
        ),
        "shed_reasons": shed_reasons,
        "tenants": by_tenant,
    }


def simulate_noisy_neighbor() -> dict[str, object]:
    quotas, workload = build_noisy_neighbor_workload()
    naive_scheduler = MultiTenantScheduler(
        quotas,
        scheduling_mode="request_count_fifo",
        enable_admission_control=False,
    )
    protected_scheduler = MultiTenantScheduler(
        quotas,
        scheduling_mode="service_token_drr",
        enable_admission_control=True,
    )
    naive_outcomes = naive_scheduler.run_trace(workload)
    protected_outcomes = protected_scheduler.run_trace(workload)
    return {
        "experiment": "multi-tenant-service-token-drr-and-admission-control",
        "decode_weight": 4,
        "interactive_ttft_slo_ms": 500.0,
        "quotas": [asdict(q) for q in quotas],
        "comparison": {
            "request_count_no_admission": summarize_outcomes(naive_outcomes),
            "service_token_drr_with_admission": summarize_outcomes(protected_outcomes),
        },
        "sample_decisions": [asdict(o) for o in protected_outcomes[:10]],
    }


def main() -> None:
    report = simulate_noisy_neighbor()
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
