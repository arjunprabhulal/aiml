import copy
import json
import hashlib
import shutil
import tempfile
from pathlib import Path
import unittest
from chunk_index import CONFIGS,build_index
from load_documents import IngestionError
from surround import expand_context,validate_windows

ROOT=Path(__file__).parent

class SurroundTests(unittest.TestCase):
    def setUp(self):
        self.index=build_index(ROOT/'fixtures/source-manifest.json',CONFIGS['paragraph'])
        self.primary=[c for c in self.index['chunks'] if c['source_id']=='aster-copy-v1' and c['section_title']=='Create a copy']
    def test_overlap_merges_and_retains_all_seed_ranks(self):
        seeds=[self.primary[2]['chunk_id'],self.primary[0]['chunk_id']]
        result=expand_context(self.index,seeds,1)
        self.assertEqual(len(result['groups']),1)
        group=result['groups'][0]
        self.assertEqual(group['seed_ranks'],[{'chunk_id':seeds[0],'rank':1},{'chunk_id':seeds[1],'rank':2}])
        self.assertEqual([m['role'] for m in group['members']],['seed','neighbor','seed'])
        self.assertIsNone(group['members'][1]['retrieval_rank'])
        self.assertEqual(len(set(group['chunk_ids'])),3)
    def test_radius_zero_does_not_promote_neighbors(self):
        result=expand_context(self.index,[self.primary[0]['chunk_id']],0)
        self.assertEqual(result['groups'][0]['chunk_ids'],[self.primary[0]['chunk_id']])
    def test_no_cross_document_version_or_section(self):
        result=expand_context(self.index,[self.primary[-1]['chunk_id']],3)
        self.assertEqual(result['groups'][0]['chunk_ids'],[c['chunk_id'] for c in self.primary])
        self.assertEqual(result['groups'][0]['source_id'],'aster-copy-v1')
        self.assertEqual(result['groups'][0]['version'],'1.0')
        self.assertEqual(result['groups'][0]['section_title'],'Create a copy')
    def test_context_is_exact_source_slice(self):
        result=expand_context(self.index,[self.primary[0]['chunk_id']],1)
        group=result['groups'][0];source=next(d for d in self.index['documents'] if d['source_id']==group['source_id'])
        self.assertEqual(group['text'],source['text'][group['start']:group['end']])
        self.assertIn('This operation refuses an existing path.',group['text'])
        self.assertEqual(validate_windows(self.index,result),result)
    def test_unknown_and_stale_seeds_refused(self):
        stale=build_index(ROOT/'fixtures/source-manifest.json',CONFIGS['heading-aware'])['chunks'][0]['chunk_id']
        for seed in ['unknown',stale]:
            with self.assertRaisesRegex(ValueError,'unknown_or_stale_seed'):expand_context(self.index,[seed])
    def test_changed_document_revision_refuses_old_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'fixtures';shutil.copytree(ROOT/'fixtures',target)
            source=target/'docs/aster-copy-v1.md';source.write_bytes(source.read_bytes()+b'\nSynthetic local revision.\n')
            manifest=target/'source-manifest.json';data=json.loads(manifest.read_text())
            data['sources'][0]['sha256']=hashlib.sha256(source.read_bytes()).hexdigest();manifest.write_text(json.dumps(data))
            updated=build_index(manifest,CONFIGS['paragraph'])
            with self.assertRaisesRegex(ValueError,'unknown_or_stale_seed'):expand_context(updated,[self.primary[0]['chunk_id']])
    def test_invalid_radius_refused(self):
        for radius in [True,-1,4,1.5,'1',None]:
            with self.assertRaisesRegex(ValueError,'invalid_radius'):expand_context(self.index,[self.primary[0]['chunk_id']],radius)
    def test_duplicate_and_malformed_seeds_refused(self):
        with self.assertRaisesRegex(ValueError,'duplicate_seed'):expand_context(self.index,[self.primary[0]['chunk_id']]*2)
        for seeds in ['seed',[None],[''],['id']*101]:
            with self.assertRaisesRegex(ValueError,'invalid_seeds'):expand_context(self.index,seeds)
    def test_empty_seeds_return_no_context(self):
        self.assertEqual(expand_context(self.index,[])['groups'],[])
    def test_malformed_index_order_span_payload_refused_before_expansion(self):
        for field,value in [('order',99),('start',-1),('text','changed'),('section_id','changed')]:
            changed=copy.deepcopy(self.index);changed['chunks'][0][field]=value
            with self.assertRaisesRegex(IngestionError,'invalid_chunk_index'):expand_context(changed,[self.primary[0]['chunk_id']])
    def test_tampered_windows_seed_provenance_refused(self):
        result=expand_context(self.index,[self.primary[0]['chunk_id']])
        for field,value in [('start',-1),('text','changed'),('seed_ranks',[]),('members',[])]:
            changed=copy.deepcopy(result);changed['groups'][0][field]=value
            with self.assertRaisesRegex(IngestionError,'invalid_context_windows'):validate_windows(self.index,changed)
    def test_different_sections_are_distinct_deterministic_groups(self):
        listing=next(c for c in self.index['chunks'] if c['source_id']=='aster-copy-v1' and c['section_title']=='List documents')
        seeds=[listing['chunk_id'],self.primary[0]['chunk_id']]
        first=expand_context(self.index,seeds,3)
        self.assertEqual([g['section_title'] for g in first['groups']],['List documents','Create a copy'])
        self.assertEqual(first,expand_context(self.index,seeds,3))

if __name__=='__main__':unittest.main()
