import copy
import json
from pathlib import Path
import tempfile
import unittest
from index import connect, delete_source, replace_source, search, state


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=connect(Path(self.temp.name)/'index.sqlite');self.addCleanup(self.db.close)
        self.source=json.loads((Path(__file__).parent/'fixtures/snapshot.json').read_text())['documents'][0]
        replace_source(self.db,self.source)

    def updated(self):
        updated=copy.deepcopy(self.source);updated['document_revision']='new-revision'
        updated['chunks']=[{'chunk_id':'new-chunk','text':'Replacement sentinelword only.'}]
        return updated

    def test_update_removes_old_chunk_ids_and_old_matches(self):
        old_ids={c['chunk_id'] for c in self.source['chunks']}
        self.assertTrue(search(self.db,'encoding'))
        replace_source(self.db,self.updated())
        self.assertFalse(old_ids & {r[0] for r in state(self.db)['chunks']})
        self.assertEqual(search(self.db,'encoding'),[])
        self.assertEqual(search(self.db,'sentinelword')[0]['chunk_id'],'new-chunk')

    def test_update_interruption_rolls_back_source_chunks_and_index(self):
        before=state(self.db)
        with self.assertRaises(InterruptedError):replace_source(self.db,self.updated(),interrupt=True)
        self.assertEqual(state(self.db),before);self.assertTrue(search(self.db,'encoding'))

    def test_repeated_update_is_idempotent(self):
        replace_source(self.db,self.updated());before=state(self.db)
        replace_source(self.db,self.updated());self.assertEqual(before,state(self.db))

    def test_delete_removes_actual_match_results(self):
        self.assertTrue(search(self.db,'encoding'))
        self.assertEqual(delete_source(self.db,self.source['source_id']),'deleted')
        self.assertEqual(search(self.db,'encoding'),[])
        self.assertTrue(all(not rows for rows in state(self.db).values()))

    def test_missing_delete_is_idempotent_noop(self):
        delete_source(self.db,self.source['source_id']);before=state(self.db)
        self.assertEqual(delete_source(self.db,self.source['source_id']),'missing-no-op')
        self.assertEqual(before,state(self.db))

    def test_delete_interruption_rolls_back(self):
        before=state(self.db)
        with self.assertRaises(InterruptedError):delete_source(self.db,self.source['source_id'],interrupt=True)
        self.assertEqual(before,state(self.db));self.assertTrue(search(self.db,'encoding'))

if __name__=='__main__':unittest.main()
