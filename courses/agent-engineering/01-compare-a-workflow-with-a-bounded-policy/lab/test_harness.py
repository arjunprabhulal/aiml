import subprocess
import tempfile
import unittest
from unittest.mock import patch
from terminal_harness import check_candidate, validate_patch


class HarnessTests(unittest.TestCase):
    def test_imports_cannot_enter_the_candidate(self):
        self.assertEqual(check_candidate('__import__("os").getcwd()')['outcome'], 'rejected_patch')

    def test_unchanged_boundary_bug_fails_actual_checks(self):
        result = check_candidate('attempt <= max_attempts')
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(result['exit_status'], 1)

    def test_valid_fix_passes_the_independent_checker(self):
        r = check_candidate('attempt < max_attempts')
        self.assertEqual((r['outcome'], r['passed'], r['total']), ('passed', 6, 6))

    def test_timeout_is_an_incomplete_trial(self):
        with patch('terminal_harness.subprocess.run', side_effect=subprocess.TimeoutExpired('fixture', 2)):
            self.assertEqual(check_candidate('attempt < max_attempts')['outcome'], 'timeout')

    def test_workspace_is_removed_after_the_candidate(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            check_candidate('attempt < max_attempts', root)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_unbounded_timeout_is_rejected(self):
        with self.assertRaises(ValueError):
            check_candidate('attempt < max_attempts', timeout=None)


if __name__ == '__main__':
    unittest.main()
