# Compare eager and compiled normalization on real tensors

Fresh Metal eager-versus-compiled tensor experiment. CUDA/Triton execution, kernel traffic, and whole-model acceleration are unmeasured.

## Run

Use Python 3.12 or later. From this directory:

```sh
python3 lab.py
python3 -m unittest -v test_lab.py
```

`fusion_live.py` creates actual tensors, warms both paths, checks maximum absolute output difference, and records repeated synchronized timings for several shapes, including an irregular row width. It replaces the unexecuted Triton snippet as the tested implementation.

## Interpretation

Fusion can reduce dispatch and data movement but increase register pressure or compilation overhead. Small and large shapes can behave differently. A reduction in modeled tensor accesses is not an equal reduction in model latency; normalization may be a small fraction of the critical path.

## Sources

- MLX compilation and fusion: https://ml-explore.github.io/mlx/build/html/usage/compile.html
- Triton normalization implementation patterns: https://triton-lang.org/main/getting-started/tutorials/05-layer-norm.html
- RMSNorm authors’ formulation: https://arxiv.org/abs/1910.07467

## Optional fresh execution

```sh
python3 -m venv .venv
.venv/bin/python -m pip install mlx==0.32.4
.venv/bin/python fusion_live.py --output new-fusion-run.json
```

Run model commands in the pinned runtime from the first lesson. CPU and Metal results are distinct; no NVIDIA execution is claimed.
