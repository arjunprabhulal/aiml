import copy,json,math,unittest
from pathlib import Path
from cross_encoder import accept_scores,MODEL,REVISION
class CrossEncoderTests(unittest.TestCase):
 def setUp(self):
  root=Path(__file__).parent;self.snapshot=json.loads((root/'fixtures/snapshot.json').read_text());self.record=json.loads((root/'runs/cross-encoder-v1/result.json').read_text());self.row=self.record['original_candidate_comparison'][0]
 def test_actual_scores_replay_exact_candidate_binding_without_model(self):
  self.assertEqual(self.record['model']['model'],MODEL);self.assertEqual(self.record['model']['revision'],REVISION)
  for row in self.record['original_candidate_comparison']+self.record['expanded_cases']:
   self.assertEqual(accept_scores(row['question'],row['candidates'],self.snapshot,row['scores_in_candidate_order']),row['cross_encoder'])
 def test_nonfinite_missing_duplicate_and_changed_candidates_refused(self):
  q=self.row['question'];rows=self.row['candidates'];scores=self.row['scores_in_candidate_order']
  for invalid in (scores[:-1],[math.nan]*len(rows),[math.inf]*len(rows)):
   with self.assertRaises(ValueError):accept_scores(q,rows,self.snapshot,invalid)
  changed=copy.deepcopy(rows);changed[0]['text']='altered'
  with self.assertRaises(ValueError):accept_scores(q,changed,self.snapshot,scores)
  with self.assertRaises(ValueError):accept_scores(q,rows+[rows[0]],self.snapshot,scores+[0])
 def test_missing_candidate_cannot_be_recovered(self):
  rows=self.row['candidates'][1:];ranked=accept_scores(self.row['question'],rows,self.snapshot,self.row['scores_in_candidate_order'][1:])
  self.assertNotIn(self.row['candidates'][0]['chunk_id'],[r['chunk_id'] for r in ranked]);self.assertEqual(accept_scores(self.row['question'],[],self.snapshot,[]),[])
if __name__=='__main__':unittest.main()
