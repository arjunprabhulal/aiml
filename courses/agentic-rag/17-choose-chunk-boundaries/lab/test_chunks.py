import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from chunk_index import CONFIGS,build_index,digest,sections,chunks_for,config_checked,validate_index
from load_documents import IngestionError
from run import run

ROOT=Path(__file__).parent

class ChunkTests(unittest.TestCase):
    def setUp(self):self.index=build_index(ROOT/'fixtures/source-manifest.json',CONFIGS['paragraph'])
    def test_controlled_instruction_qualifier_span_check(self):
        comparisons=run()['comparisons']
        self.assertEqual({r['strategy']:r['instruction_and_qualifier_share_chunk'] for r in comparisons},{'fixed-char':False,'paragraph':False,'heading-aware':True})
        self.assertEqual([r['chunk_count'] for r in comparisons],[13,8,7])
    def test_exact_spans_reconstruct_source_text(self):
        documents={d['source_id']:d for d in self.index['documents']}
        for chunk in self.index['chunks']:
            text=documents[chunk['source_id']]['text']
            self.assertEqual(chunk['text'],text[chunk['start']:chunk['end']])
            self.assertEqual(chunk['start_line'],text.count('\n',0,chunk['start'])+1)
            self.assertEqual(chunk['end_line'],text.count('\n',0,chunk['end']-1)+1)
    def test_every_strategy_stays_inside_heading_section(self):
        for config in CONFIGS.values():
            index=build_index(ROOT/'fixtures/source-manifest.json',config)
            boundaries={section['section_id']:section for doc in index['documents'] for section in sections(doc)}
            for chunk in index['chunks']:
                section=boundaries[chunk['section_id']]
                self.assertGreaterEqual(chunk['start'],section['start']);self.assertLessEqual(chunk['end'],section['end'])
    def test_repeat_build_and_roundtrip_identical(self):
        self.assertEqual(self.index,build_index(ROOT/'fixtures/source-manifest.json',CONFIGS['paragraph']))
        self.assertEqual(validate_index(json.loads(json.dumps(self.index))),self.index)
    def test_config_binds_chunk_identity(self):
        paragraph=self.index
        heading=build_index(ROOT/'fixtures/source-manifest.json',CONFIGS['heading-aware'])
        self.assertNotEqual(paragraph['index_id'],heading['index_id'])
        self.assertFalse({c['chunk_id'] for c in paragraph['chunks']} & {c['chunk_id'] for c in heading['chunks']})
    def test_whole_oversized_paragraph_is_preserved(self):
        document=dict(self.index['documents'][0],text='# Controlled unit fixture\n\n'+'x'*300+'\n')
        chunks=chunks_for(document,CONFIGS['heading-aware'])
        self.assertEqual(len(chunks),1)
        self.assertEqual(chunks[0]['text'],'x'*300+'\n')
        self.assertGreater(len(chunks[0]['text']),CONFIGS['heading-aware']['max_chars'])
    def test_non_json_config_refused_as_contract_error(self):
        for config in [None,[],{'strategy':set()},dict(CONFIGS['paragraph'],unexpected=object())]:
            with self.assertRaisesRegex(IngestionError,'unsupported_chunk_config'):config_checked(config)
    def test_unknown_config_rejected(self):
        with self.assertRaisesRegex(IngestionError,'unsupported_chunk_config'):build_index(ROOT/'fixtures/source-manifest.json',{'strategy':'paragraph','version':2,'max_chars':None})
    def test_unpinned_source_change_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'fixtures';shutil.copytree(ROOT/'fixtures',target)
            (target/'docs/aster-copy-v1.md').write_text('changed source')
            with self.assertRaisesRegex(IngestionError,'hash_mismatch'):build_index(target/'source-manifest.json')
    def test_same_id_text_change_refused(self):
        changed=copy.deepcopy(self.index);changed['documents'][0]['text']+=' changed'
        with self.assertRaisesRegex(IngestionError,'invalid_chunk_index'):validate_index(changed)
    def test_rehashed_malformed_chunk_order_span_or_payload_refused(self):
        for field,value in [('order',99),('start',-1),('end',99999),('text','invented'),('version','9.0')]:
            with self.subTest(field=field):
                changed=copy.deepcopy(self.index);changed['chunks'][0][field]=value
                changed['index_id']=digest({k:v for k,v in changed.items() if k!='index_id'})
                with self.assertRaisesRegex(IngestionError,'invalid_chunk_index'):validate_index(changed)
    def test_malformed_top_level_refused(self):
        for value in [[],None,{},dict(self.index,schema_version=True)]:
            with self.assertRaisesRegex(IngestionError,'invalid_chunk_index'):validate_index(value)

if __name__=='__main__':unittest.main()
