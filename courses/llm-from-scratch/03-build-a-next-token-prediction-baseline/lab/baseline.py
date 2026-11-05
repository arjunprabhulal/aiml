"""Count-based next-token baselines for the story corpus, standard library only.

Three models predict the next token ID:
  uniform  - every vocabulary entry equally likely
  unigram  - how often each token appears in the training stories
  bigram   - how often each token follows the previous token, with add-k smoothing

Each model returns a probability for every token in the vocabulary, so all three
are scored the same way: mean cross-entropy (natural log) on held-out tokens.
"""
import math
import random
from collections import Counter

from bpe import Tokenizer


def split_stories(text, train=280, dev=60):
    """Split by story, in file order: training, development, then test."""
    stories = [s + "\n" for s in text.split("\n") if s]
    if train + dev >= len(stories):
        raise ValueError(f"need more than {train + dev} stories, got {len(stories)}")
    return stories[:train], stories[train:train + dev], stories[train + dev:]


def encode_stories(tok, stories):
    return [tok.encode(s) for s in stories]


class Uniform:
    def __init__(self, vocab_size):
        self.vocab_size = vocab_size

    def probs(self, prev):
        return [1.0 / self.vocab_size] * self.vocab_size


class Unigram:
    def __init__(self, sequences, vocab_size):
        counts = Counter(t for seq in sequences for t in seq)
        total = sum(counts.values())
        # add-one smoothing so a token unseen in training still gets a probability
        self.p = [(counts[i] + 1) / (total + vocab_size) for i in range(vocab_size)]

    def probs(self, prev):
        return self.p


class Bigram:
    def __init__(self, sequences, vocab_size, k):
        if not (k > 0 and math.isfinite(k)):
            raise ValueError(f"smoothing k must be a positive finite number, got {k!r}")
        self.vocab_size, self.k = vocab_size, k
        self.counts = [Counter() for _ in range(vocab_size)]
        for seq in sequences:
            for a, b in zip(seq, seq[1:]):
                self.counts[a][b] += 1
        self.totals = [sum(c.values()) for c in self.counts]

    def probs(self, prev):
        c, total = self.counts[prev], self.totals[prev]
        denom = total + self.k * self.vocab_size
        return [(c[i] + self.k) / denom for i in range(self.vocab_size)]


def cross_entropy(model, sequences):
    """Mean negative log probability of each token given the token before it.

    The first token of each story has no previous token in the story, so it is
    not scored; every model is scored on exactly the same positions.
    """
    losses = []
    for seq in sequences:
        for prev, nxt in zip(seq, seq[1:]):
            p = model.probs(prev)[nxt]
            if p <= 0:
                raise ValueError(f"model gave probability {p} to an observed token")
            losses.append(-math.log(p))
    if not losses:
        raise ValueError("no token pairs to score")
    return math.fsum(losses) / len(losses), len(losses)


def argmax(probs):
    return max(range(len(probs)), key=lambda i: (probs[i], -i))


def recall_check(tok, model, stories, field):
    """Predict the color or object in each story's last sentence from the token before it.

    field="color": context ends with "now <name> has the"; the answer is " <color>".
    field="object": context ends with "now <name> has the <color>"; the answer is " <object>".
    """
    correct, guesses = 0, Counter()
    for story in stories:
        last = story[story.index("now "):].rstrip(".\n")
        words = last.split()  # now, name, has, the, color, object
        color, thing = words[4], words[5]
        cut = story.rindex(" " + color) if field == "color" else story.rindex(" " + thing)
        # The answer word can be several tokens (" kite" is " kit" + "e"); score its first token.
        answer = tok.tokens(" " + (color if field == "color" else thing))[0]
        context = tok.encode(story[:cut])
        guess = tok.vocab[argmax(model.probs(context[-1]))]
        guesses[guess] += 1
        correct += guess == answer
    return {"correct": correct, "total": len(stories), "guesses": dict(sorted(guesses.items()))}


def sample(model, tok, start, length, rng, greedy=False):
    ids = tok.encode(start)
    for _ in range(length):
        p = model.probs(ids[-1])
        ids.append(argmax(p) if greedy else rng.choices(range(len(p)), weights=p)[0])
    return tok.decode(ids)
