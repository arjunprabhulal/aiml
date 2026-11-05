# Benchmark streaming inference under load

Live requests to the local model endpoint, plus a separate generic scheduling simulation. No vLLM, SGLang, or TensorRT-LLM benchmark was executed.

## Run

Use Python 3.12 or later. From this directory:

```sh
python3 lab.py
python3 -m unittest -v test_lab.py
```

`benchmark.py` sends real HTTP requests at a configured offered rate. It caps client concurrency, counts locally shed requests, and retains server errors. `lab.py` separately models arrivals using generic scenarios; its coefficients are test inputs, not vLLM, SGLang, or TensorRT-LLM measurements.

## Interpretation

More offered load can increase throughput until queueing and rejection dominate. A bounded queue prevents unlimited waiting but rejects work. An unbounded client-side executor can hide the server's saturation by queueing requests before transmission; this runner discloses local saturation instead.

## Sources

- vLLM serving benchmark CLI: https://docs.vllm.ai/en/latest/cli/bench/serve/
- TensorRT-LLM benchmark metric definitions: https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/commands/trtllm-serve/run-benchmark-with-trtllm-serve.md
- AWS endpoint load-testing workflow: https://docs.aws.amazon.com/sagemaker/latest/dg/endpoint-scaling-loadtest.html

## Optional fresh execution

```sh
python3 benchmark.py --url http://127.0.0.1:8766/generate --requests 6 --rate 2 --output new-http-run.json
```

Run model commands in the pinned runtime from the first lesson. CPU and Metal results are distinct; no NVIDIA execution is claimed.
