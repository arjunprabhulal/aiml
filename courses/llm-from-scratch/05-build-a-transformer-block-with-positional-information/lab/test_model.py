"""Tests for model.py. Run: python3 -m unittest -v test_model.py"""
import math
import subprocess
import sys
import unittest
from pathlib import Path

import model as m
import trace_block as tb
from bpe import Tokenizer

HERE = Path(__file__).parent
TOK = Tokenizer.load(HERE / "tokenizer.json")


def series():
    return tb.build(TOK, tb.SERIES)


class Recorded(unittest.TestCase):
    def test_recorded_trace(self):
        result = subprocess.run([sys.executable, "trace_block.py", "--check"], cwd=HERE)
        self.assertEqual(result.returncode, 0)


class Mechanism(unittest.TestCase):
    def test_gradients_match_finite_differences(self):
        ids = TOK.encode("mia has a red ball.")
        self.assertLess(tb.gradient_error(tb.build(TOK, tb.TINY), ids[:-1], ids[1:]), 1e-7)

    def test_layernorm_centers_and_scales_each_row(self):
        x = [[1.0, 2.0, 3.0, 6.0], [0.5, 0.5, 0.5, 2.5]]
        out, _ = m.layernorm_forward(x, [2.0] * 4, [1.0] * 4)
        for row in out:
            self.assertAlmostEqual(math.fsum(row) / 4, 1.0, places=12)  # the bias sets the mean
            var = math.fsum((v - 1.0) ** 2 for v in row) / 4
            self.assertAlmostEqual(var, 4.0, places=3)  # the gain squared sets the variance

    def test_layernorm_backward_with_nonunit_gains(self):
        x = [[0.2, -0.4, 1.1], [2.0, 0.3, -0.8]]
        gain, bias = [2.0, 0.5, -1.0], [0.1, -0.2, 0.3]
        dy = [[0.4, -0.7, 0.2], [-0.3, 0.8, 0.5]]
        _, cache = m.layernorm_forward(x, gain, bias)
        dx, dg, db = m.layernorm_backward(dy, gain, cache)

        def loss():
            y, _ = m.layernorm_forward(x, gain, bias)
            return math.fsum(a * b for row, grad in zip(y, dy) for a, b in zip(row, grad))

        def check(values, gradients):
            for i, expected in enumerate(gradients):
                old, epsilon = values[i], 1e-6
                values[i] = old + epsilon
                higher = loss()
                values[i] = old - epsilon
                lower = loss()
                values[i] = old
                self.assertAlmostEqual(expected, (higher - lower) / (2 * epsilon), places=7)

        for row, grad in zip(x, dx):
            check(row, grad)
        check(gain, dg)
        check(bias, db)

    def test_later_token_does_not_change_earlier_logits(self):
        p = series()
        a, _ = m.forward(p, TOK.encode("mia has a red ball."))
        b, _ = m.forward(p, TOK.encode("mia has a red hat."))
        self.assertEqual(a[:4], b[:4])
        self.assertNotEqual(a[4], b[4])

    def test_unused_positions_get_zero_gradient(self):
        p = series()
        ids = TOK.encode("mia has a red ball.")
        logits, cache = m.forward(p, ids[:-1])
        g = m.backward(p, cache, m.loss_and_dlogits(logits, ids[1:])[1])
        self.assertTrue(any(v != 0.0 for v in g["pos_emb"][0]))
        self.assertTrue(all(v == 0.0 for row in g["pos_emb"][len(ids) - 1:] for v in row))


class FailureCases(unittest.TestCase):
    def test_without_positions_the_last_position_cannot_see_word_order(self):
        self.assertEqual(tb.last_logits_gap(series(), TOK, use_positions=False), 0.0)
        self.assertGreater(tb.last_logits_gap(series(), TOK, use_positions=True), 0.0)

    def test_earlier_positions_still_differ_without_positions(self):
        gaps = tb.position_gaps(series(), TOK, use_positions=False)
        self.assertEqual(gaps[-1], 0.0)
        self.assertTrue(all(g > 0 for g in gaps[2:-1]))

    def test_sequence_longer_than_positions(self):
        with self.assertRaisesRegex(ValueError, "longer than the 64 positions"):
            m.forward(series(), [5] * 65)

    def test_token_id_outside_vocabulary(self):
        for ids in ([5, 96], [5, -1]):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "outside the vocabulary"):
                m.forward(series(), ids)

    def test_empty_sequence(self):
        with self.assertRaisesRegex(ValueError, "empty sequence"):
            m.forward(series(), [])

    def test_targets_must_match_positions(self):
        logits, _ = m.forward(series(), [5, 6, 7])
        with self.assertRaisesRegex(ValueError, "3 positions but 2 targets"):
            m.loss_and_dlogits(logits, [6, 7])


if __name__ == "__main__":
    unittest.main()
