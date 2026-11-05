"""Capacity and cost arithmetic with explicit evidence requirements. No invented latency or quality scores."""

from dataclasses import dataclass, asdict
import json
import math


@dataclass(frozen=True)
class CapacityEvidence:
    sustainable_requests_per_second: float
    hourly_replica_cost: float
    workload: str
    latency_and_quality_accepted: bool
    record_reference: str

    def validate(self):
        if self.sustainable_requests_per_second <= 0 or self.hourly_replica_cost < 0:
            raise ValueError("Invalid rate or price")
        if not self.latency_and_quality_accepted or not self.record_reference:
            raise ValueError("Supply accepted benchmark evidence before sizing")


def plan(daily_requests, peak_to_average, evidence, reserve_replicas=1):
    evidence.validate()
    if daily_requests <= 0 or peak_to_average < 1 or reserve_replicas < 0:
        raise ValueError("Invalid traffic or reserve")
    peak_rps = daily_requests / 86400 * peak_to_average
    active = math.ceil(peak_rps / evidence.sustainable_requests_per_second)
    return {
        "daily_requests_assumed": daily_requests,
        "peak_to_average_assumed": peak_to_average,
        "peak_rps": round(peak_rps, 6),
        "active_replicas": active,
        "reserve_replicas": reserve_replicas,
        "total_replicas": active + reserve_replicas,
        "peak_hour_cost": round(
            (active + reserve_replicas) * evidence.hourly_replica_cost, 2
        ),
        "evidence": asdict(evidence),
        "limits": "Arithmetic assumes independent replicas and identical workload. Load-test routing, shared dependencies, cold starts and a lost replica before deployment.",
    }


def main():
    # Explicit controlled fixture: demonstrates arithmetic, not a real fleet recommendation.
    fixture = CapacityEvidence(
        2.5,
        1.0,
        "controlled calculator test workload",
        True,
        "unit-test fixture; not measured serving capacity",
    )
    print(
        json.dumps(
            {
                "execution_mode": "capacity arithmetic over labeled test inputs",
                "base": plan(100000, 3, fixture),
                "higher_peak": plan(100000, 5, fixture),
                "limits": "No million-user deployment or percentage cost saving is claimed. Replace the test inputs with accepted, workload-matched measurements.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
