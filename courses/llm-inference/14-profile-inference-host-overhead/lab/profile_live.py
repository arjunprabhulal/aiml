"""Collect actual CPU operator events around synchronized local model forwards on Metal."""

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model-path", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    import torch, transformers
    from transformers import AutoTokenizer, AutoModelForCausalLM

    tokenizer = AutoTokenizer.from_pretrained(a.model_path, local_files_only=True)
    model = (
        AutoModelForCausalLM.from_pretrained(
            a.model_path,
            local_files_only=True,
            dtype=torch.float32,
            attn_implementation="eager",
        )
        .eval()
        .to("mps")
    )
    ids = tokenizer(
        "A code assistant retrieves relevant functions before generating a patch.",
        return_tensors="pt",
    )["input_ids"].to("mps")
    with torch.inference_mode():
        model(ids, use_cache=True)
    torch.mps.synchronize()
    start = time.perf_counter()
    with torch.profiler.profile(
        activities=[torch.profiler.ProfilerActivity.CPU], record_shapes=True
    ) as prof:
        with torch.inference_mode():
            result = model(ids, use_cache=True)
            torch.mps.synchronize()
    elapsed = (time.perf_counter() - start) * 1000
    rows = sorted(
        prof.key_averages(), key=lambda x: x.self_cpu_time_total, reverse=True
    )[:12]
    result = {
        "execution_mode": "fresh local inference; CPU operator profiler around Metal execution",
        "environment": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
        "model_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "profiled_wall_ms": round(elapsed, 3),
        "operators": [
            {
                "name": x.key,
                "calls": x.count,
                "self_cpu_us": round(x.self_cpu_time_total, 3),
            }
            for x in rows
        ],
        "limits": "CPU operator durations include dispatch and synchronization overhead, not GPU kernel duration or occupancy. Profiling changes runtime; compare unprofiled repetitions separately.",
    }
    Path(a.output).write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
