import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import workflow as w


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'cohort.json';self.model=self.root/'model.json'
        self.cohort=w.prepare(w.HERE/'scenario.json');w.save(self.data,self.cohort)

    def fit(self):
        model=w.train(self.data);w.save(self.model,model);return model

    def test_late_events_never_enter_features(self):
        self.assertTrue(self.cohort['rows'])
        self.assertFalse(any(e.endswith('-late') for row in self.cohort['rows'] for e in row['feature_event_ids']))

    def test_label_readiness_is_enforced_by_reused_assembler(self):
        source=w.strict_json(w.HERE/'scenario.json');source['assemble_at']='2026-01-04T12:00:00Z'
        path=self.root/'early.json';w.save(path,source);cohort=w.prepare(path)
        self.assertFalse(cohort['rows']);self.assertTrue(cohort['excluded'])

    def test_fit_and_scaler_receive_training_only(self):
        expected=[r['feature_count'] for r in self.cohort['rows'] if r['split']=='training']
        original=w.baseline.train_logistic
        def inspect(rows,scaler):
            self.assertEqual([r['x'][0] for r in rows],expected)
            self.assertAlmostEqual(scaler['mean'][0],sum(expected)/len(expected))
            return original(rows,scaler)
        with patch.object(w.baseline,'train_logistic',side_effect=inspect):self.fit()

    def test_model_reload_matches_in_memory_prediction(self):
        model=self.fit();loaded=w.load_model(self.model)
        for count in [0,3,8]:self.assertEqual(w.predict(model,count),w.predict(loaded,count))

    def test_new_process_prediction_matches(self):
        model=self.fit();r=subprocess.run([sys.executable,str(w.HERE/'workflow.py'),'predict','--model',str(self.model),'--event-count','3'],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(r.stdout),w.predict(model,3))

    def test_evaluation_uses_declared_validation_rows(self):
        self.fit();result=w.evaluate(self.data,self.model)
        self.assertEqual(result['rows'],sum(r['split']=='validation' for r in self.cohort['rows']))
        self.assertEqual(result['split'],'validation')

    def test_changed_cohort_refuses_model_evaluation(self):
        self.fit();self.data.write_text(self.data.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'identities differ'):w.evaluate(self.data,self.model)

    def test_forged_split_is_refused(self):
        self.cohort['rows'][0]['split']='validation';self.data.write_text(json.dumps(self.cohort))
        with self.assertRaisesRegex(ValueError,'time split'):w.train(self.data)

    def test_duplicate_observation_is_refused(self):
        self.cohort['rows'].append(self.cohort['rows'][0]);self.data.write_text(json.dumps(self.cohort))
        with self.assertRaisesRegex(ValueError,'duplicate'):w.train(self.data)

    def test_non_binary_and_boolean_labels_are_refused(self):
        for value in [None,True,2]:
            with self.subTest(value=value):
                data=copy.deepcopy(self.cohort);data['rows'][0]['label']=value;self.data.write_text(json.dumps(data))
                with self.assertRaises(ValueError):w.train(self.data)

    def test_bad_feature_counts_are_refused(self):
        model=self.fit()
        for value in [-1,1001,True,None,1.5,float('nan')]:
            with self.subTest(value=value),self.assertRaises(ValueError):w.predict(model,value)

    def test_malformed_model_is_refused(self):
        original=self.fit()
        for field,value in [('weights',[]),('weights',[True]),('weights',[float('nan')]),('bias',None)]:
            with self.subTest(field=field,value=value):
                model=copy.deepcopy(original);model['estimator'][field]=value;self.model.write_text(json.dumps(model))
                with self.assertRaises(ValueError):w.load_model(self.model)

    def test_zero_scaler_is_refused(self):
        model=self.fit();model['preprocessing']['std']=[0];self.model.write_text(json.dumps(model))
        with self.assertRaises(ValueError):w.load_model(self.model)

    def test_existing_artifact_is_not_overwritten(self):
        original=self.data.read_bytes()
        with self.assertRaises(FileExistsError):w.save(self.data,{'changed':True})
        self.assertEqual(original,self.data.read_bytes())


if __name__=='__main__':unittest.main()
