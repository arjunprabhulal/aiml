import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import diagnose as d


class Diagnostics(unittest.TestCase):
    def setUp(self):
        self.context=d.load()
        self.rows={row['id']:row for row in self.context['responses']}

    def changed(self, change):
        row=copy.deepcopy(self.rows['complete']); response=json.loads(row['raw_response'])
        change(response); row['raw_response']=json.dumps(response)
        return d.diagnose(row,self.context)

    def test_complete_fixture_satisfies_all_requirements(self):
        row=d.diagnose(self.rows['complete'],self.context)
        self.assertEqual(row['decision'],'accepted')
        self.assertTrue(all(row[k]['status']=='pass' for k in ('format','source','action','explanation')))

    def test_valid_format_and_action_do_not_hide_unsupported_claim(self):
        row=d.diagnose(self.rows['unsupported-claim'],self.context)
        self.assertEqual(row['format']['status'],'pass');self.assertEqual(row['action']['status'],'pass')
        self.assertEqual(row['source']['status'],'fail');self.assertEqual(row['decision'],'rejected')

    def test_supported_explanation_does_not_make_wrong_proposal_correct(self):
        row=d.diagnose(self.rows['wrong-proposal'],self.context)
        self.assertEqual(row['source']['status'],'pass');self.assertEqual(row['explanation']['status'],'pass')
        self.assertEqual(row['action']['status'],'fail');self.assertEqual(row['decision'],'rejected')

    def test_claimed_execution_and_missing_approval_fail_action_policy(self):
        row=d.diagnose(self.rows['claims-execution'],self.context)
        self.assertFalse(row['action']['checks']['unexecuted_approval_bound'])
        row=self.changed(lambda r:r['proposal'].update(approval_required=False))
        self.assertEqual(row['format']['status'],'pass');self.assertEqual(row['action']['status'],'fail')

    def test_three_new_checks_cannot_replace_existing_explanation_rubric(self):
        row=d.diagnose(self.rows['missing-health-check'],self.context)
        self.assertTrue(all(row[k]['status']=='pass' for k in ('format','source','action')))
        self.assertEqual(row['explanation']['status'],'fail');self.assertEqual(row['decision'],'rejected')

    def test_uncertain_semantic_review_remains_pending(self):
        row=d.diagnose(self.rows['uncertain-support'],self.context)
        self.assertEqual(row['format']['status'],'pass');self.assertEqual(row['action']['status'],'pass')
        self.assertEqual(row['source']['status'],'pending');self.assertEqual(row['decision'],'pending')

    def test_malformed_format_blocks_content_checks(self):
        row=d.diagnose(self.rows['truncated-json'],self.context)
        self.assertEqual(row['decision'],'rejected');self.assertEqual(row['format']['status'],'fail')
        for name in ('source','action','explanation'):self.assertEqual(row[name]['status'],'not_run')

    def test_boolean_type_is_strict_not_integer_alias(self):
        row=d.diagnose(self.rows['integer-for-boolean'],self.context)
        self.assertEqual(row['format']['status'],'fail');self.assertEqual(row['action']['status'],'not_run')

    def test_unknown_fields_and_empty_strings_fail_format(self):
        for change in (lambda r:r.update(extra=True),lambda r:r['answer'].update(text=' '),
                       lambda r:r['proposal'].pop('approval_required'),lambda r:r['answer'].update(citation=None)):
            with self.subTest(change=change):
                self.assertEqual(self.changed(change)['format']['status'],'fail')

    def test_duplicate_nonstandard_and_wrong_json_shapes_refused(self):
        for raw in ('null','[]','{"answer":{},"answer":{},"proposal":{}}','{"x":NaN}'):
            row=copy.deepcopy(self.rows['complete']);row['raw_response']=raw
            with self.subTest(raw=raw):self.assertEqual(d.diagnose(row,self.context)['format']['status'],'fail')

    def test_changed_answer_cannot_reuse_old_semantic_judgement(self):
        row=d.diagnose(self.rows['changed-answer'],self.context)
        self.assertFalse(row['source']['answer_review_bound'])
        self.assertEqual(row['source']['status'],'pending');self.assertEqual(row['action']['status'],'pass')
        self.assertEqual(row['explanation']['status'],'pending');self.assertEqual(row['decision'],'pending')

    def test_citation_match_is_separate_from_semantic_support(self):
        row=self.changed(lambda r:r['proposal'].update(citation='rollback-v2-staging'))
        self.assertEqual(row['format']['status'],'pass');self.assertEqual(row['action']['status'],'pass')
        self.assertFalse(row['source']['citations_match']);self.assertEqual(row['source']['semantic_review'],'pass')
        self.assertEqual(row['source']['status'],'fail');self.assertEqual(row['decision'],'rejected')

    def test_known_failure_remains_visible_while_another_check_is_pending(self):
        row=self.changed(lambda r:(r['answer'].update(text='Unreviewed replacement.'),
                                  r['proposal'].update(proposed_command='wrong command')))
        self.assertEqual(row['source']['status'],'pending');self.assertEqual(row['action']['status'],'fail')
        self.assertEqual(row['decision'],'pending')

    def fixture_root(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        shutil.copytree(d.HERE/'rubric-inputs',root/'rubric-inputs')
        for name in ('responses.json','expected-action.json'):shutil.copyfile(d.HERE/name,root/name)
        return root

    def test_stale_review_and_changed_source_are_refused_at_load(self):
        root=self.fixture_root();p=root/'rubric-inputs/annotations.json';raw=p.read_bytes();data=json.loads(raw)
        data['reviews'][0]['judgements']['support']['rating']='does_not_meet';p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'different judgement revision'):d.load(root)
        p.write_bytes(raw);p=root/'rubric-inputs/source.txt';p.write_text(p.read_text()+'Changed source.\n')
        with self.assertRaisesRegex(ValueError,'different source'):d.load(root)

    def test_duplicate_response_ids_refused(self):
        root=self.fixture_root();p=root/'responses.json';data=json.loads(p.read_text())
        data['responses'].append(copy.deepcopy(data['responses'][0]));p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'duplicate response'):d.load(root)

    def test_unknown_review_reference_refused(self):
        root=self.fixture_root();p=root/'responses.json';data=json.loads(p.read_text())
        data['responses'][0]['rubric_case']='invented';p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'invalid or duplicate'):d.load(root)

    def test_expected_command_must_occur_in_the_guide(self):
        root=self.fixture_root();p=root/'expected-action.json';data=json.loads(p.read_text())
        data['proposed_command']='docuctl erase production';p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'does not occur'):d.load(root)

    def test_record_matches_saved_fixture_results_and_cli(self):
        self.assertEqual(d.record(),json.loads((d.HERE/'result.json').read_text()))
        result=subprocess.run([sys.executable,'diagnose.py','--check'],cwd=d.HERE,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,(d.HERE/'run-output.txt').read_text())


if __name__=='__main__':unittest.main()
