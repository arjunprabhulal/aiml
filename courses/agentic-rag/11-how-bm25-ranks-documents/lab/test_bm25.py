import copy
import json
from pathlib import Path
import unittest
from bm25 import LexicalIndex
from load_documents import IngestionError

class BM25Tests(unittest.TestCase):
    def setUp(self):
        self.snapshot=json.loads((Path(__file__).parent/'fixtures/snapshot.json').read_text())
        self.index=LexicalIndex(self.snapshot);self.addCleanup(self.index.close)
    def test_native_scores_match_single_term_explanation(self):
        for query in ['text','newline','overwritten']:
            results=self.index.search(query)['results'];self.assertTrue(results)
            for row in results:self.assertAlmostEqual(row['native_score'],row['explained_score'],places=14)
            self.assertEqual([r['native_score'] for r in results],sorted(r['native_score'] for r in results))
    def test_unicode61_exposes_indexed_api_terms(self):
        terms={row['term'] for row in self.index.indexed_terms()}
        self.assertIn('write',terms);self.assertIn('read',terms);self.assertIn('text',terms)
        self.assertNotIn('write_text',terms)
    def test_empty_query_returns_no_results(self):
        self.assertEqual(self.index.search('  ')['status'],'empty_query')
        self.assertEqual(self.index.search('  ')['results'],[])
    def test_no_match_is_explicit(self):
        self.assertEqual(self.index.search('xyznotindexed')['status'],'no_match')
    def test_invalid_query_never_becomes_sql_or_fts_syntax(self):
        for query in ['text*','"','x; DROP TABLE passages;',None,'a'*65]:
            with self.subTest(query=query):
                with self.assertRaisesRegex(ValueError,'invalid_query'):self.index.search(query)
        self.assertTrue(self.index.search('text')['results'])
    def test_multiword_query_uses_literal_or_and_native_scores(self):
        result=self.index.search('text newline')
        rows=self.index.connection.execute('SELECT chunk_id,bm25(passages) AS score FROM passages WHERE passages MATCH ? ORDER BY score,chunk_id LIMIT 10', ('"text" OR "newline"',)).fetchall()
        self.assertEqual([(r['chunk_id'],r['native_score']) for r in result['results']],[(r['chunk_id'],r['score']) for r in rows])
        self.assertTrue(result['results'])
        self.assertNotIn('term_frequency',result['results'][0])
    def test_api_underscore_separates_literal_terms(self):
        self.assertEqual(self.index.search('write_text')['results'],self.index.search('write text')['results'])
    def test_fts_operator_word_is_a_literal(self):
        self.assertEqual(self.index.search('text OR newline')['results'],self.index.search('text or newline')['results'])
        self.assertEqual(self.index.search('OR'),self.index.search('or'))
    def test_limit_is_bounded(self):
        for limit in [0,-1,101,True,'1']:
            with self.assertRaisesRegex(ValueError,'invalid_query'):self.index.search('text',limit)
        self.assertEqual(len(self.index.search('text',1)['results']),1)
    def test_equal_scores_break_ties_by_chunk_id(self):
        # Controlled unit fixture: duplicate a real row under two new IDs.
        self.index.connection.execute('DELETE FROM passages')
        for key in ['z-last','a-first']:
            self.index.connection.execute('INSERT INTO passages VALUES(?,?,?,?,?)',('text repeated',key,'controlled-tie','3.12','https://example.invalid'))
        rows=self.index.search('text')['results']
        self.assertEqual(rows[0]['native_score'],rows[1]['native_score'])
        self.assertEqual([row['chunk_id'] for row in rows],['a-first','z-last'])
    def test_source_metadata_stays_attached(self):
        rows=self.index.search('newline')['results']
        self.assertEqual({row['version'] for row in rows},{'3.12','3.13'})
        expected={chunk['chunk_id'] for doc in self.snapshot['documents'] for chunk in doc['chunks']}
        self.assertTrue(all(row['chunk_id'] in expected for row in rows))
    def test_tampered_snapshot_rejected_before_index(self):
        changed=copy.deepcopy(self.snapshot);changed['documents'][0]['text']+=' changed'
        with self.assertRaisesRegex(IngestionError,'invalid_snapshot'):LexicalIndex(changed)

if __name__=='__main__':unittest.main()
