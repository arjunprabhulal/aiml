import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from evaluate_rubric import ROOT, load, record, stable_result, FixtureJudgements, harness
from rubric import fingerprint, validate_rubric
import task


class RubricTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for name in ('source.txt','rubric.json','cases.json','annotations.json'):shutil.copyfile(ROOT/name,self.root/name)

    def edit(self,name,change):
        p=self.root/name;value=json.loads(p.read_text());change(value);p.write_text(json.dumps(value,indent=2)+'\n')

    def rebind_review(self,id):
        annotations=json.loads((self.root/'annotations.json').read_text())
        review=next(row for row in annotations['reviews'] if row['answer_id']==id)
        self.edit('cases.json',lambda data:next(c for c in data['cases'] if c['id']==id)['expected'].update(review_sha256=fingerprint(review)))

    def test_three_valid_expressions_accept_without_exact_sentence_match(self):
        _,decisions=load(self.root)
        for id in ('complete','paraphrase','negation'):self.assertEqual(decisions[id]['status'],'accepted')

    def test_unsupported_guarantee_is_rejected_despite_complete_task_points(self):
        _,decisions=load(self.root);row=decisions['unsupported-guarantee']
        self.assertEqual(row['status'],'rejected');self.assertEqual(row['reason'],'support')
        self.assertTrue(all(rating=='meets' for key,rating in row['ratings'].items() if key!='support'))

    def test_missing_required_verification_is_rejected(self):
        self.assertEqual(load(self.root)[1]['missing-verification']['reason'],'verification')

    def test_old_syntax_remains_a_task_failure(self):
        row=load(self.root)[1]['wrong-command']
        self.assertEqual(row['status'],'rejected');self.assertEqual(row['ratings']['command'],'does_not_meet')

    def test_uncertain_and_unreviewed_remain_pending(self):
        cases,decisions=load(self.root)
        for id in ('uncertain-wording','not-reviewed'):self.assertEqual(decisions[id]['status'],'pending')
        with self.assertRaisesRegex(ValueError,'pending review'):
            FixtureJudgements(decisions).respond(next(c for c in cases['cases'] if c['id']=='not-reviewed'),0)

    def test_coverage_keeps_pending_separate_from_harness_execution(self):
        result=record(self.root);coverage=result['coverage'];summary=result['report']['summary']['development']
        self.assertEqual((coverage['candidates'],coverage['graded'],coverage['pending']),(8,6,2))
        self.assertEqual((summary['pass'],summary['fail'],summary['incomplete']),(3,3,0))
        self.assertEqual(set(r['case_id'] for r in result['report']['results']),set(result['decisions'])-{'uncertain-wording','not-reviewed'})

    def test_changed_answer_cannot_reuse_old_judgement(self):
        self.edit('cases.json',lambda data:data['cases'][0]['input']['answer'].update(text='A different answer.'))
        with self.assertRaisesRegex(ValueError,'different answer'):load(self.root)

    def test_changed_source_and_rubric_are_refused(self):
        p=self.root/'source.txt';p.write_text(p.read_text()+'New source line.\n')
        with self.assertRaisesRegex(ValueError,'different source'):load(self.root)
        shutil.copyfile(ROOT/'source.txt',p)
        self.edit('rubric.json',lambda data:data.update(version=2))
        with self.assertRaisesRegex(ValueError,'different source or rubric'):load(self.root)

    def test_changed_review_requires_explicit_expectation_revision(self):
        self.edit('annotations.json',lambda data:data['reviews'][0]['judgements']['support'].update(rating='does_not_meet'))
        with self.assertRaisesRegex(ValueError,'different judgement revision'):load(self.root)

    def test_missing_criterion_stays_pending_after_explicit_rebinding(self):
        self.edit('annotations.json',lambda data:data['reviews'][0]['judgements'].pop('support'))
        self.rebind_review('complete')
        self.assertEqual(load(self.root)[1]['complete']['status'],'pending')

    def test_pending_priority_keeps_known_failures_visible_without_final_grade(self):
        self.edit('annotations.json',lambda data:data['reviews'][0]['judgements']['support'].update(rating='uncertain'))
        self.edit('annotations.json',lambda data:data['reviews'][0]['judgements']['command'].update(rating='does_not_meet'))
        self.rebind_review('complete')
        row=load(self.root)[1]['complete']
        self.assertEqual(row['status'],'pending')
        self.assertEqual(row['ratings']['command'],'does_not_meet')

    def test_unknown_criterion_and_invalid_rating_are_refused(self):
        self.edit('annotations.json',lambda data:data['reviews'][0]['judgements'].update(invented={}))
        self.rebind_review('complete')
        with self.assertRaisesRegex(ValueError,'unknown criterion'):load(self.root)
        shutil.copyfile(ROOT/'annotations.json',self.root/'annotations.json')
        self.edit('annotations.json',lambda data:data['reviews'][0]['judgements']['support'].update(rating='good'))
        self.rebind_review('complete')
        with self.assertRaisesRegex(ValueError,'invalid judgement'):load(self.root)

    def test_evidence_excerpt_must_match_criterion_and_source(self):
        self.edit('annotations.json',lambda data:data['reviews'][0]['judgements']['support'].update(reference_quote='After the rollback, check service health.'))
        self.rebind_review('complete')
        with self.assertRaisesRegex(ValueError,'bound excerpt'):load(self.root)

    def test_answer_span_cannot_point_to_old_text(self):
        self.edit('annotations.json',lambda data:data['reviews'][0]['judgements']['support'].update(answer_span='Words never present.'))
        self.rebind_review('complete')
        with self.assertRaisesRegex(ValueError,'bound excerpt'):load(self.root)

    def test_duplicate_and_orphan_reviews_are_refused(self):
        self.edit('annotations.json',lambda data:data['reviews'].append(copy.deepcopy(data['reviews'][0])))
        with self.assertRaisesRegex(ValueError,'duplicate review'):load(self.root)
        shutil.copyfile(ROOT/'annotations.json',self.root/'annotations.json')
        self.edit('annotations.json',lambda data:data['reviews'][0].update(answer_id='unknown'))
        with self.assertRaisesRegex(ValueError,'unknown or duplicate'):load(self.root)

    def test_question_change_cannot_reuse_task_rubric(self):
        self.edit('cases.json',lambda data:data['cases'][0]['input'].update(question='Restore my database.'))
        with self.assertRaisesRegex(ValueError,'question'):load(self.root)

    def test_all_pending_has_zero_coverage_and_no_quality_report(self):
        self.edit('annotations.json',lambda data:data.update(reviews=[]))
        self.edit('cases.json',lambda data:[case['expected'].update(review_sha256=fingerprint(None)) for case in data['cases']])
        result=record(self.root)
        self.assertEqual(result['coverage']['graded'],0);self.assertEqual(result['coverage']['pending'],8)
        self.assertIsNone(result['report'])

    def test_changed_expected_revision_changes_case_set_identity(self):
        before=load(self.root)[0]['sha256']
        self.edit('annotations.json',lambda data:data['reviews'][0]['judgements']['support'].update(reason='Revised authored rationale.'))
        self.rebind_review('complete')
        self.assertNotEqual(load(self.root)[0]['sha256'],before)

    def test_runner_is_unchanged_and_report_retains_authored_origin(self):
        result=record(self.root)
        self.assertEqual(result['report']['manifest']['system']['mode'],'authored_annotation_fixture')
        self.assertTrue(all(row['metadata']['origin']=='authored judgement fixture' for row in result['report']['results']))
        self.assertTrue(all(row['metadata']['answer']['text'] for row in result['report']['results']))

    def test_actual_record_ignores_only_run_description_locations(self):
        actual=record(self.root);expected=json.loads((ROOT/'result.json').read_text())
        self.assertEqual(stable_result(actual),stable_result(expected))


if __name__=='__main__':unittest.main()
