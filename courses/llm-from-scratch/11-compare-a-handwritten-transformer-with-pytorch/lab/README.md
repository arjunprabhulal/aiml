# Handwritten transformer to PyTorch

Python 3.12+, CPU PyTorch. Create an isolated environment and install
`python -m pip install -r requirements.txt`. The pin records the library used for
this execution; choose an installation supported on your platform from PyTorch.
No pretrained model, GPU, data download or paid service is used.

Run from this directory:

    python bridge.py
    python -m unittest -v test_bridge.py

`python bridge.py --record` deliberately replaces result.json. To retain command
output too, redirect that command to run-output.txt. `python report.py` renders
report.html from the saved result; opening it does not execute a model.

vendor/model.py is byte-identical to the published transformer-block lab's
model.py. Its inherited docstring is original source, not a cross-version
numerical guarantee for this bridge. The bridge tests the actual CPU float64
execution with atol=1e-10 and rtol=1e-8; other devices/dtypes are untested.
The synthetic integer sequence repeats token 1, leaves token rows unused and
uses fewer positions than the table contains. All 18 parameter tensors are
compared, including embedding accumulation and zero gradients in unused rows.

Both tensor paths use the same parameter values, mean cross-entropy, pre-LN
EPS=1e-5, ReLU, one attention head and causal scale 1/sqrt(4). SDPA explicitly
sets dropout_p=0 and forces SDPBackend.MATH. This does not benchmark fused GPU
attention, train a model or verify generation quality. Every tensor is on CPU.
Fault probes remove the causal mask, change attention scale and change layer-norm
epsilon. Their measured differences are retained, not described as API errors.

Official references checked 2026-10-24 against PyTorch 2.14 documentation:
- https://docs.pytorch.org/docs/2.14/generated/torch.nn.functional.scaled_dot_product_attention.html
  Signature/equivalent implementation: causal mask, scale and dropout_p.
- https://docs.pytorch.org/docs/2.14/generated/torch.nn.functional.layer_norm.html
  normalized_shape and eps argument.
- https://docs.pytorch.org/docs/2.14/generated/torch.nn.functional.cross_entropy.html
  Unnormalized logits, class-index targets and mean reduction.
