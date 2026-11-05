import unittest
from lab import rank_operators


class ProfileTests(unittest.TestCase):
    def test_rank_uses_actual_host_duration(self):
        rows = [
            {"name": "b", "calls": 2, "self_cpu_us": 3},
            {"name": "a", "calls": 1, "self_cpu_us": 7},
        ]
        self.assertEqual(rank_operators(rows)[0]["name"], "a")

    def test_empty_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            rank_operators([])

    def test_nonfinite_duration_is_rejected(self):
        for value in [float("nan"), float("inf"), -1]:
            with self.assertRaises(ValueError):
                rank_operators([{"name": "a", "calls": 1, "self_cpu_us": value}])


if __name__ == "__main__":
    unittest.main()
