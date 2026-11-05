import json,unittest
from pathlib import Path
from assistant import Assistant,Ask,Answer,Corpus,BadAnswer,validate_answer,digest
from record_demo import plan
from providers import Gemini
ROOT=Path(__file__).parent

class RecordingTests(unittest.TestCase):
    def test_current_docuctl_http_record_matches_current_corpus(self):
        record=json.loads((ROOT/'runs/local-docuctl/http-demo.json').read_text())
        service=Assistant()
        self.assertEqual(record['provider'],'extractive')
        self.assertEqual(record['snapshot'],service.corpus.snapshot)
        for row in record['activities']:
            if row['status']!=200:continue
            role='maintainer' if row['id']=='production' else 'reader'
            principal='demo-maintainer' if role=='maintainer' else 'demo-reader'
            result=service.ask(principal,role,Ask(**row['request']))
            self.assertEqual(result,row['response'])

    def test_saved_http_answers_reproduce_with_current_corpus(self):
        record=json.loads((ROOT/'runs/http-demo.json').read_text());s=Assistant()
        self.assertEqual(record['snapshot'],s.corpus.snapshot)
        for row in record['activities']:
            if row['status']!=200:continue
            role='maintainer' if row['id']=='production' else 'reader'
            principal='demo-maintainer' if role=='maintainer' else 'demo-reader'
            result=s.ask(principal,role,Ask(**row['request']))
            self.assertEqual(result,row['response'])
    def test_saved_gemini_requests_and_answers_match_current_context(self):
        rows=json.loads((ROOT/'runs/gemini/http-demo.json').read_text())['activities']
        records=[json.loads(p.read_text()) for p in sorted((ROOT/'runs/gemini/provider-responses').glob('response-*.json'))]
        self.assertEqual(len(rows),4);self.assertEqual(len(records),4)
        for row,record in zip(rows,records):
            self.assertEqual(row['status'],200)
            service=Assistant();role='maintainer' if row['id']=='production' else 'reader';query=Ask(**row['request'])
            passages,_=service.retrieve('replay',role,query)
            self.assertEqual(record['request'],Gemini.payload(query.question,passages))
            self.assertEqual(record['request_sha256'],digest(record['request']))
            self.assertEqual(record['response']['candidates'][0]['finishReason'],'STOP')
            text=''.join(p.get('text','') for p in record['response']['candidates'][0]['content']['parts'] if not p.get('thought'))
            saved=Answer.model_validate_json(text)
            from assistant import validate_answer
            validate_answer(saved,passages)
            self.assertEqual(saved.model_dump(),{k:row['response'][k] for k in ['status','answer','citations']})

    def test_changed_quote_is_rejected_even_with_a_real_source_id(self):
        record=json.loads((ROOT/'runs/gemini/http-demo.json').read_text())
        service=Assistant();row=record['activities'][0]
        passages,_=service.retrieve('check','reader',Ask(**row['request']))
        saved=Answer.model_validate({k:row['response'][k] for k in ['status','answer','citations']})
        saved.citations[0].quote='This sentence is absent from the supplied source.'
        with self.assertRaises(BadAnswer):validate_answer(saved,passages)

    def test_four_request_preflight_is_offline_and_fixed(self):
        profile=plan();self.assertEqual(profile['max_generation_HTTP_attempts'],4);self.assertEqual(len(profile['cases']),4)
        for case in profile['cases']:
            self.assertLessEqual(case['serialized_bytes'],10000);self.assertNotIn('tools',case['payload'])
            self.assertEqual(case['payload']['generationConfig']['maxOutputTokens'],1024)
if __name__=='__main__':unittest.main()
