"""Offline checks for the selected native evaluation; never run models/services."""
from pathlib import Path
import collections
import hashlib
import json
import unittest
from google.adk.evaluation.eval_result import EvalSetResult
HERE=Path(__file__).resolve().parent
RUN=HERE/'runs/native-2026-10-23'
class SelectedNativeRun(unittest.TestCase):
    def test_native_selected_case_generated_followup_and_fixture_grounding(self):
        run=json.loads((RUN/'run.json').read_text());result=EvalSetResult.model_validate_json((RUN/run['native_result_file']).read_text())
        self.assertEqual(len(result.eval_case_results),1);case=result.eval_case_results[0];self.assertEqual(case.eval_id,run['eval_id'])
        turns=[x.actual_invocation for x in case.eval_metric_result_per_invocation];self.assertEqual(len(turns),run['turn_count']);self.assertEqual(len(turns),2)
        fixture=(HERE/'docs_assistant/docs/install.md').read_text()
        self.assertIn('OLLAMA_API_BASE',fixture);self.assertIn('Python 3.12 or later',fixture)
        self.assertIn('OLLAMA_API_BASE',turns[0].final_response.parts[0].text);self.assertIn('Python 3.12 or later',turns[1].final_response.parts[0].text)
        self.assertEqual(turns[1].user_content.parts[0].text,'Which Python version does the project require?')
        rows=[json.loads(s)for s in(RUN/'receipts/nested-llm.jsonl').read_text().splitlines()]
        simulated=[p.get('text','')for r in rows if r['phase']=='response'and r['role']=='simulator'for p in(r['response'].get('content')or{}).get('parts',[])if not p.get('thought')]
        self.assertIn(turns[1].user_content.parts[0].text,simulated);self.assertTrue(any('</finished>'in s for s in simulated))
    def test_judge_scores_and_native_means_preserve_distinct_scopes(self):
        run=json.loads((RUN/'run.json').read_text());case=json.loads((RUN/run['native_result_file']).read_text())['eval_case_results'][0]
        metric={m['metric_name']:m for m in case['overall_eval_metric_results']}
        for name,m in run['judge_metrics'].items():self.assertEqual(m['score'],metric[name]['score']);self.assertEqual(m['threshold'],metric[name]['threshold']);self.assertEqual(m['status'],metric[name]['eval_status'])
        for name,mean in run['native_means'].items():
            scores=[next(m['score']for m in row['eval_metric_results']if m['metric_name']==name)for row in case['eval_metric_result_per_invocation']]
            self.assertAlmostEqual(mean,sum(scores)/len(scores))
        self.assertFalse(run['cloud_eval_or_task_success_metric_exercised']);self.assertIn('per-agent-invocation means',run['metric_boundary'])
    def test_shared_attempt_ledger_and_supplementary_observer(self):
        run=json.loads((RUN/'run.json').read_text());ledger=json.loads((RUN/'request-ledger.json').read_text())
        self.assertEqual(len(ledger),run['provider_requests']);self.assertLessEqual(len(ledger),run['request_cap']);self.assertTrue(all(v['max_output_tokens']==run['max_output_tokens_per_request']for v in ledger))
        starts=[v for v in map(json.loads,(RUN/'receipts/nested-llm.jsonl').read_text().splitlines())if v['phase']=='start'];self.assertEqual(dict(collections.Counter(v['role']for v in starts)),run['observer_starts']);self.assertEqual(len(starts),len(ledger))
    def test_public_original_hashes_and_only_opaque_fields_omitted(self):
        for row in json.loads((RUN/'public-projection.json').read_text())['files']:
            self.assertEqual(hashlib.sha256((RUN/row['path']).read_bytes()).hexdigest(),row['public_sha256'])
            if not row['opaque_json_fields_omitted']:self.assertEqual(row['private_sha256'],row['public_sha256'])
        opaque={'thoughtSignature','thought_signature','functionCallSignature','function_call_signature'}
        def inspect(v):
            if isinstance(v,dict):
                self.assertFalse(opaque.intersection(v))
                for x in v.values():inspect(x)
            elif isinstance(v,list):
                for x in v:inspect(x)
        for p in RUN.rglob('*'):
            if not p.is_file():continue
            self.assertFalse(p.read_bytes().startswith(b'SQLite format 3\x00'))
            if p.suffix=='.json':inspect(json.loads(p.read_text()))
            elif p.suffix=='.jsonl':
                for line in p.read_text().splitlines():
                    if line:inspect(json.loads(line))
if __name__=='__main__':unittest.main()
