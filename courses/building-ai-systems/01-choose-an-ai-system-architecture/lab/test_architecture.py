import json
from pathlib import Path
import unittest
from architecture import Request, Refused, answer, naive_answer
PAGES = json.loads(Path(__file__).with_name("pages.json").read_text())
class ArchitectureTests(unittest.TestCase):
    def test_version_and_environment_bind_source(self):
        got = answer(Request("lookup_rollback", "3", "production"), PAGES)
        self.assertEqual(got["citation"], "rollback-v3-production")
        self.assertNotEqual(got["command_template"], naive_answer(None))
    def test_missing_version_refuses_instead_of_using_old_page(self):
        with self.assertRaisesRegex(Refused, "matching page"):
            answer(Request("lookup_rollback", "9", "staging"), PAGES)
    def test_conflicting_pages_refused(self):
        with self.assertRaises(Refused):
            answer(Request("lookup_rollback", "2", "staging"), PAGES + [PAGES[0]])
    def test_reader_cannot_create_action_proposal(self):
        with self.assertRaisesRegex(Refused, "maintainer"):
            answer(Request("propose_rollback", "3", "production", release="r41"), PAGES)
    def test_proposal_is_bound_but_never_executed(self):
        got=answer(Request("propose_rollback", "3", "production", "maintainer", "r41"), PAGES)
        self.assertTrue(got["approval_required"])
        self.assertFalse(got["executed"])
        self.assertEqual(got["proposed_command"], "docuctl releases rollback r41 --environment production")
    def test_unvalidated_release_refused(self):
        with self.assertRaises(Refused):
            answer(Request("propose_rollback", "3", "production", "maintainer", "r41; rm file"), PAGES)
    def test_unknown_intent_and_environment_refused(self):
        for req in [Request("delete", "3", "staging"), Request("lookup_rollback", "3", "all")]:
            with self.assertRaises(Refused): answer(req, PAGES)
if __name__ == "__main__": unittest.main()
