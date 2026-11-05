from __future__ import annotations

import unittest

from lab import (
    expected_tokens_per_step,
    marginal_output_distribution,
    run_verification_demo,
    speculative_speedup_by_batch,
    total_variation_distance,
)


class TestSpeculativeDecodingLab(unittest.TestCase):
    def test_greedy_threshold_without_residual_breaks_target_distribution(self) -> None:
        p = [0.10, 0.48, 0.18, 0.24]
        q = [0.05, 0.15, 0.60, 0.20]
        exact_marginal = marginal_output_distribution(p, q, use_residual=True)
        buggy_marginal = marginal_output_distribution(p, q, use_residual=False)
        self.assertLessEqual(total_variation_distance(p, exact_marginal), 1e-7)
        self.assertGreater(total_variation_distance(p, buggy_marginal), 0.12)

    def test_high_batch_speculative_verification_slows_down_step_time(self) -> None:
        rows = {row["batch_size"]: row for row in speculative_speedup_by_batch(gamma=4)}
        self.assertGreater(rows[1]["alpha_80_speedup"], 2.0)
        self.assertLess(rows[32]["alpha_80_speedup"], 1.0)
        self.assertLessEqual(rows[64]["alpha_80_speedup"], 0.75)

    def test_rejection_truncates_remaining_draft_and_resamples_residual(self) -> None:
        demo = run_verification_demo()["verification_step"]
        self.assertEqual(demo["accepted_draft_tokens"], 2)
        self.assertEqual(demo["total_emitted"], 3)
        self.assertEqual(demo["emitted_tokens"], [0, 1, 1])

    def test_expected_tokens_formula_matches_boundaries(self) -> None:
        self.assertEqual(expected_tokens_per_step(0.0, 4), 1.0)
        self.assertEqual(expected_tokens_per_step(1.0, 4), 5.0)
        self.assertAlmostEqual(expected_tokens_per_step(0.80, 4), 3.3616, places=4)


class ProbabilityValidationTests(unittest.TestCase):
    def test_invalid_probability_distribution_is_rejected(self):
        from lab import residual_distribution

        for vector in [[0.5, -0.5], [float("nan"), 1], [0.2, 0.2]]:
            with self.assertRaises(ValueError):
                residual_distribution(vector, [0.5, 0.5])

    def test_zero_draw_cannot_select_zero_probability_token(self):
        from lab import _sample_from_cdf

        self.assertEqual(_sample_from_cdf([0, 1], 0), 1)


if __name__ == "__main__":
    unittest.main()


class GuardBoundaryTests(unittest.TestCase):
    def test_rejects_invalid_boundary_inputs_with_specific_reason(self):
        import lab
        cases = [('residual_distribution([1],[0.5,0.5])', 'Vocabulary sizes'), ('marginal_output_distribution([1],[0.5,0.5], use_residual=False)', 'Vocabulary sizes'), ('verify_speculative_draft([0],[],[[1],[1]],[0],[0,0])', 'target_probs must have length'), ('verify_speculative_draft([0],[[1]],[[1],[1]],[],[0,0])', 'Draw counts'), ('verify_speculative_draft([0],[[1]],[[1],[1]],[1],[0,0])', 'Draws must'), ('verify_speculative_draft([0],[[1]],[[0.5,0.5],[1]],[0],[0,0])', 'Vocabulary sizes'), ('verify_speculative_draft([0],[[0,1]],[[0.5,0.5],[0.5,0.5]],[0],[0,0])', 'positive proposal'), ('expected_tokens_per_step(-1,1)', 'alpha must'), ('expected_tokens_per_step(0.5,0)', 'gamma must')]
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex((ValueError, MemoryError, KeyError, RuntimeError), reason):
                    exec(code, vars(lab).copy())
