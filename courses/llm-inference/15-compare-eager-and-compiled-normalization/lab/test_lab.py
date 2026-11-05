import unittest
from lab import compare_case


class FusionEvidenceTests(unittest.TestCase):
    def case(self):
        return {
            "rows": 1,
            "width": 3,
            "max_abs_error": 0,
            "timings": {
                "eager": {"samples_ms": [1, 3, 2]},
                "compiled": {"samples_ms": [2, 2, 2]},
            },
        }

    def test_parity_is_required_before_timing(self):
        case = self.case()
        case["max_abs_error"] = 0.1
        with self.assertRaises(ValueError):
            compare_case(case)

    def test_invalid_execution_timing_is_rejected(self):
        case = self.case()
        case["timings"]["compiled"]["samples_ms"] = [-1]
        with self.assertRaises(ValueError):
            compare_case(case)

    def test_medians_are_compared_without_a_speedup_promise(self):
        result = compare_case(self.case())
        self.assertEqual(result["eager_median_ms"], 2)
        self.assertEqual(result["compiled_median_ms"], 2)


if __name__ == "__main__":
    unittest.main()
