# Quantize a model and evaluate the regression

Fresh CPU INT8 model execution and recorded development-text likelihoods. Separate scalar quantization examples do not execute GPU quantized kernels.

## Run

Use Python 3.12 or later. From this directory:

```sh
python3 lab.py
python3 -m unittest -v test_lab.py
```

`quantize_live.py` loads the pinned model, scores the same development texts, converts real linear modules, and records the new scores. It uses a pinned legacy PyTorch quantization API whose deprecation warning is preserved in the run notes; it is an investigation of a candidate, not a recommended new deployment API.

## Interpretation

A smaller representation is useful only if the runtime executes it efficiently and the application accepts its output quality. This experiment produced a regression; the candidate is not accepted. CPU quantization results do not establish FP8 or INT4 behavior on a GPU. The separate scalar-format experiment remains a way to inspect rounding, not to benchmark those formats.

## Sources

- PyTorch quantization documentation and migration notice: https://docs.pytorch.org/docs/2.14/quantization.html
- vLLM quantization compatibility: https://docs.vllm.ai/en/latest/features/quantization/
- Official model configuration: https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/blob/7ae557604adf67be50417f59c2c2f167def9a775/config.json

## Optional fresh execution

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-live.txt
.venv/bin/python quantize_live.py --model-path /path/to/downloaded/model --output new-quantization-run.json
```

Run model commands in the pinned runtime from the first lesson. CPU and Metal results are distinct; no NVIDIA execution is claimed.
