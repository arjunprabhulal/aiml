"""Real CPU INT8 dynamic quantization and development-text likelihood comparison."""

import argparse
import copy
import hashlib
import json
import math
import platform
import time
from pathlib import Path


def score(model, tokenizer, texts, torch):
    results = []
    with torch.inference_mode():
        for text in texts:
            ids = tokenizer(text, return_tensors="pt")["input_ids"]
            start = time.perf_counter()
            logits = model(ids, use_cache=False).logits
            loss = torch.nn.functional.cross_entropy(
                logits[:, :-1].float().reshape(-1, logits.shape[-1]),
                ids[:, 1:].reshape(-1),
            )
            results.append(
                {
                    "text": text,
                    "predicted_tokens": ids.shape[-1] - 1,
                    "nll": float(loss),
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
                }
            )
    weighted = sum(r["nll"] * r["predicted_tokens"] for r in results) / sum(
        r["predicted_tokens"] for r in results
    )
    return {
        "cases": results,
        "token_weighted_nll": weighted,
        "perplexity": math.exp(weighted),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model-path", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    import torch, transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(4)
    torch.manual_seed(0)
    tokenizer = AutoTokenizer.from_pretrained(a.model_path, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        a.model_path,
        local_files_only=True,
        dtype=torch.float32,
        attn_implementation="eager",
    ).eval()
    texts = [
        "An inference service should release the request cache when a client cancels.",
        "A bounded queue rejects excess requests instead of allowing memory to grow without a limit.",
        "Measure time to first token separately from the time between later output tokens.",
    ]
    baseline = score(model, tokenizer, texts, torch)
    torch.backends.quantized.engine = "qnnpack"
    quantized = torch.ao.quantization.quantize_dynamic(
        model, {torch.nn.Linear}, dtype=torch.qint8, inplace=False
    ).eval()
    candidate = score(quantized, tokenizer, texts, torch)
    qmodules = sum(
        isinstance(m, torch.ao.nn.quantized.dynamic.Linear) for m in quantized.modules()
    )
    report = {
        "execution_mode": "fresh local CPU inference; dynamic INT8 Linear modules",
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "platform": platform.platform(),
            "quantized_engine": torch.backends.quantized.engine,
            "threads": torch.get_num_threads(),
        },
        "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
        "model_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
        "license": "Apache-2.0",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "quantized_linear_modules": qmodules,
        "baseline_fp32": baseline,
        "candidate_int8": candidate,
        "perplexity_delta": candidate["perplexity"] - baseline["perplexity"],
        "limits": "Three manually written development texts, not held-out task-quality evaluation. Timing includes forward and loss calculation. No GPU quantized kernels, FP8, INT4, or NVFP4 tested.",
    }
    Path(a.output).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
