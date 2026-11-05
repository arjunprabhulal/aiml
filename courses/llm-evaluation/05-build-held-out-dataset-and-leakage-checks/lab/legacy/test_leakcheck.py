"""Tests for the held-out checks. Run: python3 -m unittest -v test_leakcheck.py"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import harness
import leakcheck
import make_cases_v2

HERE = Path(__file__).resolve().parent
TASK = harness.load_task("triage_task")
RECORDS = sorted(str(p) for p in (HERE / "records").glob("*.json"))


def stored(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


class LeakTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.cases = harness.load_cases(HERE / "cases.json", TASK)
        self.robust = harness.load_cases(HERE / "cases-robustness.json", TASK)

    def load(self, data):
        path = self.dir / f"cases-{len(list(self.dir.iterdir()))}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return harness.load_cases(path, TASK)

    def edited(self, edit):
        data = copy.deepcopy(stored("cases.json"))
        edit({case["id"]: case for case in data["cases"]}, data)
        return self.load(data)

    def test_recorded_files_match_fresh_checks(self):
        self.assertEqual(make_cases_v2.make(stored("cases.json")), stored("cases-v2.json"))
        self.assertEqual(leakcheck.lock(self.cases), stored("heldout.lock.json"))
        v2 = harness.load_cases(HERE / "cases-v2.json", TASK)
        artifacts = lambda name: [str(HERE / "artifacts" / name)]
        expected = {
            "check-harness-cases": leakcheck.check(self.cases, artifacts("triage.py"), stored("heldout.lock.json"), RECORDS),
            "check-v2": leakcheck.check(v2, artifacts("triage.py"), stored("heldout.lock.json"), RECORDS),
            "check-draft": leakcheck.check(self.robust, artifacts("triage_changes_draft.py")),
            "check-fixed": leakcheck.check(self.robust, artifacts("triage_changes.py")),
        }
        for name, result in expected.items():
            with self.subTest(check=name):
                self.assertEqual(result, stored(f"runs/{name}.json"))

    def test_exact_and_near_duplicates_across_splits_block(self):
        def copy_held(cases, data):
            data["cases"].append(dict(cases["shop-hours"], id="copy", split="development", input="what TIME does your shop open"))
            data["cases"].append(dict(cases["shop-hours"], id="near", split="development", input="What time does the shop open?"))
            data["cases"].append(dict(cases["shop-hours"], id="far", split="development", input="When do you open?"))
        findings = leakcheck.check_overlap(self.edited(copy_held))
        found = {(f["development"], f["held_out"]): f["similarity"] for f in findings}
        self.assertEqual(found[("copy", "shop-hours")], 1.0)
        self.assertGreaterEqual(found[("near", "shop-hours")], leakcheck.NEAR_DUPLICATE)
        self.assertNotIn(("far", "shop-hours"), found)
        self.assertEqual(leakcheck.check_overlap(self.cases), [])

    def test_identical_text_blocks_even_without_shared_words(self):
        def punctuation_only(cases, data):
            data["cases"].append(dict(cases["shop-hours"], id="held-marks", split="held_out", input="?!"))
            data["cases"].append(dict(cases["shop-hours"], id="dev-marks", split="development", input="? !"))
        findings = leakcheck.check_overlap(self.edited(punctuation_only))
        found = {(f["development"], f["held_out"]): f["similarity"] for f in findings}
        self.assertEqual(found[("dev-marks", "held-marks")], 0.0)

    def test_generated_case_in_another_split_than_its_source_blocks(self):
        data = copy.deepcopy(stored("cases-robustness.json"))
        for case in data["cases"]:
            if case["id"] == "cannot-log-in--typo":
                case["split"] = "development"
            if case["id"] == "late-order--greeting":
                case["tags"]["source"] = "missing-case"
        reasons = {f["case"]: f["reason"] for f in leakcheck.check_sources(self.load(data))}
        self.assertEqual(reasons["cannot-log-in--typo"], "in development, its source 'cannot-log-in' is in held_out")
        self.assertEqual(reasons["late-order--greeting"], "source 'missing-case' is not in the case set")
        self.assertEqual(leakcheck.check_sources(self.robust), [])

    def test_held_out_text_copied_into_an_artifact_blocks(self):
        prompt = self.dir / "prompt.py"
        prompt.write_text('EXAMPLES = "Example: a stranger has been buying things -> account"\n'
                          'SHORT = "has been"\n', encoding="utf-8")
        findings = leakcheck.check_artifact(prompt, self.cases)
        copied = [f for f in findings if f["check"] == "copied"]
        self.assertEqual([(f["held_out"], f["severity"]) for f in copied], [("stranger-buying", "block")])
        self.assertEqual(copied[0]["words"], "a stranger has been")

    def test_held_out_only_terms_are_flagged_for_review(self):
        draft = leakcheck.check_artifact(HERE / "artifacts/triage_changes_draft.py", self.robust)
        fixed = leakcheck.check_artifact(HERE / "artifacts/triage_changes.py", self.robust)
        terms = lambda findings: sorted(f["term"] for f in findings if f["check"] == "held-out-only term")
        self.assertEqual(terms(draft), ["desconocido", "iniciar sesión", "log in", "pago", "paquete"])
        self.assertEqual(terms(fixed), ["log in"])
        self.assertTrue(all(f["severity"] == "review" for f in draft))

    def test_docstrings_are_not_terms(self):
        source = self.dir / "rules.py"
        source.write_text('"""Mentions shop open hours."""\n\ndef f():\n    """log in"""\n    return ("charge",)\n',
                          encoding="utf-8")
        self.assertEqual(leakcheck.artifact_strings(source), ["charge"])

    def test_lock_finds_edited_removed_moved_and_added_cases(self):
        locked = leakcheck.lock(self.cases)
        self.assertEqual(leakcheck.check_lock(locked, self.cases), [])

        def change(cases, data):
            cases["cannot-log-in"]["expected"] = {"category": "other"}
            cases["shop-hours"]["split"] = "development"
            data["cases"].remove(cases["arrived-damaged"])
            data["cases"].append(dict(cases["two-payments"], id="new-held-out"))
        reasons = {f["case"]: f["reason"] for f in leakcheck.check_lock(locked, self.edited(change))}
        self.assertEqual(reasons, {"cannot-log-in": "edited", "shop-hours": "moved to development",
                                   "arrived-damaged": "removed", "new-held-out": "added after the lock"})
        with self.assertRaises(leakcheck.LeakError):
            leakcheck.check_lock({"held_out": []}, self.cases)

    def test_held_out_runs_are_counted_for_this_case_set_only(self):
        runs = leakcheck.held_out_runs(RECORDS, self.cases)
        self.assertEqual(sorted(r["record"] for r in runs), ["baseline-final.json", "candidate-final.json"])
        self.assertEqual(leakcheck.held_out_runs(RECORDS, self.robust), [])

    def test_cli_exit_status_blocks_only_on_block_findings(self):
        for cases, status in (("cases-v2.json", 1), ("cases.json", 0)):
            result = subprocess.run([sys.executable, "leakcheck.py", "check", "--cases", cases, "--lock", "heldout.lock.json",
                                     "--artifact", "artifacts/triage.py", "--out", str(self.dir / "out.json")],
                                    cwd=HERE, capture_output=True, text=True)
            self.assertEqual(result.returncode, status, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
