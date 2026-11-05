import copy,unittest
from unittest.mock import patch
from release_check import check,seal,inputs

class ReleaseTests(unittest.TestCase):
    def test_release_binds_evaluator_dependencies_and_launchers(self):
        for name in ['evaluate.py','requirements-lock.txt','release_check.py','record_demo.py','cli.py']:
            self.assertIn(name,inputs())
    def test_current_bundle_matches(self):self.assertEqual(check(seal())['evaluation']['provider'],'extractive')
    def test_changed_file_hash_is_refused(self):
        saved=seal();saved['files']['assistant.py']='changed'
        with self.assertRaises(ValueError):check(saved)
    def test_saved_pass_count_is_not_trusted(self):
        saved=seal();saved['evaluation']['passed']=0
        with self.assertRaises(ValueError):check(saved)
    def test_failing_actual_evaluation_blocks_sealing(self):
        with patch('release_check.evaluate',return_value={'passed':0,'total':1}):
            with self.assertRaisesRegex(ValueError,'case failed'):seal()
if __name__=='__main__':unittest.main()
