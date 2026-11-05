"""Generate text from the trained one-block model with greedy, temperature and top-k selection.

Each step runs the whole model on the text so far, takes the scores at the last
position and chooses one token. Generation stops at a newline (the end of a
story), at max_new_tokens, or when the model's position table is full.
Python 3.10+, standard library only.
"""
import math
import random

import model as m

MIN_TEMPERATURE = 0.01  # a chosen floor: a tiny T can overflow the divided scores; use 0 for greedy


def check_settings(temperature, top_k, vocab_size):
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) \
            or not math.isfinite(temperature) or not (temperature == 0 or temperature >= MIN_TEMPERATURE):
        raise ValueError(f"temperature must be 0 or a finite number >= {MIN_TEMPERATURE}, got {temperature!r}")
    if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= vocab_size):
        raise ValueError(f"top_k must be an integer from 1 to {vocab_size}, got {top_k!r}")


def next_token_probs(logits, temperature, top_k):
    """Turn one row of scores into the probabilities the sampler draws from."""
    if temperature == 0:  # greedy: all probability on the highest score, ties to the lowest ID
        best = max(range(len(logits)), key=lambda i: (logits[i], -i))
        return [1.0 if i == best else 0.0 for i in range(len(logits))]
    scaled = [v / temperature for v in logits]
    if top_k is not None:
        # The k highest scores; among equal scores the lower token ID is kept.
        kept = set(sorted(range(len(scaled)), key=lambda i: (-scaled[i], i))[:top_k])
        scaled = [v if i in kept else -math.inf for i, v in enumerate(scaled)]
    return m.softmax_row(scaled)


def generate(p, tok, prompt, max_new_tokens=60, temperature=0.0, top_k=None, seed=0):
    """Return the generated text, the chosen tokens with their probabilities, and why it stopped."""
    check_settings(temperature, top_k, len(p["tok_emb"]))
    ids = tok.encode(prompt)
    if not ids:
        raise ValueError("empty prompt: the model needs at least one token to continue")
    max_len = len(p["pos_emb"])
    if len(ids) > max_len:
        raise ValueError(f"prompt of {len(ids)} tokens is longer than the {max_len} positions the model has")
    rng = random.Random(seed)
    steps, reason = [], "max_new_tokens"
    newline = tok.ids["\n"]
    for _ in range(max_new_tokens):
        if len(ids) == max_len:
            reason = "context full"
            break
        logits, _ = m.forward(p, ids)
        probs = next_token_probs(logits[-1], temperature, top_k)
        choice = rng.choices(range(len(probs)), weights=probs)[0] if temperature > 0 else probs.index(1.0)
        ids.append(choice)
        steps.append({"token": tok.vocab[choice], "probability": round(probs[choice], 4)})
        if choice == newline:
            reason = "end of story"
            break
    return {"text": tok.decode(ids), "steps": steps, "stopped": reason}


def follows_story(prompt_sentence, generated):
    """Check a generated story against its first sentence: same giver, color and object at the end."""
    words = prompt_sentence.rstrip(".").split()  # name has a color object
    giver, color, thing = words[0], words[3], words[4]
    lines = generated.split("\n")[0].split(". ")
    if len(lines) != 4 or not lines[3].startswith("now "):
        return {"well_formed": False, "keeps_color_and_object": False}
    last = lines[3].rstrip(".").split()
    well_formed = (lines[1].startswith(f"{giver} goes to the ") and lines[2].startswith("at the ")
                   and len(last) == 6 and last[2:4] == ["has", "the"])
    return {"well_formed": well_formed, "keeps_color_and_object": well_formed and last[4:6] == [color, thing]}
