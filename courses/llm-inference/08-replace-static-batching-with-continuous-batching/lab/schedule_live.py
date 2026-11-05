"""Real cooperative request scheduling. Serial forwards, not fused continuous batching."""

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path


def execute(decoder, jobs, policy, chunk_size=None, max_active=2):
    if policy not in ["fifo", "interleave"]:
        raise ValueError("Unknown policy")
    if max_active < 1:
        raise ValueError("Active capacity must be positive")
    torch = decoder.torch
    waiting = list(jobs)
    active = []
    finished = []
    start = time.perf_counter()
    while waiting or active:
        capacity = 1 if policy == "fifo" else max_active
        while waiting and len(active) < capacity:
            job = waiting.pop(0)
            active.append(
                {
                    "id": job["id"],
                    "ids": decoder.encode(job["prompt"]),
                    "prompt": job["prompt"],
                    "limit": job["limit"],
                    "cursor": 0,
                    "cache": None,
                    "token": None,
                    "emitted": [],
                    "arrivals": [],
                }
            )
        # Ready decodes run before the next prompt segment. Model forwards remain serial.
        for state in sorted(active, key=lambda s: not bool(s["emitted"])):
            if state["cursor"] < state["ids"].shape[-1]:
                end = min(
                    state["ids"].shape[-1],
                    state["cursor"] + (chunk_size or state["ids"].shape[-1]),
                )
                inputs = state["ids"][:, state["cursor"] : end]
                state["cursor"] = end
            else:
                inputs = state["token"]
            result = decoder._forward(inputs, state["cache"])
            state["cache"] = result.past_key_values
            if state["cursor"] < state["ids"].shape[-1]:
                continue
            state["token"] = result.logits[:, -1].argmax(-1, keepdim=True)
            decoder.sync()
            token = int(state["token"].item())
            state["emitted"].append(token)
            state["arrivals"].append((time.perf_counter() - start) * 1000)
            eos = decoder.model.generation_config.eos_token_id
            eos = eos if isinstance(eos, list) else [eos]
            if len(state["emitted"]) >= state["limit"] or token in eos:
                times = state["arrivals"]
                finished.append(
                    {
                        "id": state["id"],
                        "prompt": state["prompt"],
                        "output_ids": state["emitted"],
                        "text": decoder.tokenizer.decode(
                            state["emitted"], skip_special_tokens=True
                        ),
                        "ttft_ms": round(times[0], 3),
                        "completion_ms": round(times[-1], 3),
                        "max_gap_ms": round(
                            max((b - a for a, b in zip(times, times[1:])), default=0), 3
                        ),
                    }
                )
                state["cache"] = None
                active.remove(state)
    decoder.sync()
    return {
        "policy": policy,
        "chunk_size": chunk_size,
        "max_active": max_active,
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
        "requests": sorted(finished, key=lambda x: x["id"]),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model-path", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    from live_inference import LocalDecoder, MODEL_ID, MODEL_REVISION
    import torch, transformers

    d = LocalDecoder(a.model_path, "mps")
    d.run("Explain a cache.", max_new_tokens=4)
    jobs = [
        {
            "id": "long-document",
            "prompt": ("Source files define functions and their dependencies. " * 24)
            + " Summarize the use of caching.",
            "limit": 16,
        },
        {
            "id": "interactive-a",
            "prompt": "Explain cache invalidation in one sentence.",
            "limit": 8,
        },
        {
            "id": "interactive-b",
            "prompt": "Name one reason to bound a request queue.",
            "limit": 8,
        },
    ]
    runs = [
        execute(d, jobs, "fifo"),
        execute(d, jobs, "interleave"),
        execute(d, jobs, "interleave", 64),
    ]
    report = {
        "execution_mode": "fresh local model inference with real per-request cache; cooperative serial scheduler",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "device": "mps",
        },
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "arrival_policy": "all jobs arrive before the scheduler starts; greedy output, explicit per-job caps",
        "runs": runs,
        "limits": "One development run per policy; serial model forwards, not a production continuous-batching kernel or a throughput benchmark.",
    }
    Path(a.output).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
