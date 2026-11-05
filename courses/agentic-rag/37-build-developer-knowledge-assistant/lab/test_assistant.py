import copy,json,threading,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from assistant import Answer,Ask,Assistant,BadAnswer,Busy,Citation,Corpus,Denied,Extractive,GRANTS,rank,validate_answer
from evaluate import evaluate
from providers import Gemini

class AssistantTests(unittest.TestCase):
    def setUp(self): self.service=Assistant()
    def test_development_cases(self):
        result=evaluate(self.service);self.assertEqual(result['passed'],result['total'])
    def test_private_collection_is_denied_before_search_or_cache(self):
        self.service.ask('maintainer','maintainer',Ask(question='production deployment',collection='operations'))
        with self.assertRaises(Denied):self.service.ask('maintainer','reader',Ask(question='production deployment',collection='operations'))
    def test_source_rechecks_access(self):
        with self.assertRaises(Denied):self.service.corpus.document('reader','production-35')
        self.assertIn('--approval',self.service.corpus.document('maintainer','production-35')['text'])
    def test_cache_key_includes_principal_and_version(self):
        q=Ask(question='deploy staging');self.service.ask('alice','reader',q)
        self.assertTrue(self.service.ask('alice','reader',q)['trace']['cache_hit'])
        self.assertFalse(self.service.ask('bob','reader',q)['trace']['cache_hit'])
        old=self.service.ask('alice','reader',q.model_copy(update={'version':'3.4'}))
        self.assertFalse(old['trace']['cache_hit']);self.assertTrue(all(s['version']=='3.4' for s in old['sources']))
    def test_cache_ttl_and_size(self):
        clock=[0];s=Assistant(clock=lambda:clock[0],ttl=2);q=Ask(question='token')
        s.ask('alice','reader',q);clock[0]=3
        self.assertFalse(s.ask('alice','reader',q)['trace']['cache_hit'])
        for i in range(40):s.ask(str(i),'reader',q)
        self.assertEqual(len(s.cache),32)
    def test_unknown_question_does_not_call_provider(self):
        class Refuse:
            name='never'
            def generate(*args):raise AssertionError('Provider called')
        result=Assistant(provider=Refuse()).ask('alice','reader',Ask(question='Wimbledon'))
        self.assertEqual(result['status'],'abstain')
    def test_context_bound_applies_to_cached_results(self):
        s=Assistant(context_bytes=1);q=Ask(question='deploy staging')
        for _ in range(2):
            r=s.ask('alice','reader',q);self.assertEqual(r['status'],'abstain');self.assertEqual(r['trace']['context_bytes'],0)
    def test_fabricated_source_and_modified_quote_are_refused(self):
        passages=self.service.corpus.eligible('reader','3.5','handbook')[:1]
        for id,quote in [('unknown','text'),(passages[0].id,'not in the original source')]:
            with self.assertRaises(BadAnswer):validate_answer(Answer(status='answered',answer='Made up',citations=[Citation(source_id=id,quote=quote)]),passages)
    def test_answer_without_citations_is_refused(self):
        with self.assertRaises(BadAnswer):validate_answer(Answer(status='answered',answer='Unsupported',citations=[]),[])
    def test_slot_is_returned_after_provider_failure(self):
        class Broken:
            name='broken'
            def generate(*a):raise RuntimeError('Unavailable')
        s=Assistant(provider=Broken(),capacity=1)
        for _ in range(2):
            with self.assertRaises(RuntimeError):s.ask('alice','reader',Ask(question='deploy'))
    def test_busy_request_is_refused_before_provider(self):
        self.service.slots.acquire();self.service.slots.acquire()
        try:
            with self.assertRaises(Busy):self.service.ask('alice','reader',Ask(question='deploy'))
        finally:self.service.slots.release();self.service.slots.release()
    def test_document_symlink_escape_is_refused(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'manifest.json').write_text(json.dumps([{'id':'bad','title':'bad','file':'escape.md','version':'3.5','collection':'handbook'}]));(root/'escape.md').symlink_to(Path(__file__))
            with self.assertRaises(ValueError):Corpus(root)
    def test_snapshot_changes_when_document_changes(self):
        import shutil
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/'docs';shutil.copytree(Path(__file__).parent/'docs',root)
            before=Corpus(root).snapshot;(root/'config-35.md').write_text((root/'config-35.md').read_text()+'\nA new documented option.\n')
            self.assertNotEqual(before,Corpus(root).snapshot)
    def test_gemini_payload_is_bounded_and_has_no_tools(self):
        body=Gemini.payload('deploy',self.service.corpus.passages[:2]);cfg=body['generationConfig']
        self.assertEqual(cfg['maxOutputTokens'],1024);self.assertEqual(cfg['thinkingConfig']['thinkingLevel'],'LOW');self.assertNotIn('tools',body)
    def test_request_allowance_stops_before_key_or_network(self):
        g=Gemini(max_requests=0)
        with self.assertRaisesRegex(RuntimeError,'allowance'):g.generate('deploy',self.service.corpus.passages[:1])
if __name__=='__main__':unittest.main()
