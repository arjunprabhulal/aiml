# Protect interactive requests from noisy neighbors

Actual queue and admission-policy implementation with a deterministic service-cost model. No authentication service, multi-tenant GPU deployment, or billing system.

## Run

Use Python 3.12 or later. From this directory:

```sh
python3 lab.py
python3 -m unittest -v test_lab.py
```

`MultiTenantScheduler` implements tenant queues, token-budget accounting, priority selection, and a cache-capacity gate. Its execution times and occupancy are modeled. The real HTTP server earlier demonstrates actual bounded admission and 429 responses; this scheduler is not wired into that model engine.

## Interpretation

Protecting an interactive lane can reduce batch throughput or starve background work unless the policy reserves service for it. Rejecting early preserves capacity but pushes retry and backoff behavior onto clients. Estimated work should be reconciled with actual usage rather than trusted as a billable measurement.

## Sources

- Linux fair queueing and DRR implementation: https://man7.org/linux/man-pages/man8/tc-drr.8.html
- Google Cloud inference-aware autoscaling signals: https://docs.cloud.google.com/kubernetes-engine/docs/best-practices/machine-learning/inference/autoscaling
