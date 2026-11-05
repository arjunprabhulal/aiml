"""Checkpointed, resumable training for the one-block model, standard library only.

A checkpoint holds everything the next step depends on: the parameters, Adam's
two running averages and step count, the shuffle generator's state, the stories
left in the current epoch and the recorded history. It is written to a temporary
file and renamed into place, and it carries a SHA-256 digest of its contents.
"""
import hashlib
import json
import math
import os
import random
from pathlib import Path

import model as m
import train as t

FORMAT_VERSION = 1


def _digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def params_sha256(params):
    """An exact fingerprint of every parameter value: equal hashes mean equal parameters."""
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


def save(path, body):
    """Write to a temporary file, flush it to disk, then rename it over the old checkpoint.

    If the process stops at any point, the old checkpoint or the complete new one is
    left, never half of one. Surviving a power failure would also need the folder
    itself to be flushed, which this function does not do.
    """
    path = Path(path)
    data = dict(body, format_version=FORMAT_VERSION)
    data["sha256"] = _digest(data)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        f.write(json.dumps(data))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def input_signature(tok, text):
    """Bind the data, token IDs and exact numeric implementation used by a run."""
    source = Path(__file__).parent
    return {
        "corpus_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "tokenizer_sha256": _digest(tok.to_json()),
        "source_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                          for name in ("model.py", "train.py", "bpe.py", "checkpoint.py")},
    }


def load(path, cfg, expected_inputs=None):
    """Read and verify a checkpoint. Raises ValueError if it is damaged or from another run."""
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"checkpoint {path} is not valid JSON: {error.msg}") from None
    if not isinstance(data, dict):
        raise ValueError(f"checkpoint {path} does not hold a JSON object")
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"checkpoint format {data.get('format_version')!r}; expected {FORMAT_VERSION}")
    digest = data.pop("sha256", None)
    if digest != _digest(data):
        raise ValueError(f"checkpoint {path} failed its SHA-256 check")
    if data["config"] != cfg:
        changed = sorted(k for k in set(cfg) | set(data["config"]) if cfg.get(k) != data["config"].get(k))
        raise ValueError(f"checkpoint was written with a different config: {changed}")
    if expected_inputs is not None and data.get("training_inputs") != expected_inputs:
        raise ValueError("checkpoint training inputs differ: corpus, tokenizer or source changed")
    return data


def run(tok, text, cfg, folder, resume=False, stop_after=None, restore_optimizer=True, restore_shuffle=True):
    """Train with a checkpoint every eval_every steps.

    Writes folder/last.json (full state) and folder/best.json (parameters with the
    lowest development loss so far). stop_after simulates an interruption.
    restore_optimizer=False and restore_shuffle=False reproduce two resume bugs.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    training_inputs = input_signature(tok, text)
    train_s, dev_s, _ = t.split_stories(text)
    tr = t.encode_all(tok, train_s, cfg["max_len"])
    dv = t.encode_all(tok, dev_s, cfg["max_len"])
    p = m.init_params(len(tok.vocab), cfg["d"], cfg["hidden"], cfg["max_len"], cfg["init_seed"])
    opt = t.Adam(p, cfg["learning_rate"], cfg["beta1"], cfg["beta2"], cfg["adam_eps"])
    rng = random.Random(cfg["data_seed"])
    order, history, dev_history, best, start = [], [], [], None, 0
    if resume:
        state = load(folder / "last.json", cfg, training_inputs)
        p.update(state["params"])
        if restore_optimizer:
            opt.m, opt.v, opt.t = state["adam"]["m"], state["adam"]["v"], state["adam"]["t"]
        if restore_shuffle:
            version, internal, gauss = state["rng_state"]
            rng.setstate((version, tuple(internal), gauss))
            order = state["order"]
        history, dev_history, best, start = state["history"], state["dev_history"], state["best"], state["step"]
    for step in range(start + 1, cfg["steps"] + 1):
        if len(order) < cfg["batch"]:
            order += rng.sample(range(len(tr)), len(tr))
        batch = [tr[i] for i in order[:cfg["batch"]]]
        del order[:cfg["batch"]]
        loss, g = t.batch_gradient(p, batch)
        opt.step(p, g)
        history.append(round(loss, 4))
        if step % cfg["eval_every"] == 0 or step == cfg["steps"]:
            dev_loss = round(t.mean_loss(p, dv), 4)
            dev_history.append({"step": step, "dev_loss": dev_loss})
            if best is None or dev_loss < best["dev_loss"]:
                best = {"step": step, "dev_loss": dev_loss}
                save(folder / "best.json", {"step": step, "dev_loss": dev_loss, "config": cfg, "params": p, "training_inputs": training_inputs})
            save(folder / "last.json", {
                "step": step, "config": cfg, "params": p, "training_inputs": training_inputs,
                "adam": {"m": opt.m, "v": opt.v, "t": opt.t},
                "rng_state": list(rng.getstate()), "order": order,
                "history": history, "dev_history": dev_history, "best": best,
            })
            if stop_after is not None and step >= stop_after:
                break
    return p, history, dev_history, best
