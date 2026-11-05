"""Simulate replica startup and evaluate supplied canary samples; no live fleet is controlled."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from typing import Literal

ScalingMode = Literal["reactive_gpu_util", "leading_kv_and_velocity"]


@dataclass(frozen=True)
class AutoscalerConfig:
    mode: ScalingMode
    min_replicas: int = 4
    max_replicas: int = 16
    target_kv_utilization: float = 0.68
    reactive_gpu_util_threshold: float = 0.88
    tokens_per_replica_capacity: int = 18_000
    cold_start_seconds: int = 180
    warm_standby_replicas: int = 0
    fast_weight_stream_seconds: int = 22
    ttft_slo_ms: float = 450.0

    def __post_init__(self) -> None:
        if self.min_replicas <= 0 or self.max_replicas < self.min_replicas:
            raise ValueError("Invalid replica bounds")
        if not (0.1 <= self.target_kv_utilization <= 0.95):
            raise ValueError("target_kv_utilization must be in [0.1, 0.95]")


@dataclass(frozen=True)
class CanaryStageSample:
    stage_percent: int
    requests_evaluated: int
    baseline_p99_tpot_ms: float
    canary_p99_tpot_ms: float
    baseline_exact_match: float
    canary_exact_match: float
    canary_error_rate: float

    def __post_init__(self):
        if not 1 <= self.stage_percent <= 100 or self.requests_evaluated < 1:
            raise ValueError("Canary sample needs traffic and observations")
        rates = [
            self.baseline_exact_match,
            self.canary_exact_match,
            self.canary_error_rate,
        ]
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in rates):
            raise ValueError("Invalid canary rate")
        if any(
            not math.isfinite(v) or v < 0
            for v in [self.baseline_p99_tpot_ms, self.canary_p99_tpot_ms]
        ):
            raise ValueError("Invalid canary latency")


@dataclass(frozen=True)
class CanaryGate:
    max_tpot_regression_ms: float = 6.0
    max_tpot_ceiling_ms: float = 45.0
    max_quality_drop: float = 0.015
    max_error_rate: float = 0.005

    def evaluate_stage(self, sample: CanaryStageSample) -> dict[str, object]:
        tpot_delta = sample.canary_p99_tpot_ms - sample.baseline_p99_tpot_ms
        quality_drop = sample.baseline_exact_match - sample.canary_exact_match
        reasons: list[str] = []
        if (
            sample.canary_p99_tpot_ms > self.max_tpot_ceiling_ms
            or tpot_delta > self.max_tpot_regression_ms
        ):
            reasons.append("tpot_slo_regression")
        if quality_drop > self.max_quality_drop:
            reasons.append("quality_score_regression")
        if sample.canary_error_rate > self.max_error_rate:
            reasons.append("error_rate_breach")
        passed = len(reasons) == 0
        return {
            "stage_percent": sample.stage_percent,
            "requests_evaluated": sample.requests_evaluated,
            "decision": "promote" if passed else "rollback_to_0_percent",
            "passed": passed,
            "tpot_delta_ms": tpot_delta,
            "quality_drop": quality_drop,
            "canary_error_rate": sample.canary_error_rate,
            "reasons": reasons,
        }

    def run_rollout(self, stages: list[CanaryStageSample]) -> dict[str, object]:
        percents = [s.stage_percent for s in stages]
        if percents != sorted(set(percents)):
            raise ValueError("Canary stages must increase")
        history: list[dict[str, object]] = []
        active_traffic_percent = 0
        rolled_back = False
        rollback_reason: list[str] = []
        for stage in stages:
            verdict = self.evaluate_stage(stage)
            history.append(verdict)
            if not verdict["passed"]:
                rolled_back = True
                rollback_reason = list(verdict["reasons"])
                active_traffic_percent = 0
                break
            active_traffic_percent = stage.stage_percent
        return {
            "completed_100_percent": (
                not rolled_back and active_traffic_percent == 100
            ),
            "rolled_back": rolled_back,
            "final_canary_traffic_percent": active_traffic_percent,
            "rollback_reasons": rollback_reason,
            "stages": history,
        }


def build_traffic_spike_timeline() -> list[tuple[int, int]]:
    """Returns (second, inflight_token_demand) across a 300-second traffic surge."""
    return [
        (0, 48_000),
        (20, 52_000),
        (40, 74_000),
        (60, 108_000),
        (80, 142_000),
        (100, 168_000),
        (120, 176_000),
        (140, 172_000),
        (160, 160_000),
        (180, 144_000),
        (200, 124_000),
        (220, 102_000),
        (240, 84_000),
        (260, 68_000),
        (280, 56_000),
        (300, 50_000),
    ]


def simulate_autoscaler(
    config: AutoscalerConfig,
    timeline: list[tuple[int, int]] | None = None,
) -> dict[str, object]:
    series = timeline if timeline is not None else build_traffic_spike_timeline()
    ready_replicas = config.min_replicas
    warm_pool = config.warm_standby_replicas
    pending_boots: list[tuple[int, int]] = []  # (ready_at_sec, count)
    prev_demand = series[0][1]
    prev_sec = series[0][0]
    steps: list[dict[str, object]] = []
    slo_breach_windows = 0

    for sec, demand_tokens in series:
        # Promote any replicas whose weight loading completed by `sec`.
        newly_ready = sum(count for ready_at, count in pending_boots if ready_at <= sec)
        pending_boots = [
            (ready_at, count) for ready_at, count in pending_boots if ready_at > sec
        ]
        ready_replicas += newly_ready
        inflight_booting = sum(count for _, count in pending_boots)

        total_kv_capacity = ready_replicas * config.tokens_per_replica_capacity
        kv_util = demand_tokens / max(1, total_kv_capacity)
        # GPU compute utilization saturates early under continuous batching, hiding queue growth.
        gpu_compute_util = min(0.99, 0.52 + 0.38 * min(1.25, kv_util))

        dt = max(1, sec - prev_sec)
        velocity_tokens_per_sec = max(0.0, (demand_tokens - prev_demand) / dt)
        prev_demand = demand_tokens
        prev_sec = sec

        if config.mode == "reactive_gpu_util":
            # Reactive policy waits until GPU utilization exceeds 88% and pays the full 180s cold start.
            if gpu_compute_util >= config.reactive_gpu_util_threshold:
                desired = math.ceil(
                    demand_tokens / (config.tokens_per_replica_capacity * 0.80)
                )
            else:
                desired = ready_replicas
            desired = min(config.max_replicas, max(config.min_replicas, desired))
            needed = max(0, desired - (ready_replicas + inflight_booting))
            if needed > 0:
                pending_boots.append((sec + config.cold_start_seconds, needed))
        else:
            # Leading-indicator policy projects demand across the fast weight-streaming window (22s).
            projected_demand = (
                demand_tokens
                + velocity_tokens_per_sec * config.fast_weight_stream_seconds
            )
            desired = math.ceil(
                projected_demand
                / (config.tokens_per_replica_capacity * config.target_kv_utilization)
            )
            desired = min(config.max_replicas, max(config.min_replicas, desired))
            needed = max(0, desired - (ready_replicas + inflight_booting))
            if needed > 0:
                from_warm = min(warm_pool, needed)
                if from_warm > 0:
                    warm_pool -= from_warm
                    pending_boots.append((sec + 20, from_warm))
                remaining = needed - from_warm
                if remaining > 0:
                    pending_boots.append(
                        (sec + config.fast_weight_stream_seconds, remaining)
                    )
                # This finite initial standby pool is not replenished in the simulation.

        # Recompute effective KV utilization and queue delay at `sec`.
        overload_ratio = max(0.0, kv_util - 0.85)
        p99_ttft_ms = round(
            140.0 + 190.0 * min(kv_util, 0.85) + 2600.0 * (overload_ratio**1.35), 2
        )
        if p99_ttft_ms > config.ttft_slo_ms:
            slo_breach_windows += 1

        steps.append(
            {
                "sec": sec,
                "demand_tokens": demand_tokens,
                "ready_replicas": ready_replicas,
                "booting_replicas": sum(count for _, count in pending_boots),
                "demand_to_kv_capacity_ratio": round(kv_util, 4),
                "kv_utilization": round(min(1.0, kv_util), 4),
                "warm_standby_remaining": warm_pool,
                "gpu_compute_utilization": round(gpu_compute_util, 4),
                "p99_ttft_ms": p99_ttft_ms,
                "slo_breached": p99_ttft_ms > config.ttft_slo_ms,
            }
        )

    return {
        "mode": config.mode,
        "cold_start_seconds": (
            config.cold_start_seconds
            if config.mode == "reactive_gpu_util"
            else config.fast_weight_stream_seconds
        ),
        "peak_kv_utilization": max(s["demand_to_kv_capacity_ratio"] for s in steps),
        "peak_p99_ttft_ms": max(s["p99_ttft_ms"] for s in steps),
        "max_ready_replicas": max(s["ready_replicas"] for s in steps),
        "slo_breach_windows": slo_breach_windows,
        "timeline": steps,
    }


def simulate_cold_start_and_rollout() -> dict[str, object]:
    reactive_cfg = AutoscalerConfig(
        mode="reactive_gpu_util",
        cold_start_seconds=180,
        warm_standby_replicas=0,
    )
    leading_cfg = AutoscalerConfig(
        mode="leading_kv_and_velocity",
        target_kv_utilization=0.68,
        warm_standby_replicas=2,
        fast_weight_stream_seconds=22,
    )
    reactive_run = simulate_autoscaler(reactive_cfg)
    leading_run = simulate_autoscaler(leading_cfg)

    gate = CanaryGate(
        max_tpot_regression_ms=6.0,
        max_tpot_ceiling_ms=45.0,
        max_quality_drop=0.015,
        max_error_rate=0.005,
    )
    # Rollout 1: Defective INT4 calibration that passes 5% traffic but regresses p99 TPOT & quality at 25% load.
    defective_canary_stages = [
        CanaryStageSample(
            stage_percent=5,
            requests_evaluated=250,
            baseline_p99_tpot_ms=28.4,
            canary_p99_tpot_ms=31.2,
            baseline_exact_match=0.842,
            canary_exact_match=0.834,
            canary_error_rate=0.001,
        ),
        CanaryStageSample(
            stage_percent=25,
            requests_evaluated=1200,
            baseline_p99_tpot_ms=29.0,
            canary_p99_tpot_ms=48.6,
            baseline_exact_match=0.842,
            canary_exact_match=0.814,
            canary_error_rate=0.002,
        ),
        CanaryStageSample(
            stage_percent=100,
            requests_evaluated=5000,
            baseline_p99_tpot_ms=29.1,
            canary_p99_tpot_ms=52.0,
            baseline_exact_match=0.842,
            canary_exact_match=0.811,
            canary_error_rate=0.003,
        ),
    ]
    # Rollout 2: Validated FP8 build that passes all 3 stages (5% -> 25% -> 100%).
    healthy_canary_stages = [
        CanaryStageSample(
            stage_percent=5,
            requests_evaluated=250,
            baseline_p99_tpot_ms=28.4,
            canary_p99_tpot_ms=24.8,
            baseline_exact_match=0.842,
            canary_exact_match=0.839,
            canary_error_rate=0.001,
        ),
        CanaryStageSample(
            stage_percent=25,
            requests_evaluated=1200,
            baseline_p99_tpot_ms=29.0,
            canary_p99_tpot_ms=25.6,
            baseline_exact_match=0.842,
            canary_exact_match=0.838,
            canary_error_rate=0.001,
        ),
        CanaryStageSample(
            stage_percent=100,
            requests_evaluated=5000,
            baseline_p99_tpot_ms=29.1,
            canary_p99_tpot_ms=26.1,
            baseline_exact_match=0.842,
            canary_exact_match=0.838,
            canary_error_rate=0.001,
        ),
    ]

    return {
        "experiment": "gpu-autoscaling-cold-starts-and-canary-rollout",
        "scenario_scope": "Combined signal, startup-delay and initial-standby scenarios; does not isolate signal choice",
        "cold_start_breakdown_seconds": {
            "unoptimized_container_and_safetensors_init": {
                "node_alloc_and_image_pull": 75,
                "cuda_context_and_nccl_init": 35,
                "remote_weight_download_and_mmap": 70,
                "total_seconds": 180,
            },
            "pre_pulled_image_plus_object_memory_tensor_stream": {
                "warm_container_init": 4,
                "cuda_graph_cache_restore": 6,
                "direct_nvme_or_rdma_tensor_stream": 12,
                "total_seconds": 22,
            },
        },
        "autoscaling_comparison": {
            "reactive_gpu_util": reactive_run,
            "leading_kv_and_velocity": leading_run,
        },
        "canary_rollouts": {
            "defective_int4_build": gate.run_rollout(defective_canary_stages),
            "validated_fp8_build": gate.run_rollout(healthy_canary_stages),
        },
        "canary_gate_policy": asdict(gate),
    }


def main() -> None:
    print(
        json.dumps(
            {
                "execution_mode": "CPU algorithm with controlled inputs; any latency/capacity coefficients are assumptions",
                **simulate_cold_start_and_rollout(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
