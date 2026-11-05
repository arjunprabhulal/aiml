import copy
import json
from pathlib import Path
import tempfile
import unittest
from ingest import IngestionError, connect, ingest, state


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'job.sqlite'
        self.db = connect(self.path); self.addCleanup(self.db.close)
        self.snapshot = json.loads((Path(__file__).parent/'fixtures/snapshot.json').read_text())

    def test_interruption_rolls_back_source_chunks_and_checkpoint(self):
        sid=self.snapshot['documents'][1]['source_id']
        with self.assertRaises(InterruptedError): ingest(self.db,self.snapshot,'demo',sid)
        for table in ['sources','chunks','checkpoints']:
            self.assertEqual(self.db.execute(f'SELECT count(*) FROM {table} WHERE source_id=?',(sid,)).fetchone()[0],0)
        self.assertEqual(len(state(self.db)['sources']),1)

    def test_persistent_restart_skips_committed_source(self):
        with self.assertRaises(InterruptedError): ingest(self.db,self.snapshot,'demo',self.snapshot['documents'][1]['source_id'])
        self.db.close();self.db=connect(self.path)
        actions=ingest(self.db,self.snapshot,'demo')
        self.assertEqual(actions[0]['action'],'skipped')
        self.assertTrue(all(a['action']=='committed' for a in actions[1:]))

    def test_duplicate_retry_is_idempotent(self):
        ingest(self.db,self.snapshot,'demo');before=state(self.db)
        self.assertTrue(all(a['action']=='skipped' for a in ingest(self.db,self.snapshot,'demo')))
        self.assertEqual(before,state(self.db))

    def test_changed_snapshot_is_rejected(self):
        ingest(self.db,self.snapshot,'demo');changed=copy.deepcopy(self.snapshot);changed['snapshot_id']='changed'
        with self.assertRaisesRegex(IngestionError,'snapshot changed'):ingest(self.db,changed,'demo')

    def test_other_job_requires_new_database(self):
        ingest(self.db,self.snapshot,'demo')
        with self.assertRaisesRegex(IngestionError,'another job'):ingest(self.db,self.snapshot,'other')

    def test_stale_checkpoint_is_rejected(self):
        ingest(self.db,self.snapshot,'demo')
        with self.db:self.db.execute("UPDATE checkpoints SET document_revision='stale'")
        with self.assertRaisesRegex(IngestionError,'checkpoint'):ingest(self.db,self.snapshot,'demo')

    def test_changed_stored_chunk_is_rejected_before_skip(self):
        ingest(self.db,self.snapshot,'demo')
        with self.db:self.db.execute("UPDATE chunks SET text='corrupt'")
        with self.assertRaisesRegex(IngestionError,'checkpoint'):ingest(self.db,self.snapshot,'demo')

    def test_missing_stored_chunk_is_rejected_before_skip(self):
        ingest(self.db,self.snapshot,'demo')
        with self.db:self.db.execute("DELETE FROM chunks")
        with self.assertRaisesRegex(IngestionError,'checkpoint'):ingest(self.db,self.snapshot,'demo')

    def test_same_id_changed_input_is_rejected_after_interruption(self):
        with self.assertRaises(InterruptedError):ingest(self.db,self.snapshot,'demo',self.snapshot['documents'][1]['source_id'])
        for kind in ['text','metadata','chunker']:
            changed=copy.deepcopy(self.snapshot)
            if kind=='text':changed['documents'][1]['chunks'][0]['text']='tampered'
            elif kind=='metadata':changed['documents'][1]['title']='changed title'
            else:changed['chunker']['version']=2
            before=state(self.db)
            with self.subTest(kind=kind),self.assertRaisesRegex(IngestionError,'snapshot changed'):
                ingest(self.db,changed,'demo')
            self.assertEqual(before,state(self.db))

if __name__=='__main__':unittest.main()
