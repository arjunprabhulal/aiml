"""Tests for train.py. Run: python3 -m unittest -v test_train.py

These tests run short training jobs and replay the saved parameters. They do not
repeat the full recorded run; `python3 trace_train.py --check` does that.
"""
import json
import math
import unittest
from pathlib import Path

import model as m
import train as t
from bpe import Tokenizer

HERE = Path(__file__).parent
TOK = Tokenizer.load(HERE / "tokenizer.json")
TEXT = (HERE / "corpus.txt").read_text()
RECORD = json.loads((HERE / "training-trace.json").read_text())


def short(steps, **changes):
    return dict(t.CONFIG, steps=steps, eval_every=steps, **changes)


class Mechanism(unittest.TestCase):
    def test_adam_first_step_matches_the_formula(self):
        p = {"w": [0.5, -0.25]}
        g = {"w": [0.2, -0.4]}
        opt = t.Adam(p, 0.01, 0.9, 0.999, 1e-8)
        opt.step(p, g)
        # After one step m-hat = g and v-hat = g squared, so each weight moves by lr * g / (|g| + eps).
        for before, grad, after in zip([0.5, -0.25], g["w"], p["w"]):
            self.assertAlmostEqual(after, before - 0.01 * grad / (abs(grad) + 1e-8), places=15)

    def test_adam_bias_correction_matters_early(self):
        p, q = {"w": [0.0]}, {"w": [0.0]}
        opt = t.Adam(p, 0.01, 0.9, 0.999, 1e-8)
        opt.step(p, {"w": [1.0]})
        q["w"][0] -= 0.01 * (0.1 * 1.0) / (math.sqrt(0.001 * 1.0) + 1e-8)  # uncorrected moments
        self.assertAlmostEqual(p["w"][0], -0.01, places=9)
        self.assertNotAlmostEqual(q["w"][0], p["w"][0], places=3)

    def test_batch_gradient_is_the_mean_of_story_gradients(self):
        p = m.init_params(len(TOK.vocab), 16, 64, 64, 3)
        stories = t.encode_all(TOK, t.split_stories(TEXT)[0][:2], 64)
        _, g = t.batch_gradient(p, stories)
        single = []
        for ids in stories:
            logits, cache = m.forward(p, ids[:-1])
            single.append(m.backward(p, cache, m.loss_and_dlogits(logits, ids[1:])[1]))
        for name in ("W_out", "Wq", "tok_emb"):
            for r, (a, b) in enumerate(zip(single[0][name], single[1][name])):
                for j in range(len(a)):
                    self.assertAlmostEqual(g[name][r][j], (a[j] + b[j]) / 2, places=12)

    def test_training_is_deterministic(self):
        a = t.train(TOK, TEXT, short(3))[0]
        b = t.train(TOK, TEXT, short(3))[0]
        self.assertEqual(json.dumps(a), json.dumps(b))  # every value, not only the checksum

    def test_short_run_lowers_development_loss(self):
        _, _, dev = t.train(TOK, TEXT, short(30))
        start = m.init_params(len(TOK.vocab), 16, 64, 64, 3)
        _, dv, _ = t.split_stories(TEXT)
        self.assertLess(dev[-1]["dev_loss"], t.mean_loss(start, t.encode_all(TOK, dv, 64)))

    def test_saved_parameters_reproduce_the_recorded_scores(self):
        p = json.loads((HERE / "params.json").read_text())
        _, _, test = t.split_stories(TEXT)
        self.assertEqual(t.checksum(p), RECORD["parameter_checksum"])
        self.assertEqual(round(t.mean_loss(p, t.encode_all(TOK, test, 64)), 4), RECORD["test_loss"])
        self.assertEqual(t.color_recall(p, TOK, test), RECORD["color_recall_test"])

    def test_trained_parameters_beat_the_bigram_baseline(self):
        bigram = json.loads((HERE / "baseline-trace.json").read_text())["test"]["bigram"]["loss"]
        p = json.loads((HERE / "params.json").read_text())
        _, _, test = t.split_stories(TEXT)
        self.assertLess(t.mean_loss(p, t.encode_all(TOK, test, 64)), bigram)


class FailureCases(unittest.TestCase):
    def test_story_longer_than_positions(self):
        with self.assertRaisesRegex(ValueError, "does not fit 48 positions"):
            t.encode_all(TOK, ["ava has a blue cup. ava goes to the garden. at the garden, ava gives "
                               "the cup to leo. now leo has the blue cup.\n"], 48)

    def test_learning_rate_must_be_positive(self):
        for bad in (0, -0.01, float("nan")):
            with self.subTest(lr=bad), self.assertRaisesRegex(ValueError, "positive finite"):
                t.Adam({"w": [0.0]}, bad, 0.9, 0.999, 1e-8)

    def test_non_finite_gradient_stops_training(self):
        p = {"w": [0.0, 1.0]}
        opt = t.Adam(p, 0.01, 0.9, 0.999, 1e-8)
        with self.assertRaisesRegex(ValueError, "non-finite gradient in w"):
            opt.step(p, {"w": [0.1, float("inf")]})

    def test_most_common_color_baseline(self):
        train, _, test = t.split_stories(TEXT)
        result = t.most_common_color_recall(train, test)
        self.assertEqual(result, RECORD["most_common_color_baseline"])
        self.assertLess(result["correct"], RECORD["color_recall_test"]["correct"])

    def test_too_few_stories(self):
        with self.assertRaisesRegex(ValueError, "need more than 340 stories"):
            t.split_stories("a.\nb.\n")

    def test_larger_rate_in_a_short_sweep_is_worse(self):
        dev = {}
        for lr in (0.01, 0.1):
            dev[lr] = t.train(TOK, TEXT, short(60, learning_rate=lr))[2][-1]["dev_loss"]
        self.assertGreater(dev[0.1], dev[0.01])
        recorded = {r["learning_rate"]: r["dev_loss"] for r in RECORD["learning_rate_sweep"]}
        self.assertEqual(dev, {lr: recorded[lr] for lr in dev})


if __name__ == "__main__":
    unittest.main()
