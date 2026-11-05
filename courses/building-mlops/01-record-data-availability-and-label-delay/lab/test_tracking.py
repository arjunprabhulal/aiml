"""Integration tests use the installed local MLflow SQLite store, not a mock."""
import tempfile
from pathlib import Path
import unittest
import tracking
import workflow as w


class TrackingTests(unittest.TestCase):
    def test_completed_run_stores_reloadable_model_and_separate_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=tracking.execute(w.HERE/'scenario.json',tmp)
            _,client,experiment=tracking.client(tmp)
            run=client.get_run(result['run_id'])
            self.assertEqual(run.info.status,'FINISHED')
            downloaded=client.download_artifacts(result['run_id'],'model/candidate.json')
            self.assertEqual(w.sha(downloaded),result['model_sha256'])
            self.assertAlmostEqual(w.predict(w.load_model(downloaded),3)['return_probability'],0.40381146876849405)
            report=client.download_artifacts(result['run_id'],'evaluation/validation.json')
            self.assertEqual(w.strict_json(report)['correct'],29)
            with self.assertRaises(ValueError):w.load_model(report)
            self.assertFalse(result['final_test_used'])

    def test_failure_is_failed_run_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'deliberate'):
                tracking.execute(w.HERE/'scenario.json',tmp,True)
            _,client,experiment=tracking.client(tmp)
            runs=client.search_runs([experiment])
            self.assertEqual(len(runs),1)
            self.assertEqual(runs[0].info.status,'FAILED')
            self.assertEqual(client.list_artifacts(runs[0].info.run_id,'model'),[])
            failure=client.download_artifacts(runs[0].info.run_id,'failure/failure.json')
            self.assertIsNone(w.strict_json(failure)['model_artifact'])

    def test_copied_source_is_checked_before_execution(self):
        from unittest.mock import patch
        original=tracking.f.snapshot
        def corrupt(source,destination):
            manifest=original(source,destination)
            (Path(destination)/'workflow.py').write_text('raise RuntimeError("should never run")')
            return manifest
        with tempfile.TemporaryDirectory() as tmp,patch.object(tracking.f,'snapshot',corrupt):
            with self.assertRaisesRegex(ValueError,'copied source differs'):
                tracking.execute(w.HERE/'scenario.json',tmp)
            _,client,experiment=tracking.client(tmp)
            self.assertEqual(client.search_runs([experiment])[0].info.status,'FAILED')


if __name__=='__main__':unittest.main()
