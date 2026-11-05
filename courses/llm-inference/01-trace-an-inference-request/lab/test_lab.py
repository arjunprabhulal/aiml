import unittest
from lab import summarize


class TraceTests(unittest.TestCase):
    def sample(self):
        return {
            "generated_tokens": 3,
            "generated_token_ids": [4, 5, 6],
            "ttft_ms": 10,
            "e2e_ms": 30,
            "itl_ms": [8, 12],
        }

    def test_average_decode_interval_excludes_prefill(self):
        result = summarize([self.sample()])
        self.assertEqual(result["median_ttft_ms"], 10)
        self.assertEqual(result["median_tpot_ms"], 10)

    def test_rejects_missing_token_interval(self):
        sample = self.sample()
        sample["itl_ms"] = [8]
        with self.assertRaisesRegex(ValueError, "Missing token intervals"):
            summarize([sample])

    def test_rejects_end_before_first_token(self):
        sample = self.sample()
        sample["e2e_ms"] = 2
        with self.assertRaisesRegex(ValueError, "Invalid token timing"):
            summarize([sample])

    def test_rejects_inconsistent_generated_count(self):
        sample = self.sample()
        sample["generated_tokens"] = 2
        with self.assertRaisesRegex(ValueError, "Token count mismatch"):
            summarize([sample])


class TraceBoundaryTests(unittest.TestCase):
    def test_one_token_has_no_tpot(self):
        self.assertIsNone(
            summarize(
                [
                    {
                        "generated_tokens": 1,
                        "generated_token_ids": [4],
                        "ttft_ms": 10,
                        "e2e_ms": 10,
                        "itl_ms": [],
                    }
                ]
            )["median_tpot_ms"]
        )

    def test_negative_and_nonfinite_intervals_are_rejected(self):
        for interval in [-1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                summarize(
                    [
                        {
                            "generated_tokens": 2,
                            "generated_token_ids": [4, 5],
                            "ttft_ms": 10,
                            "e2e_ms": 20,
                            "itl_ms": [interval],
                        }
                    ]
                )


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('summarize([])', 'At least one'), ('summarize([dict(generated_tokens=1,generated_token_ids=[1],ttft_ms=float("nan"),e2e_ms=0,itl_ms=[])])', 'Timing values'), ('summarize([dict(generated_tokens=2,generated_token_ids=[1,2],ttft_ms=10,e2e_ms=20,itl_ms=[9])])', 'Intervals do not')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
