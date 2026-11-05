"""Tests for baseline.py. Run: python3 -m unittest -v test_baseline.py"""
import math
import json
import random
import subprocess
import sys
import unittest
from pathlib import Path

import baseline as b
from bpe import Tokenizer
from inspect_split import overlap_counts

HERE = Path(__file__).parent
TOK = Tokenizer.load(HERE / "tokenizer.json")
V = len(TOK.vocab)
TRAIN, DEV, TEST = b.split_stories((HERE / "corpus.txt").read_text())
TR = b.encode_stories(TOK, TRAIN)


class Recorded(unittest.TestCase):
    def test_recorded_trace(self):
        result = subprocess.run([sys.executable, "trace_baseline.py", "--check"], cwd=HERE)
        self.assertEqual(result.returncode, 0)

    def test_tokenizer_matches_its_corpus(self):
        self.assertEqual(Tokenizer.train((HERE / "corpus.txt").read_text(), 96).vocab, TOK.vocab)


class Mechanism(unittest.TestCase):
    def test_every_model_gives_a_distribution(self):
        for model in (b.Uniform(V), b.Unigram(TR, V), b.Bigram(TR, V, 0.01)):
            for prev in (0, TOK.ids[" the"], TOK.ids["."]):
                with self.subTest(model=type(model).__name__, prev=prev):
                    p = model.probs(prev)
                    self.assertEqual(len(p), V)
                    self.assertAlmostEqual(math.fsum(p), 1.0, places=12)

    def test_uniform_loss_is_log_vocab(self):
        loss, _ = b.cross_entropy(b.Uniform(V), b.encode_stories(TOK, DEV))
        self.assertAlmostEqual(loss, math.log(V), places=12)

    def test_bigram_beats_unigram_beats_uniform_on_test(self):
        te = b.encode_stories(TOK, TEST)
        losses = [b.cross_entropy(m, te)[0] for m in (b.Bigram(TR, V, 0.001), b.Unigram(TR, V), b.Uniform(V))]
        self.assertEqual(losses, sorted(losses))

    def test_split_rows_reconstruct_the_corpus(self):
        self.assertEqual((len(TRAIN), len(DEV), len(TEST)), (280, 60, 60))
        self.assertEqual(TRAIN + DEV + TEST, [s + "\n" for s in (HERE / "corpus.txt").read_text().split("\n") if s])

    def test_split_inspection_counts_rows_not_distinct_texts(self):
        stories = [f"story {i}" for i in range(400)]
        stories[280] = stories[281] = stories[0]
        stories[340] = stories[342] = stories[0]
        stories[341] = stories[282]
        counts = overlap_counts("\n".join(stories))
        self.assertEqual(counts["dev_rows_matching_training_text"], 2)
        self.assertEqual(counts["test_rows_matching_training_text"], 2)
        self.assertEqual(counts["test_rows_matching_train_or_dev_text"], 3)

    def test_bundled_split_overlap_is_reported(self):
        counts = overlap_counts((HERE / "corpus.txt").read_text())
        self.assertEqual(counts, json.loads((HERE / "split-overlap.json").read_text()))
        self.assertEqual(counts["dev_rows_matching_training_text"], 5)
        self.assertEqual(counts["test_rows_matching_training_text"], 5)
        self.assertEqual(counts["test_rows_matching_train_or_dev_text"], 8)

    def test_unseen_pair_gets_smoothed_probability(self):
        model = b.Bigram(TR, V, 0.01)
        prev = TOK.ids[" the"]
        unseen = TOK.ids["<unk>"]
        self.assertEqual(model.counts[prev][unseen], 0)
        self.assertAlmostEqual(model.probs(prev)[unseen], 0.01 / (model.totals[prev] + 0.01 * V))


class FailureCases(unittest.TestCase):
    def test_bigram_cannot_recall_color(self):
        result = b.recall_check(TOK, b.Bigram(TR, V, 0.001), TEST, "color")
        self.assertEqual(result["correct"], 0)
        self.assertEqual(list(result["guesses"]), [" school"])

    def test_greedy_decoding_repeats(self):
        text = b.sample(b.Bigram(TR, V, 0.001), TOK, "mia has", 25, random.Random(1), greedy=True)
        self.assertGreaterEqual(text.count("sam gives the school,"), 4)

    def test_sampling_can_emit_unknown_token(self):
        text = b.sample(b.Bigram(TR, V, 0.001), TOK, "mia has", 40, random.Random(1))
        self.assertIn("�", text)

    def test_zero_smoothing_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive finite"):
            b.Bigram(TR, V, 0)

    def test_zero_probability_is_reported(self):
        class Never:
            def probs(self, prev):
                return [0.0] * V
        with self.assertRaisesRegex(ValueError, "probability 0.0 to an observed token"):
            b.cross_entropy(Never(), TR[:1])

    def test_too_few_stories(self):
        with self.assertRaisesRegex(ValueError, "need more than 340 stories"):
            b.split_stories("a.\nb.\n")


if __name__ == "__main__":
    unittest.main()
