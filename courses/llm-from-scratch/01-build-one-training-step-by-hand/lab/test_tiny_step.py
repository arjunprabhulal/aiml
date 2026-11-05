"""Regression and failure tests for tiny_step.py. Run: python3 -m unittest -v test_tiny_step.py"""
import json
import math
import unittest
from pathlib import Path

import tiny_step as t

TOLERANCE = 1e-6


def batch():
    return t.init_params(), t.encode(t.INPUTS), t.encode(t.TARGETS)


def close(a, b, tol=TOLERANCE):
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k], tol) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


class RecordedTrace(unittest.TestCase):
    def test_recorded_trace(self):
        recorded = json.loads(Path(__file__).with_name("step-trace.json").read_text())
        actual = t.trace()
        self.assertLess(actual["gradient_check"]["max_error_power_of_ten"], -6)
        self.assertTrue(close(recorded, actual))


class Mechanism(unittest.TestCase):
    def test_softmax_handles_large_scores(self):
        self.assertEqual(t.softmax([1000.0, 0.0]), [1.0, math.exp(-1000.0)])

    def test_shapes(self):
        params, ids, targets = batch()
        cache = t.forward(params, ids, targets)
        self.assertEqual(t.shape(cache["x"]), (3, 2))
        self.assertEqual(t.shape(cache["logits"]), (3, 4))
        self.assertTrue(all(math.isclose(sum(row), 1.0) for row in cache["probs"]))

    def test_gradient_check_passes(self):
        params, ids, targets = batch()
        analytic = t.backward(params, ids, targets, t.forward(params, ids, targets))
        numeric = t.numerical_gradients(params, ids, targets)
        self.assertLess(t.max_gradient_error(analytic, numeric), TOLERANCE)

    def test_unused_embedding_rows_get_zero_gradient(self):
        params, ids, targets = batch()
        grads = t.backward(params, ids, targets, t.forward(params, ids, targets))
        for token in ("stop", "go"):
            self.assertEqual(grads["embedding"][t.VOCAB.index(token)], [0.0, 0.0])

    def test_one_step_lowers_loss(self):
        params, ids, targets = batch()
        before, _, _, after = t.train_step(params, ids, targets, t.LEARNING_RATE)
        self.assertLess(after, before)

    def test_step_does_not_modify_input_params(self):
        params, ids, targets = batch()
        snapshot = json.dumps(params)
        t.train_step(params, ids, targets)
        self.assertEqual(json.dumps(params), snapshot)


class FailureCases(unittest.TestCase):
    def test_repeated_ids_must_accumulate(self):
        params, ids, targets = batch()
        cache = t.forward(params, ids, targets)
        numeric = t.numerical_gradients(params, ids, targets)
        buggy = t.backward(params, ids, targets, cache, accumulate=False)
        self.assertGreater(t.max_gradient_error(buggy, numeric), 0.01)

    def test_large_learning_rate_raises_loss(self):
        params, ids, targets = batch()
        before, _, _, after = t.train_step(params, ids, targets, 20)
        self.assertGreater(after, before)

    def test_unknown_token(self):
        with self.assertRaisesRegex(ValueError, "not in the vocabulary"):
            t.encode(["red", "blue"])

    def test_token_id_out_of_range(self):
        params, _, _ = batch()
        for ids, targets in (([0, 4], [2, 3]), ([-1], [2]), ([0], [4]), ([0], [-1]), ([True], [2])):
            with self.subTest(ids=ids, targets=targets), self.assertRaisesRegex(ValueError, "outside the vocabulary"):
                t.forward(params, ids, targets)

    def test_batch_length_mismatch(self):
        params, _, _ = batch()
        with self.assertRaisesRegex(ValueError, "3 inputs but 2 targets"):
            t.forward(params, [0, 1, 0], [2, 3])

    def test_empty_batch(self):
        params, _, _ = batch()
        with self.assertRaisesRegex(ValueError, "empty batch"):
            t.forward(params, [], [])

    def test_matmul_shape_mismatch(self):
        with self.assertRaisesRegex(ValueError, "inner sizes 2 and 3 differ"):
            t.matmul([[1.0, 2.0]], [[1.0], [2.0], [3.0]])

    def test_invalid_learning_rate(self):
        params, ids, targets = batch()
        grads = t.backward(params, ids, targets, t.forward(params, ids, targets))
        for bad in (0, -0.1, float("nan"), float("inf")):
            with self.subTest(learning_rate=bad), self.assertRaisesRegex(ValueError, "positive finite"):
                t.sgd_step(params, grads, bad)


if __name__ == "__main__":
    unittest.main()
