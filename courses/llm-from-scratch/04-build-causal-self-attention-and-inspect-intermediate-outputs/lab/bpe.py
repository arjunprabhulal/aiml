"""A byte-pair encoding (BPE) tokenizer trained on characters, standard library only.

Training starts from the characters seen in the training text and repeatedly
merges the most frequent adjacent pair of tokens into a new token. Encoding
replays those merges in the order they were learned. Merges never cross the
boundary of a chunk: a word with its leading space, a run of punctuation or a
run of whitespace.

ID 0 is reserved for <unk>: a character that never appeared in training.
"""
import json
import re
from collections import Counter

UNK = "<unk>"
FORMAT_VERSION = 1
# A chunk is an optional space plus letters or digits, an optional space plus
# punctuation, or whitespace. BPE merges only inside a chunk.
CHUNK = re.compile(r" ?[A-Za-z0-9]+| ?[^A-Za-z0-9\s]+|\s+")


def chunks(text):
    found = CHUNK.findall(text)
    if "".join(found) != text:  # every character must belong to exactly one chunk
        raise AssertionError("chunk pattern lost characters")
    return found


def most_frequent_pair(words):
    """words: {tuple of tokens: count}. Ties go to the pair first in string (code-point) order."""
    pairs = Counter()
    for word, count in words.items():
        for pair in zip(word, word[1:]):
            pairs[pair] += count
    if not pairs:
        return None, 0
    best = min(pairs, key=lambda p: (-pairs[p], p))
    return best, pairs[best]


def merge_word(word, pair, joined):
    out, i = [], 0
    while i < len(word):
        if i + 1 < len(word) and (word[i], word[i + 1]) == pair:
            out.append(joined)
            i += 2
        else:
            out.append(word[i])
            i += 1
    return tuple(out)


class Tokenizer:
    def __init__(self, alphabet, merges):
        self.alphabet = list(alphabet)
        self.merges = [tuple(m) for m in merges]
        self.vocab = [UNK] + self.alphabet + ["".join(m) for m in self.merges]
        self.ids = {token: i for i, token in enumerate(self.vocab)}
        if len(self.ids) != len(self.vocab):
            raise ValueError("vocabulary has duplicate tokens")
        self.rank = {m: r for r, m in enumerate(self.merges)}

    @classmethod
    def train(cls, text, vocab_size):
        """Learn merges until the vocabulary (including <unk>) has vocab_size entries."""
        if not text:
            raise ValueError("cannot train on empty text")
        alphabet = sorted(set(text))
        base = 1 + len(alphabet)
        if vocab_size < base:
            raise ValueError(f"vocab_size {vocab_size} is smaller than the {base} base tokens")
        words = Counter(tuple(c) for c in chunks(text))
        merges, history = [], []
        while base + len(merges) < vocab_size:
            pair, count = most_frequent_pair(words)
            if pair is None or count < 2:
                break  # no pair repeats; a once-seen pair is not worth a vocabulary entry
            joined = pair[0] + pair[1]
            words = Counter({merge_word(w, pair, joined): c for w, c in words.items()})
            merges.append(pair)
            history.append({"pair": list(pair), "token": joined, "count": count})
        tok = cls(alphabet, merges)
        tok.history = history
        return tok

    def encode_chunk(self, chunk):
        parts = [c if c in self.ids else UNK for c in chunk]
        while True:
            candidates = [(self.rank[p], i) for i, p in enumerate(zip(parts, parts[1:])) if p in self.rank]
            if not candidates:
                return parts
            _, i = min(candidates)
            pair = (parts[i], parts[i + 1])
            parts = list(merge_word(tuple(parts), pair, pair[0] + pair[1]))

    def tokens(self, text):
        return [t for chunk in chunks(text) for t in self.encode_chunk(chunk)]

    def encode(self, text):
        return [self.ids[t] for t in self.tokens(text)]

    def decode(self, ids):
        bad = [i for i in ids if isinstance(i, bool) or not (isinstance(i, int) and 0 <= i < len(self.vocab))]
        if bad:
            raise ValueError(f"token IDs outside the vocabulary of size {len(self.vocab)}: {bad[:5]}")
        return "".join("�" if i == 0 else self.vocab[i] for i in ids)

    def to_json(self):
        return {"format_version": FORMAT_VERSION, "alphabet": self.alphabet,
                "merges": [list(m) for m in self.merges]}

    @classmethod
    def from_json(cls, data):
        if data.get("format_version") != FORMAT_VERSION:
            raise ValueError(f"unsupported tokenizer format {data.get('format_version')!r}; expected {FORMAT_VERSION}")
        return cls(data["alphabet"], data["merges"])

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.to_json(), f, indent=1)
            f.write("\n")

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls.from_json(json.load(f))
