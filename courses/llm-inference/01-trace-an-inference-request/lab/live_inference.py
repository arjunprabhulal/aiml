"""Real local text generation and measured inference experiments. Never downloads implicitly."""

from __future__ import annotations
import argparse
import hashlib
import json
import math
import platform
import statistics
import time
from pathlib import Path

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"


def percentile(values, q):
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)] if values else None


class LocalDecoder:
    def __init__(self, model_path, device):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.device = device
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path, local_files_only=True
        )
        self.tokenizer.padding_side = "left"
        self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                model_path,
                local_files_only=True,
                dtype=torch.float32,
                attn_implementation="eager",
                trust_remote_code=False,
            )
            .eval()
            .to(device)
        )

    def sync(self):
        if self.device == "mps":
            self.torch.mps.synchronize()
        elif self.device.startswith("cuda"):
            self.torch.cuda.synchronize()

    def encode(self, text):
        if not text.strip():
            raise ValueError("Prompt must not be empty")
        return self.tokenizer.apply_chat_template(
            [{"role": "user", "content": text}],
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        )["input_ids"].to(self.device)

    def _forward(self, ids, cache=None, use_cache=True):
        with self.torch.inference_mode():
            return self.model(input_ids=ids, past_key_values=cache, use_cache=use_cache)

    def run(
        self,
        text,
        max_new_tokens=24,
        use_cache=True,
        chunk_size=None,
        cancel_after=None,
    ):
        if max_new_tokens < 1:
            raise ValueError("Output limit must be positive")
        if chunk_size is not None and chunk_size < 1:
            raise ValueError("Chunk size must be positive")
        self.sync()
        started = time.perf_counter()
        ids = self.encode(text)
        self.sync()
        tokenized = time.perf_counter()
        cache = None
        if chunk_size is not None and not use_cache:
            raise ValueError("Chunking needs a cache")
        for chunk in ids.split(chunk_size or ids.shape[-1], dim=-1):
            result = self._forward(chunk, cache, use_cache)
            cache = result.past_key_values if use_cache else None
        emitted = []
        arrivals = []
        stop = "length"
        context = ids
        eos_ids = self.model.generation_config.eos_token_id
        eos_ids = set(eos_ids if isinstance(eos_ids, list) else [eos_ids])
        for _ in range(max_new_tokens):
            token = result.logits[:, -1].argmax(-1, keepdim=True)
            self.sync()
            token_id = int(token.item())
            arrivals.append(time.perf_counter() - started)
            emitted.append(token_id)
            if token_id in eos_ids:
                stop = "eos"
                break
            if cancel_after is not None and len(emitted) >= cancel_after:
                stop = "cancelled"
                break
            if len(emitted) == max_new_tokens:
                break
            context = self.torch.cat((context, token), dim=-1)
            result = self._forward(token if use_cache else context, cache, use_cache)
            cache = result.past_key_values if use_cache else None
        cache_length = int(cache.get_seq_length()) if cache is not None else 0
        # Release the request-owned cache on every stop, including cancellation.
        del cache, result
        self.sync()
        intervals = [1000 * (b - a) for a, b in zip(arrivals, arrivals[1:])]
        return {
            "prompt": text,
            "prompt_tokens": ids.shape[-1],
            "generated_token_ids": emitted,
            "generated_tokens": len(emitted),
            "text": self.tokenizer.decode(emitted, skip_special_tokens=True),
            "use_cache": use_cache,
            "chunk_size": chunk_size,
            "stop_reason": stop,
            "tokenization_ms": round(1000 * (tokenized - started), 3),
            "ttft_ms": round(arrivals[0] * 1000, 3),
            "tpot_ms": round(statistics.fmean(intervals), 3) if intervals else None,
            "itl_ms": [round(x, 3) for x in intervals],
            "e2e_ms": round(arrivals[-1] * 1000, 3),
            "cache_tokens_before_release": cache_length,
        }

    def batch(self, texts, max_new_tokens=24):
        prompts = [
            self.tokenizer.apply_chat_template(
                [{"role": "user", "content": t}],
                tokenize=False,
                add_generation_prompt=True,
            )
            for t in texts
        ]
        encoded = self.tokenizer(prompts, padding=True, return_tensors="pt").to(
            self.device
        )
        self.sync()
        start = time.perf_counter()
        with self.torch.inference_mode():
            out = self.model.generate(
                **encoded,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                use_cache=True,
            )
        self.sync()
        elapsed = time.perf_counter() - start
        ids = out[:, encoded["input_ids"].shape[-1] :].tolist()
        eos = self.model.generation_config.eos_token_id
        eos = set(eos if isinstance(eos, list) else [eos])
        trimmed = []
        for row in ids:
            n = next((i + 1 for i, x in enumerate(row) if x in eos), len(row))
            trimmed.append(row[:n])
        return {
            "batch_size": len(texts),
            "elapsed_ms": round(elapsed * 1000, 3),
            "output_tokens": sum(map(len, trimmed)),
            "output_tokens_per_s": round(sum(map(len, trimmed)) / elapsed, 3),
            "texts": [
                self.tokenizer.decode(row, skip_special_tokens=True) for row in trimmed
            ],
        }

    def prefix_reuse(self, prefix, suffix):
        # Tokenize the full sequence once: concatenated text tokenization need not equal separate tokenizations.
        full = self.encode(prefix + suffix)
        prefix_length = max(1, full.shape[-1] // 2)
        self.sync()
        start = time.perf_counter()
        cold = self._forward(full)
        self.sync()
        cold_ms = (time.perf_counter() - start) * 1000
        cached = self._forward(full[:, :prefix_length]).past_key_values
        self.sync()
        start = time.perf_counter()
        warm = self._forward(full[:, prefix_length:], cached)
        self.sync()
        warm_ms = (time.perf_counter() - start) * 1000
        error = float((cold.logits[:, -1] - warm.logits[:, -1]).abs().max().item())
        return {
            "total_tokens": full.shape[-1],
            "cached_prefix_tokens": prefix_length,
            "cold_prefill_ms": round(cold_ms, 3),
            "suffix_prefill_ms": round(warm_ms, 3),
            "max_abs_last_logit_diff": error,
            "same_greedy_next_token": int(cold.logits[:, -1].argmax())
            == int(warm.logits[:, -1].argmax()),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import torch, transformers

    decoder = LocalDecoder(args.model_path, args.device)
    warmup = decoder.run("Explain a cache in one sentence.", max_new_tokens=4)
    short = "Explain why a code assistant should stop generating when its user cancels."
    long = (
        "A retrieval service indexes source code and returns relevant functions. " * 20
    ) + short
    runs = []
    for name, text, options in [
        ("short_cached", short, {}),
        ("long_cached", long, {}),
        ("short_without_cache", short, {"use_cache": False}),
        ("long_chunked", long, {"chunk_size": 64}),
        ("cancelled", short, {"cancel_after": 4}),
    ]:
        samples = [decoder.run(text, **options) for _ in range(3)]
        runs.append(
            {
                "name": name,
                "samples": samples,
                "median_ttft_ms": round(
                    statistics.median(s["ttft_ms"] for s in samples), 3
                ),
                "median_tpot_ms": round(
                    statistics.median(
                        s["tpot_ms"] for s in samples if s["tpot_ms"] is not None
                    ),
                    3,
                ),
            }
        )
    batches = [decoder.batch([short] * n) for n in [1, 2, 4]]
    config = decoder.model.config
    parameters = sum(p.numel() for p in decoder.model.parameters())
    report = {
        "execution_mode": "fresh local inference; no simulated latency",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "device": args.device,
        },
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "license": "Apache-2.0",
            "dtype": "float32",
            "attention_backend": "eager",
            "parameters": parameters,
            "weight_bytes": sum(
                p.numel() * p.element_size() for p in decoder.model.parameters()
            ),
            "layers": config.num_hidden_layers,
            "kv_heads": config.num_key_value_heads,
            "head_dim": config.hidden_size // config.num_attention_heads,
            "kv_bytes_per_token": 2
            * config.num_hidden_layers
            * config.num_key_value_heads
            * (config.hidden_size // config.num_attention_heads)
            * 4,
        },
        "generation": {
            "strategy": "greedy argmax",
            "max_new_tokens": 24,
            "do_sample": False,
            "warmup_tokens": 4,
            "thinking": "not a configurable reasoning mode in this model",
        },
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "warmup": warmup,
        "runs": runs,
        "batch_sweep": batches,
        "prefix_reuse": decoder.prefix_reuse(long, " Give one practical example."),
        "limits": "Three repeated development prompts per configuration; no held-out quality evaluation, HTTP latency, CUDA profiling, or production load test.",
    }
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": Path(args.output).name,
                "runs": len(runs),
                "batch_sizes": [x["batch_size"] for x in batches],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
