"""Tests for attention.py. Run: python3 -m unittest -v test_attention.py"""
import math
import subprocess
import sys
import unittest
from pathlib import Path

import attention as at
import trace_attention as tr
from bpe import Tokenizer

HERE = Path(__file__).parent
TOK = Tokenizer.load(HERE / "tokenizer.json")
TABLE = tr.embeddings(len(TOK.vocab))


def setup(sentence=tr.SENTENCE):
    params = at.init_attention(tr.D_MODEL, tr.D_HEAD, tr.SEED)
    return params, [list(TABLE[i]) for i in TOK.encode(sentence)]


class Recorded(unittest.TestCase):
    def test_recorded_trace(self):
        result = subprocess.run([sys.executable, "trace_attention.py", "--check"], cwd=HERE)
        self.assertEqual(result.returncode, 0)


class Mechanism(unittest.TestCase):
    def test_shapes(self):
        params, x = setup()
        c = at.attention_forward(params, x)
        T = len(x)
        self.assertEqual(at.shape(c["weights"]), (T, T))
        self.assertEqual(at.shape(c["out"]), (T, tr.D_MODEL))

    def test_rows_sum_to_one_and_future_weights_are_zero(self):
        params, x = setup()
        w = at.attention_forward(params, x)["weights"]
        for i, row in enumerate(w):
            self.assertAlmostEqual(math.fsum(row), 1.0, places=12)
            self.assertEqual(row[i + 1:], [0.0] * (len(row) - i - 1))

    def test_gradients_match_finite_differences(self):
        params, x = setup()
        r = tr.readout(len(x))
        grads, d_x = at.attention_backward(params, x, at.attention_forward(params, x), r)
        self.assertLess(tr.max_err(grads, tr.numeric_grad(params, x, r)), 1e-7)
        for i in range(len(x)):
            for j in range(tr.D_MODEL):
                old = x[i][j]
                x[i][j] = old + tr.EPS
                up = tr.loss(params, x, r)
                x[i][j] = old - tr.EPS
                down = tr.loss(params, x, r)
                x[i][j] = old
                self.assertAlmostEqual(d_x[i][j], (up - down) / (2 * tr.EPS), places=7)

    def test_each_position_attends_to_itself(self):
        params, x = setup()
        w = at.attention_forward(params, x)["weights"]
        self.assertEqual(w[0][0], 1.0)  # the first position can only see itself
        self.assertTrue(all(row[i] > 0 for i, row in enumerate(w)))

    def test_scores_are_scaled_by_the_square_root_of_the_head_size(self):
        params, x = setup()
        c = at.attention_forward(params, x)
        raw = at.matmul(c["q"], at.transpose(c["k"]))
        for i, row in enumerate(c["scores"]):
            for j in range(i + 1):
                self.assertAlmostEqual(row[j], raw[i][j] / math.sqrt(tr.D_HEAD), places=15)

    def test_future_token_does_not_change_earlier_rows(self):
        params, x = setup()
        _, x2 = setup(tr.CHANGED)
        changed = tr.changed_rows(at.attention_forward(params, x)["out"], at.attention_forward(params, x2)["out"])
        first = next(i for i, (a, b) in enumerate(zip(x, x2)) if a != b)
        self.assertEqual(changed, list(range(first, len(x))))


class FailureCases(unittest.TestCase):
    def test_no_mask_leaks_the_future(self):
        params, x = setup()
        _, x2 = setup(tr.CHANGED)
        changed = tr.changed_rows(at.attention_forward(params, x, "none")["out"],
                                  at.attention_forward(params, x2, "none")["out"])
        self.assertEqual(changed, list(range(len(x))))

    def test_zeroed_scores_still_leak(self):
        params, x = setup()
        w = at.attention_forward(params, x, "zero")["weights"]
        self.assertGreater(math.fsum(w[0][1:]), 0.5)

    def test_unknown_mask_mode(self):
        params, x = setup()
        with self.assertRaisesRegex(ValueError, "mask must be one of"):
            at.attention_forward(params, x, "upper")

    def test_empty_sequence(self):
        params, _ = setup()
        with self.assertRaisesRegex(ValueError, "empty sequence"):
            at.attention_forward(params, [])

    def test_wrong_input_width(self):
        params, x = setup()
        with self.assertRaisesRegex(ValueError, "must have 4 numbers"):
            at.attention_forward(params, [row[:3] for row in x])


if __name__ == "__main__":
    unittest.main()
