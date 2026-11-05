"""Tests for bpe.py. Run: python3 -m unittest -v test_bpe.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bpe import Tokenizer, chunks
from make_corpus import corpus

HERE = Path(__file__).parent
TEXT = (HERE / "corpus.txt").read_text()


class Recorded(unittest.TestCase):
    def test_corpus_matches_generator(self):
        self.assertEqual(TEXT, corpus())

    def test_recorded_trace_and_tokenizer(self):
        result = subprocess.run([sys.executable, "trace_bpe.py", "--check"], cwd=HERE)
        self.assertEqual(result.returncode, 0)

    def test_saved_tokenizer_equals_fresh_training(self):
        saved = Tokenizer.load(HERE / "tokenizer.json")
        fresh = Tokenizer.train(TEXT, 96)
        self.assertEqual(saved.vocab, fresh.vocab)


class Mechanism(unittest.TestCase):
    def setUp(self):
        self.tok = Tokenizer.train(TEXT, 96)

    def test_round_trip_on_corpus(self):
        self.assertEqual(self.tok.decode(self.tok.encode(TEXT)), TEXT)

    def test_every_learned_token_encodes_to_itself(self):
        # Replaying merges in rank order must rebuild each merged token as one piece.
        for token in self.tok.vocab[1 + len(self.tok.alphabet):]:
            with self.subTest(token=token):
                self.assertEqual(self.tok.tokens(token), [token])

    def test_most_frequent_pair_is_merged_first(self):
        self.assertEqual(self.tok.history[0]["pair"], [" ", "t"])
        counts = [h["count"] for h in self.tok.history]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_merges_stay_inside_chunks(self):
        for token in self.tok.vocab[1:]:
            self.assertEqual(chunks(token), [token], token)

    def test_unseen_word_falls_back_to_characters(self):
        self.assertEqual(self.tok.tokens("maya"), ["m", "a", "y", "a"])

    def test_training_stops_when_no_pair_repeats(self):
        self.assertEqual(len(Tokenizer.train(TEXT, 128).vocab), 109)

    def test_encoding_applies_the_lowest_rank_merge_first(self):
        # "bc" was learned before "ab", so "abc" becomes a + bc, not ab + c.
        tok = Tokenizer(["a", "b", "c"], [("b", "c"), ("a", "b")])
        self.assertEqual(tok.tokens("abc"), ["a", "bc"])

    def test_ties_break_alphabetically(self):
        tok = Tokenizer.train("ab cd", 10)
        self.assertEqual(tok.merges, [])  # every pair occurs once, so the trainer adds no entry
        # (" ", "c"), ("a", "b") and ("c", "d") each occur twice; the space sorts first.
        tok = Tokenizer.train("ab cd ab cd", 10)
        self.assertEqual(tok.merges[0], (" ", "c"))


class FailureCases(unittest.TestCase):
    def setUp(self):
        self.tok = Tokenizer.train(TEXT, 96)

    def test_unknown_characters_lose_information(self):
        ids = self.tok.encode("café")
        self.assertEqual(ids[-2:], [0, 0])
        self.assertEqual(self.tok.decode(ids), "ca��")

    def test_decode_rejects_out_of_range_ids(self):
        for ids in ([5, 96], [-1], [True]):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "outside the vocabulary"):
                self.tok.decode(ids)

    def test_empty_training_text(self):
        with self.assertRaisesRegex(ValueError, "empty text"):
            Tokenizer.train("", 96)

    def test_vocab_size_below_base(self):
        with self.assertRaisesRegex(ValueError, "smaller than the 28 base tokens"):
            Tokenizer.train(TEXT, 20)

    def test_wrong_format_version(self):
        data = self.tok.to_json() | {"format_version": 2}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "tok.json"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "unsupported tokenizer format"):
                Tokenizer.load(path)


if __name__ == "__main__":
    unittest.main()
