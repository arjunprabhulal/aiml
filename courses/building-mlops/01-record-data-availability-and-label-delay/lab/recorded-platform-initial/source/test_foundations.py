import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
import workflow as w
import foundations as f

class FoundationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.source=w.HERE/'scenario.json';self.cohort=self.root/'cohort.json';self.model=self.root/'model.json'
  w.save(self.cohort,w.prepare(self.source));w.save(self.model,w.train(self.cohort))
 def test_time_windows_match_manual_cohort_and_labels_are_ready(self):
  r=f.split_report(self.source);self.assertEqual(r['rows'],{'training':144,'validation':48,'test':48,'excluded':0});self.assertEqual(r['train_validation_shared_entities'],24);self.assertTrue(r['training_labels_ready_before_validation'])
 def test_arrival_and_label_readiness_have_separate_effects(self):
  r=f.availability_report(self.source);self.assertEqual(r['retrospective_event_count'],r['available_event_count']+1);self.assertEqual(r['at_25_hours'],{'label_pending':1});self.assertEqual(r['at_label_readiness'],1)
 def test_costs_use_validation_and_do_not_change_model(self):
  before=self.model.read_bytes();r=f.cost_report(self.cohort,self.model);self.assertEqual(self.model.read_bytes(),before);self.assertFalse(r['final_test_used']);self.assertEqual(r['rows'],48)
  for row in r['candidates']:self.assertEqual(row['total_cost'],row['false_positive']+3*row['false_negative'])
 def test_invalid_costs_are_refused(self):
  for v in [True,-1,float('nan')]:
   with self.subTest(v=v),self.assertRaises(ValueError):f.cost_report(self.cohort,self.model,false_positive=v)
 def test_costs_refuse_different_cohort(self):
  self.cohort.write_text(self.cohort.read_text()+' ')
  with self.assertRaisesRegex(ValueError,'identities differ'):f.cost_report(self.cohort,self.model)
 def test_quarantine_blocks_partial_training(self):
  result=f.validate_source(self.source,self.root/'bad',True);self.assertEqual(result['status'],'blocked');self.assertEqual(result['quarantined'],1);self.assertIsNone(result['training_file']);self.assertTrue((self.root/'bad/source.bin').is_file())
 def test_malformed_source_event_reaches_quarantine(self):
  fixture=w.strict_json(self.source);fixture['events'].append({'id':'broken-source'})
  source=self.root/'bad-source.json';w.save(source,fixture)
  result=f.validate_source(source,self.root/'bad-source-batch')
  self.assertEqual(result['status'],'blocked');self.assertEqual(result['quarantined'],1);self.assertIsNone(result['training_file'])
  self.assertIn(b'broken-source',(self.root/'bad-source-batch/source.bin').read_bytes())
 def test_clean_validation_keeps_every_original_event(self):
  result=f.validate_source(self.source,self.root/'valid');self.assertEqual(result['status'],'ready');self.assertEqual(result['accepted'],len(w.strict_json(self.source)['events']))
 def test_duplicate_identity_quarantines_both_occurrences(self):
  e=w.strict_json(self.source)['events'][0];batch=f.quarantine.validate_batch((json.dumps(e)+'\n'+json.dumps(e)+'\n').encode());self.assertEqual(len(batch['quarantined']),2);self.assertEqual(batch['status'],'blocked')
 def test_history_reconstructs_all_manual_features(self):
  result=f.publish_history(self.source,self.root/'history.db');self.assertEqual(result['matching_assembled_counts'],240)
 def test_historical_prediction_survives_later_correction(self):
  db=self.root/'h.db';f.publish_history(self.source,db);r=f.history_report(self.source,db);self.assertTrue(r['original_view_preserved']);self.assertEqual(r['later_correction_for_same_cutoff'],r['original']+1)
 def test_same_snapshot_parity_and_staleness(self):
  db=self.root/'h.db';f.publish_history(self.source,db);r=f.parity_report(self.source,db);self.assertTrue(r['same_snapshot_parity']);self.assertEqual(r['stale_status'],'stale');self.assertEqual(r['unknown_user_status'],'missing');self.assertEqual(r['different_arrival_rule_value'],r['value']+1)
 def test_current_online_projection_cannot_answer_past_time(self):
  db=self.root/'h.db';f.publish_history(self.source,db);store=f.ReturnHistory(db);self.addCleanup(store.close)
  r=store.read_online('user_events_1d@v1','user-00',f.minute('2026-01-08T12:00:00Z'),60);self.assertEqual(r['status'],'unavailable');self.assertIsNone(r['value'])
 def test_same_version_cannot_change_meaning(self):
  db=self.root/'versions.db';manifest=f.contract(self.source);f.bind_contract(db,manifest);changed=copy.deepcopy(manifest);changed['feature']['window_seconds']=172800
  with self.assertRaisesRegex(ValueError,'different feature'):f.bind_contract(db,changed)
 def test_failed_binding_rolls_back_all_new_components(self):
  db=self.root/'v.db';old=f.contract(self.source);f.bind_contract(db,old)
  # Retain an existing feature binding but remove the dataset binding. The next
  # attempt inserts a dataset first, then fails against that retained feature.
  with sqlite3.connect(db) as connection:connection.execute("DELETE FROM identities WHERE kind='dataset'")
  changed=copy.deepcopy(old);changed['dataset_sha256']='different';changed['feature']['window_seconds']=172800
  with self.assertRaises(ValueError):f.bind_contract(db,changed)
  with sqlite3.connect(db) as connection:self.assertEqual(connection.execute("SELECT COUNT(*) FROM identities WHERE kind='dataset'").fetchone()[0],0)
  self.assertEqual(f.bind_contract(db,old)['contract_id'],f.digest(old))
 def test_snapshot_copies_actual_training_sources(self):
  manifest=f.snapshot(self.source,self.root/'snapshot')
  for name in f.CORE_FILES:self.assertEqual((self.root/'snapshot'/name).read_bytes(),(w.HERE/name).read_bytes())
  self.assertEqual(manifest['dataset_sha256'],w.sha(self.source))
 def test_existing_history_is_never_overwritten(self):
  db=self.root/'h.db';f.publish_history(self.source,db)
  with self.assertRaises(FileExistsError):f.publish_history(self.source,db)

if __name__=='__main__':unittest.main()
