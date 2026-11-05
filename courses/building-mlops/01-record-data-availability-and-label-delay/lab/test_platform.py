"""Offline integration checks for pipeline, release, serving and operation."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import workflow as w
import foundations as f
import pipeline
import release
import serving
import rollout
import operations


class PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.training=pipeline.run(w.HERE/'scenario.json',cls.root/'pipeline',True)
        cls.trainingpath=cls.root/'pipeline.json';w.save(cls.trainingpath,cls.training)
        release.package_candidate(cls.trainingpath,cls.root/'bundle')
        cls.cohort=Path(cls.training['workspace'])/'cohort.json'
        cls.model=Path(cls.training['workspace'])/'tracker/runs'/cls.training['run_id']/'workspace/outputs/candidate.json'
        cls.rows=[{'id':r['id'],'entity':r['entity'],'predict_at':r['predict_at'],'feature_at':r['predict_at'],'recent_event_count':r['feature_count']} for r in w.cohort(cls.cohort)['rows'] if r['split']=='validation']

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_completed_retry_does_not_repeat_training(self):
        self.assertEqual(self.training['receipt_attempts'],2)
        repeated=pipeline.run(w.HERE/'scenario.json',self.root/'pipeline')
        self.assertTrue(repeated['reused']);self.assertEqual(repeated['run_id'],self.training['run_id'])
        self.assertEqual(repeated['workspace'],self.training['workspace'])
        self.assertEqual(len(list((Path(self.training['workspace'])/'tracker/runs').iterdir())),1)

    def test_invalid_event_batch_cannot_train(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture=w.strict_json(w.HERE/'scenario.json');fixture['events'].append({'id':'bad'})
            w.save(root/'bad.json',fixture)
            with self.assertRaisesRegex(ValueError,'invalid batch'):pipeline.run(root/'bad.json',root/'attempt')
            self.assertEqual(list((root/'attempt').rglob('candidate.json')),[])
            self.assertEqual(len(list((root/'attempt').rglob('quarantine.jsonl'))),1)

    def test_incomplete_attempt_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/pipeline.pipeline_identity(w.HERE/'scenario.json');folder.mkdir();(folder/'interrupted').write_text('retained')
            with self.assertRaisesRegex(ValueError,'incomplete attempt'):pipeline.run(w.HERE/'scenario.json',tmp)
            self.assertTrue((folder/'interrupted').exists())

    def test_completed_cohort_tampering_is_refused(self):
        raw=self.cohort.read_bytes()
        try:
            value=w.strict_json(self.cohort);value['rows'][0]['feature_count']+=1;self.cohort.write_text(json.dumps(value))
            with self.assertRaises(ValueError):pipeline.run(w.HERE/'scenario.json',self.root/'pipeline')
        finally:self.cohort.write_bytes(raw)

    def test_gate_recomputes_validation_and_retains_failed_candidate(self):
        good=release.gate(self.cohort,self.model);self.assertTrue(good['passed']);self.assertEqual(good['validation']['correct'],29)
        with tempfile.TemporaryDirectory() as tmp:
            weak=w.load_model(self.model);weak['estimator']={'weights':[0.0],'bias':0.0};path=Path(tmp)/'weak.json';w.save(path,weak)
            result=release.gate(self.cohort,path);self.assertFalse(result['passed']);self.assertTrue(path.exists())
            self.assertEqual(result['validation']['correct'],21)

    def test_policy_rejects_nonfinite_or_final_test_permission(self):
        for key,value in [('minimum_accuracy',float('nan')),('threshold',True),('final_test_allowed',True)]:
            with self.subTest(field=key),self.assertRaises(ValueError):release.gate(self.cohort,self.model,dict(release.POLICY,**{key:value}))

    def test_registry_roundtrip_and_alias_does_not_select_failed_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);registry=Path(self.training['workspace'])/'tracker'
            first=release.register(self.root/'bundle',registry);selected,version=release.selected(registry)
            self.assertEqual(version,first['version']);self.assertEqual(serving.Predictor(selected).manifest['model_sha256'],self.training['model_sha256'])
            release.package_candidate(self.trainingpath,root/'blocked',dict(release.POLICY,minimum_accuracy=0.99))
            blocked=release.register(root/'blocked',registry);self.assertFalse(blocked['review_alias_selected'])
            self.assertEqual(release.selected(registry)[1],first['version'])
            with self.assertRaisesRegex(ValueError,'failed'):release.selected(registry,blocked['version'])

    def test_bundle_tampering_and_incompatible_application_are_refused(self):
        for kind in ['model','code']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                copyto=Path(tmp)/'bundle';shutil.copytree(self.root/'bundle',copyto)
                if kind=='model':(copyto/'candidate.json').write_text('{}')
                else:
                    value=w.strict_json(copyto/'bundle.json');value['serving_code_sha256']='0'*64;(copyto/'bundle.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):release.load_bundle(copyto)

    def test_batch_uses_same_predictor_and_rejects_duplicate_ids(self):
        output=serving.batch(self.root/'bundle',self.rows)
        self.assertEqual(len(output['predictions']),48)
        for result,row in zip(output['predictions'],self.rows):
            self.assertEqual(result['return_probability'],w.predict(w.load_model(self.model),row['recent_event_count'])['return_probability'])
        with self.assertRaisesRegex(ValueError,'duplicate'):serving.batch(self.root/'bundle',[self.rows[0],self.rows[0]])

    def test_http_null_booleans_nonfinite_duplicate_fields_and_parity(self):
        from fastapi.testclient import TestClient
        with TestClient(serving.create_app(self.root/'bundle')) as client:
            self.assertEqual(client.get('/health').status_code,200)
            good=client.post('/predict',json=self.rows[0]);self.assertEqual(good.status_code,200)
            self.assertEqual(good.json()['return_probability'],serving.Predictor(self.root/'bundle').predict(self.rows[0])['return_probability'])
            for value in [None,[],{},dict(self.rows[0],recent_event_count=True),dict(self.rows[0],extra='no'),dict(self.rows[0],feature_at='2026-01-01T12:00:00Z')]:
                self.assertEqual(client.post('/predict',json=value).status_code,422)
            for raw in ['{"id":"x","id":"y"}','NaN','{"recent_event_count":Infinity}']:
                self.assertEqual(client.post('/predict',content=raw).status_code,422)

    def test_staging_is_atomic_and_rollback_retains_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            routing=rollout.Routing(Path(tmp)/'routing.sqlite')
            try:
                routing.stage(self.root/'bundle',self.root/'bundle',0,0)
                staged=routing.stage(self.root/'bundle',self.root/'bundle',25,1)
                outputs=[routing.predict(row) for row in self.rows]
                self.assertEqual({r['route'] for r in outputs},{'stable','candidate'})
                self.assertTrue(all((r['bucket']<25)==(r['route']=='candidate') for r in outputs))
                with self.assertRaisesRegex(ValueError,'routing changed'):routing.stage(self.root/'bundle',self.root/'bundle',100,1)
                self.assertEqual(routing.current()['generation'],2)
                restored=routing.rollback(1,2);self.assertEqual((restored['percent'],restored['generation']),(0,3))
                self.assertEqual(routing.db.execute('SELECT count(*) FROM releases').fetchone()[0],3)
            finally:routing.close()

    def test_metrics_separate_invalid_inputs_from_quality(self):
        events,predictions=operations.measure(self.root/'bundle',self.rows+[None])
        report=operations.service_report(events);self.assertEqual(report['status_counts'],{'ok':48,'invalid':1});self.assertFalse(report['prediction_quality_measured'])
        with self.assertRaises(ValueError):operations.service_report([{'status':'ok','elapsed_ms':-1}])
        with self.assertRaises(ValueError):operations.service_report(events*100)

    def test_labels_are_pending_before_ready_and_finalized_later(self):
        fixture=w.strict_json(w.HERE/'scenario.json');predictions=serving.batch(self.root/'bundle',self.rows)['predictions']
        first=[p for p in predictions if p['predict_at'].startswith('2026-01-10')]
        early=operations.evaluate_delayed(first,fixture,'2026-01-11T13:00:00Z')
        self.assertEqual((early['pending'],early['scored'],early['accuracy']),(24,0,None))
        ready=operations.evaluate_delayed(predictions,fixture,'2026-01-13T14:00:00Z')
        self.assertEqual((ready['scored'],ready['correct']),(48,29))
        with self.assertRaisesRegex(ValueError,'duplicate'):operations.evaluate_delayed(first+first,fixture,'2026-01-13T14:00:00Z')

    def test_drift_is_distribution_only_and_invalid_data_is_repair(self):
        reference=[r['recent_event_count'] for r in self.rows]
        equal=operations.distribution(reference,reference);self.assertEqual(equal['total_variation'],0)
        shifted=operations.distribution(reference,[0]*48);self.assertTrue(shifted['investigate']);self.assertFalse(shifted['quality_measured'])
        quality={'scored':48,'accuracy':29/48}
        self.assertFalse(operations.investigate(reference,[0]*48,quality)['retrain'])
        self.assertEqual(operations.investigate(reference,[True],quality)['decision'],'repair data before retraining')

    def test_saved_source_change_prevents_reuse(self):
        file=Path(self.training['workspace'])/'tracker/runs'/self.training['run_id']/'workspace/workflow.py'
        raw=file.read_bytes()
        try:
            file.write_bytes(raw+b'\n# changed retained source\n')
            with self.assertRaisesRegex(ValueError,'implementation changed'):
                pipeline.run(w.HERE/'scenario.json',self.root/'pipeline')
        finally:file.write_bytes(raw)

    def test_label_reporting_delay_is_enforced(self):
        fixture=w.strict_json(w.HERE/'scenario.json')
        predictions=serving.batch(self.root/'bundle',self.rows)['predictions']
        selected=predictions[0]
        label=next(x for x in fixture['labels'] if x['id']==selected['id'])
        label['ready_at']=(w.availability.instant(selected['predict_at'])+timedelta(hours=24)).isoformat()
        with self.assertRaisesRegex(ValueError,'reporting delay'):
            operations.evaluate_delayed([selected],fixture,'2026-01-13T14:00:00Z')

    def test_unknown_outcome_is_not_label_zero(self):
        prediction=serving.Predictor(self.root/'bundle').predict(self.rows[0]);prediction['id']='unknown-observation'
        report=operations.evaluate_delayed([prediction],w.strict_json(w.HERE/'scenario.json'),'2026-01-13T14:00:00Z')
        self.assertEqual((report['unknown'],report['scored'],report['accuracy']),(1,0,None))

    def test_concurrent_invocation_cannot_enter_locked_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/pipeline.pipeline_identity(w.HERE/'scenario.json');folder.mkdir();(folder/'running.lock').write_text('existing owner')
            with self.assertRaisesRegex(ValueError,'already running'):pipeline.run(w.HERE/'scenario.json',tmp)
            self.assertEqual((folder/'running.lock').read_text(),'existing owner')

    def test_supplied_cohort_must_match_selected_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            cohort=w.prepare(w.HERE/'scenario.json');cohort['rows'][0]['feature_count']+=1
            path=Path(tmp)/'cohort.json';w.save(path,cohort)
            with self.assertRaisesRegex(ValueError,'supplied cohort differs'):
                __import__('tracking').execute(w.HERE/'scenario.json',Path(tmp)/'tracker',prepared_cohort=path)

    def test_incompatible_rollback_target_does_not_change_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle=Path(tmp)/'bundle';shutil.copytree(self.root/'bundle',bundle)
            routing=rollout.Routing(Path(tmp)/'routing.sqlite')
            try:
                routing.stage(bundle,bundle,0,0)
                metadata=w.strict_json(bundle/'bundle.json');metadata['serving_code_sha256']='0'*64
                (bundle/'bundle.json').write_text(json.dumps(metadata))
                with self.assertRaisesRegex(ValueError,'incompatible'):routing.rollback(1,1)
                self.assertEqual(routing.current()['generation'],1)
            finally:routing.close()

    def test_equivalent_utc_timestamps_join_the_same_observation(self):
        prediction=serving.Predictor(self.root/'bundle').predict(self.rows[0])
        prediction['predict_at']=prediction['predict_at'].replace('Z','+00:00')
        report=operations.evaluate_delayed([prediction],w.strict_json(w.HERE/'scenario.json'),'2026-01-13T14:00:00Z')
        self.assertEqual((report['unknown'],report['scored']),(0,1))


if __name__=='__main__':unittest.main()
