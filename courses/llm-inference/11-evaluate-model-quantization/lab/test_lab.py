import unittest
from lab import compare_scores


class QuantizationEvidenceTests(unittest.TestCase):
    def case(self, nll=2, text="text"):
        return {"text": text, "predicted_tokens": 3, "nll": nll}

    def test_likelihood_regression_is_visible(self):
        report = compare_scores([self.case()], [self.case(3)])
        self.assertTrue(report["likelihood_regression"])
        self.assertEqual(report["nll_increase"], 1)

    def test_comparing_different_cases_is_rejected(self):
        with self.assertRaises(ValueError):
            compare_scores([self.case()], [self.case(text="other")])

    def test_invalid_likelihood_is_rejected(self):
        for nll in [float("nan"), float("inf"), -1]:
            with self.assertRaises(ValueError):
                compare_scores([self.case()], [self.case(nll)])


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('compare_scores([],[])', 'Matched development')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
