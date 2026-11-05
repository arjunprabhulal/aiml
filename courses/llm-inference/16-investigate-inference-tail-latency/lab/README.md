# Investigate inference tail latency with request records

Executable telemetry aggregation over controlled log fixtures; diagnosis labels are test hypotheses, not a recorded GPU incident.

## Run

Use Python 3.12 or later. From this directory:

```sh
python3 lab.py
python3 -m unittest -v test_lab.py
```

`diagnose_p99_spike()` aggregates request records and returns a rule-based interpretation. The controlled windows test how outliers and queueing affect the report. The real HTTP benchmark from the earlier lesson provides a separate small request record with both successes and overloads.

## Interpretation

A tight admission limit can lower latency among accepted requests while rejecting more users. Report offered, accepted, failed, and rejected counts together. A small sample’s maximum is not a stable estimate of production p99, and a single watermark cannot fit every model and workload.

## Sources

- vLLM metrics design: https://docs.vllm.ai/en/latest/design/metrics/
- SGLang production metrics: https://docs.sglang.ai/references/production_metrics.html
