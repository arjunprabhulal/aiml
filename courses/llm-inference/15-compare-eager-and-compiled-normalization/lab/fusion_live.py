"""Compare eager and compiled RMS normalization on Metal; no CUDA/Triton execution claimed."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import statistics
import time
from pathlib import Path


def main():
    import mlx.core as mx

    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    a = p.parse_args()
    mx.random.seed(0)

    def norm(x, r, w):
        z = x + r
        return z * mx.rsqrt(mx.mean(z * z, axis=-1, keepdims=True) + 1e-6) * w

    compiled = mx.compile(norm)
    cases = []
    for rows, width in [(1, 896), (32, 896), (32, 1003)]:
        x = mx.random.normal((rows, width))
        r = mx.random.normal((rows, width))
        w = mx.ones((width,))
        mx.eval(x, r, w)
        reference = norm(x, r, w)
        candidate = compiled(x, r, w)
        mx.eval(reference, candidate)
        error = float(mx.max(mx.abs(reference - candidate)).item())
        timings = {}
        for name, fn in [("eager", norm), ("compiled", compiled)]:
            for _ in range(3):
                mx.eval(fn(x, r, w))
            samples = []
            for _ in range(20):
                mx.synchronize()
                start = time.perf_counter()
                out = fn(x, r, w)
                mx.eval(out)
                mx.synchronize()
                samples.append((time.perf_counter() - start) * 1000)
            timings[name] = {
                "median_ms": round(statistics.median(samples), 6),
                "samples_ms": [round(s, 6) for s in samples],
            }
        cases.append(
            {
                "rows": rows,
                "width": width,
                "dtype": "float32",
                "max_abs_error": error,
                "timings": timings,
            }
        )
    result = {
        "execution_mode": "fresh Metal tensor execution; eager versus MLX compiled expression",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "mlx": importlib.metadata.version("mlx"),
        },
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": cases,
        "limits": "Expression compilation may fuse operations. No kernel trace or measured HBM byte count; no whole-model, CUDA or Triton speedup claim.",
    }
    Path(a.output).write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
