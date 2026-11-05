# Budget cache transfer before splitting inference pools

Payload calculator and explicit disaggregation/MoE cost scenarios. No networked KV transfer, multi-GPU model execution, or throughput improvement was measured.

## Run

Use Python 3.12 or later. From this directory:

```sh
python3 lab.py
python3 -m unittest -v test_lab.py
```

`ModelKVSpec` calculates transfer payload, and `evaluate_pd_disaggregation()` exposes bandwidth and overlap assumptions. The MoE calculation is a separate scenario model, not a DeepSeek deployment. The code does not move tensors between real GPUs or validate a KV connector.

## Interpretation

Separating pools can help control phase-specific latency, but adds network work, routing, failure recovery, and capacity coordination. It is not a general throughput improvement. Overlap may hide only part of transfer time. MoE expert placement and replication add another independent tradeoff.

## Sources

- vLLM disaggregated prefill boundaries: https://docs.vllm.ai/en/latest/features/disagg_prefill/
- SGLang prefill/decode disaggregation: https://docs.sglang.ai/advanced_features/pd_disaggregation.html
- vLLM expert parallel deployment: https://docs.vllm.ai/en/latest/serving/expert_parallel_deployment/
