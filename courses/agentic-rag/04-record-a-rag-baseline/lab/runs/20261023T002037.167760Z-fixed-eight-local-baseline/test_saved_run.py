"""Offline checks of the actual saved baseline and its displayed summary."""
import hashlib,importlib.util,json,re,shutil,socket,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
RUN=Path(__file__).resolve().parent
LAB=RUN.parents[1]
def read(name):return json.loads((RUN/name).read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('saved_baseline_report',RUN/'render_report.py');report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)
class SavedBaselineTests(unittest.TestCase):
 def test_frozen_source_files_match_actual_recording(self):
  m=read('run-manifest.json');self.assertEqual(len(m['source_hashes']),27)
  self.assertTrue(all(sha(LAB/p)==value for p,value in m['source_hashes'].items()))
  self.assertTrue(all(sha(RUN/p)==value for p,value in m['artifacts'].items()))
 def test_one_trial_for_each_frozen_case(self):
  r=read('recording.json');self.assertEqual(len(r['responses']),8)
  self.assertEqual(r['case_set_sha256'],'1603dde3e9e4d3fbafb14126e5c002584c6f945c29968488b01406618a6035b9')
  self.assertTrue(all(len(trials)==1 for trials in r['responses'].values()))
 def test_actual_local_request_counts_and_limits(self):
  ledger=read('http-ledger.json');c=ledger['counts']
  self.assertEqual((c['documents'],len(c['queries']),len(c['generation']),c['metadata']),(1,8,8,1))
  self.assertEqual(len(ledger['http']),18);self.assertTrue(all(x.get('status')==200 for x in ledger['http']))
  self.assertTrue(all(x['allowed']for x in ledger['network']))
  self.assertTrue(all(x['body']['options']=={'temperature':0,'num_predict':400}for x in ledger['http']if x['stage']=='generation'))
 def test_unsupported_does_not_receive_a_positive_retrieval_score(self):
  rows=read('measurements.json')['rows'];empty=[r for r in rows if not r['annotated_target_chunk_ids']]
  self.assertEqual(len(empty),3);self.assertTrue(all(r['retrieval']is None for r in empty))
  row=next(r for r in rows if r['case_id']=='read-newline-312');self.assertEqual(row['retrieval']['reciprocal_rank'],.5)
 def test_length_stop_stays_empty_and_incomplete(self):
  o=read('case-observations.json')['create-parents']['generation'];self.assertEqual(o['raw']['content'],'');self.assertIsNone(o['parsed'])
  self.assertEqual(o['raw']['response_metadata']['done_reason'],'length');self.assertTrue(o['parsing_error'])
  self.assertIn('error',read('recording.json')['responses']['create-parents'][0])
 def test_factual_negative_does_not_silently_fix_wrong_status(self):
  o=read('recording.json')['responses']['read-newline-312'][0]['output'];self.assertEqual(o['status'],'not_in_docs');self.assertEqual(o['source_ids'],[])
  self.assertIn('3.13',o['answer']);self.assertIn('not available in Python3.12'.replace('Python3','Python 3'),o['answer'])
 def test_human_template_is_unreviewed_and_assistant_inspection_is_named(self):
  self.assertTrue(all(x['verdict']=='unreviewed'and x['reviewer']is None for x in read('human-review.json')['cases'].values()))
  ai=read('assistant-review.json');self.assertEqual(ai['assessment_kind'],'assistant_semantic_inspection');self.assertEqual(ai['raw_record_file_sha256'],sha(RUN/'recording.json'))
 def test_saved_report_is_offline_and_does_not_invent_expected_answers(self):
  def deny(*a,**k):raise AssertionError('Report attempted network')
  with patch('socket.socket.connect',deny),patch('socket.getaddrinfo',deny):html=report.render()
  self.assertEqual(html.count('<article>'),3);self.assertIn('Three diagnostic cases',html);self.assertIn('5 automatic passes',html)
  self.assertIn('No parsed response',html);self.assertNotIn('Expected answer:',html)
  self.assertFalse(re.search(r'/Users/|/private/|/tmp/|AIza|ya29\.',html));self.assertIn('Human answer review is unreviewed',html)
 def test_changed_saved_artifact_is_refused_by_report(self):
  with tempfile.TemporaryDirectory()as d:
   folder=Path(d);shutil.copytree(RUN,folder/'saved');changed=folder/'saved';(changed/'measurements.json').write_text('{}')
   with patch.object(report,'RUN',changed),self.assertRaisesRegex(ValueError,'Saved artifact changed'):report.render()
 def test_real_media_dimensions_hashes_and_raw_bindings(self):
  media=read('media-index.json');self.assertEqual(media['source_record_sha256'],sha(RUN/'recording.json'));self.assertEqual(media['renderer_sha256'],sha(RUN/'render_report.py'))
  self.assertEqual({i['css_viewport_width']for i in media['images']},{1440,760,390,320})
  for image in media['images']:
   p=RUN/image['file'];self.assertEqual(sha(p),image['sha256']);self.assertEqual(struct.unpack('>II',p.read_bytes()[16:24]),(image['pixel_width'],image['pixel_height']));self.assertEqual(image['pixel_width'],image['css_viewport_width']*2)
if __name__=='__main__':unittest.main(verbosity=2)
