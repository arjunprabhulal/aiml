# Explain tiled attention and verify its output

CPU attention implementation and logical-access accounting, compared with a direct numerical reference. No FlashAttention GPU benchmark or measured HBM traffic.

## Run

Use Python 3.12 or later. From this directory:

```sh
python3 lab.py
python3 -m unittest -v test_lab.py
```

`tiled_flash_attention()` is a readable CPU implementation of the online-softmax mechanism. It checks causal masking and irregular tile sizes against `standard_attention()`. The access calculator counts repeated K/V reads in its chosen loop order; it no longer claims that every tensor is read once from device memory.

## Interpretation

Tiling reduces intermediate storage and can improve data movement on a supported GPU kernel, but tile size, register pressure, cache reuse, precision, and backend support matter. A compulsory-byte lower bound is not actual HBM traffic. Measure the selected runtime backend before claiming a FlashAttention speedup.

## Sources

- Triton fused-attention implementation: https://triton-lang.org/main/getting-started/tutorials/06-fused-attention.html
- PyTorch attention backend selection: https://docs.pytorch.org/docs/2.14/generated/torch.nn.functional.scaled_dot_product_attention.html
