"""Compare actual baseline and quantized-model development likelihood records offline."""

import json, math
from pathlib import Path


def compare_scores(baseline, candidate):
    if not baseline or len(baseline) != len(candidate):
        raise ValueError("Matched development cases are required")
    for a, b in zip(baseline, candidate):
        if a["text"] != b["text"] or a["predicted_tokens"] != b["predicted_tokens"]:
            raise ValueError("Cases or token denominators differ")
        if a["predicted_tokens"] < 1 or any(
            not math.isfinite(x["nll"]) or x["nll"] < 0 for x in [a, b]
        ):
            raise ValueError("Invalid likelihood data")
    tokens = sum(a["predicted_tokens"] for a in baseline)
    before = math.fsum(a["nll"] * a["predicted_tokens"] for a in baseline) / tokens
    after = math.fsum(a["nll"] * a["predicted_tokens"] for a in candidate) / tokens
    return {
        "predicted_tokens": tokens,
        "baseline_token_weighted_nll": before,
        "candidate_token_weighted_nll": after,
        "nll_increase": after - before,
        "likelihood_regression": after > before,
    }


def main():
    record = json.loads(Path("quantization-run.json").read_text())
    print(
        json.dumps(
            {
                "execution_mode": "offline analysis of fresh CPU INT8 model execution",
                "model_id": record["model_id"],
                "model_revision": record["model_revision"],
                "quantized_linear_modules": record["quantized_linear_modules"],
                "comparison": compare_scores(
                    record["baseline_fp32"]["cases"], record["candidate_int8"]["cases"]
                ),
                "limits": "Development likelihood only; no held-out task-quality, GPU performance or production acceptance.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
