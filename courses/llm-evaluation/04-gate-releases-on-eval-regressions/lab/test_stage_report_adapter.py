import copy,json,unittest
from pathlib import Path
from stage_report_adapter import adapt,compare
class AdapterTests(unittest.TestCase):
 def setUp(self):self.report=json.loads((Path(__file__).parent/'fixtures/stage-reports/gemini-3.8-flash.json').read_text())
 def test_saved_embedding_change_is_incomparable(self):
  other=json.loads((Path(__file__).parent/'fixtures/stage-reports/gemma4-e2b.json').read_text())
  self.assertEqual(compare(self.report,other)['decision'],'incomparable')
 def test_known_baseline_failure_remains_blocking(self):
  result=compare(self.report,self.report)
  self.assertEqual(result['decision'],'block')
  self.assertIn('docs-stages::pipe-colors::test_faithfulness',result['critical_failures'])
 def test_controlled_regression_with_matching_contract_blocks(self):
  c=copy.deepcopy(self.report);c['rows'][0]['tools']={'score':0,'unexpected':['delete_file'],'pass':False};c['rows'][0]['first_failure']='tools'
  result=compare(self.report,c);self.assertEqual(result['decision'],'block');self.assertIn('docs-stages::backup::test_tools',result['regressed'])
 def test_missing_duplicate_nonfinite_and_inconsistent_data_fail_closed(self):
  for mutate in [lambda r:r['rows'][0]['judged'].pop('faithfulness'),lambda r:r['rows'].append(r['rows'][0]),lambda r:r['rows'][0]['judged']['faithfulness'].update(score=float('nan')),lambda r:r['rows'][0].update(first_failure='tools'),lambda r:r.update(rows=[])]:
   r=copy.deepcopy(self.report);mutate(r)
   with self.assertRaises((ValueError,KeyError)):adapt(r)
 def test_changed_judge_and_missing_case_are_incomparable(self):
  c=copy.deepcopy(self.report);c['key']['judge']='different';self.assertEqual(compare(self.report,c)['decision'],'incomparable')
  c=copy.deepcopy(self.report);c['rows'].pop();self.assertEqual(compare(self.report,c)['decision'],'incomparable')
 def test_na_is_omitted_and_provenance_retained(self):
  r=adapt(self.report);ids=[t['nodeid'] for t in r['tests']]
  self.assertNotIn('docs-stages::thanks::test_retrieval',ids);self.assertEqual(r['provenance']['source_metrics'],self.report['rows'])
class AdapterCommandTests(unittest.TestCase):
 def test_saved_adapter_decision_replays_and_cli_returns_nonzero(self):
  import subprocess,sys,tempfile
  root=Path(__file__).parent
  before=root/'fixtures/stage-reports/gemini-3.8-flash.json';after=root/'fixtures/stage-reports/gemma4-e2b.json'
  saved=json.loads((root/'runs/stage-adapter/result.json').read_text())
  self.assertEqual(compare(json.loads(before.read_text()),json.loads(after.read_text())),saved['decision'])
  with tempfile.TemporaryDirectory() as d:
   result=subprocess.run([sys.executable,str(root/'stage_report_adapter.py'),str(before),str(after),'--out',str(Path(d)/'result.json')],capture_output=True,text=True)
   self.assertEqual(result.returncode,2,result.stderr)
 def test_controlled_all_passing_report_passes(self):
  r=json.loads((Path(__file__).parent/'fixtures/stage-reports/gemini-3.8-flash.json').read_text())
  for row in r['rows']:
   if row['retrieval'] is not None:row['retrieval']['recall']=1
   for metric in row['judged'].values():metric['score']=1
   row['first_failure']=None
  self.assertEqual(compare(r,r)['decision'],'pass')
if __name__=='__main__':unittest.main()
