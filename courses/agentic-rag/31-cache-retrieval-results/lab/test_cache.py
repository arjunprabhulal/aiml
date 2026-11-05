import copy
import concurrent.futures
import unittest
from fastapi.testclient import TestClient
from app import create_app,cache_key
from authorization import Authorization
from cache import ResultCache
REQUEST={'query':'json','collection':'serialization'}
HEADERS={'Authorization':'Bearer demo-reader'}
class CacheTests(unittest.TestCase):
    def test_deepcopy_on_put_and_get(self):
        cache=ResultCache();value={'status':'completed','evidence':[{'text':'original'}]};cache.put('key',value);value['evidence'][0]['text']='changed'
        got=cache.get('key');self.assertEqual(got['evidence'][0]['text'],'original');got['evidence'].clear();self.assertEqual(len(cache.get('key')['evidence']),1)
    def test_fakeclock_expiry_and_lru(self):
        now=[0.0];cache=ResultCache(ttl=1,max_entries=2,clock=lambda:now[0]);v={'status':'completed'}
        cache.put('a',v);cache.put('b',v);cache.get('a');cache.put('c',v)
        self.assertIsNone(cache.get('b'));self.assertIsNotNone(cache.get('a'));now[0]=1;self.assertIsNone(cache.get('a'));self.assertEqual(cache.bytes,0)
    def test_byte_bound_and_invalid_limits(self):
        cache=ResultCache(max_bytes=100);self.assertFalse(cache.put('a',{'status':'completed','text':'x'*200}));self.assertEqual(cache.bytes,0)
        for kwargs in ({'ttl':float('nan')},{'max_entries':True},{'max_bytes':0}):
            with self.assertRaises(ValueError):ResultCache(**kwargs)
    def test_only_completed_cached(self):
        cache=ResultCache()
        for status in ['failed','incomplete','limited']:
            self.assertFalse(cache.put(status,{'status':status}));self.assertIsNone(cache.get(status))
    def test_parallel_bookkeeping(self):
        cache=ResultCache(max_entries=4)
        def work(i):cache.put(str(i),{'status':'completed','i':i});cache.get(str(i))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(work,range(100)))
        self.assertLessEqual(len(cache.entries),4);self.assertLessEqual(cache.bytes,cache.max_bytes);self.assertEqual(cache.bytes,sum(v[2] for v in cache.entries.values()))
    def test_key_context_binding(self):
        e=Authorization();req={**REQUEST,'version':'3.12','k':2};key=cache_key(e,'reader',req)
        self.assertNotEqual(key,cache_key(e,'editor',req));self.assertNotEqual(key,cache_key(e,'reader',{**req,'version':'3.13'}))
        e.corpus_id='changed';self.assertNotEqual(key,cache_key(e,'reader',req));e.corpus_id='again';key=cache_key(e,'reader',req)
        e.policy['description']+=' changed';self.assertNotEqual(key,cache_key(e,'reader',req))
    def test_http_hit_normalized_defaults_and_isolation(self):
        with TestClient(create_app()) as client:
            a=client.post('/retrieve',json=REQUEST,headers=HEADERS);self.assertEqual(a.json()['cache'],'miss')
            b=client.post('/retrieve',json={**REQUEST,'query':'JSON','version':'3.12','k':2},headers=HEADERS);self.assertEqual(b.json()['cache'],'hit')
            self.assertEqual(a.json()['result'],b.json()['result']);self.assertNotIn('issued_id',str(b.json()['result']))
            c=client.post('/retrieve',json=REQUEST,headers={'Authorization':'Bearer demo-editor'});self.assertEqual(c.json()['cache'],'miss')
            self.assertEqual(client.post('/retrieve',json=REQUEST,headers={'Authorization':'Bearer unknown'}).status_code,401)
    def test_authorization_before_cache_lookup(self):
        with TestClient(create_app()) as client:
            client.post('/retrieve',json=REQUEST,headers=HEADERS);client.app.state.engine.policy['grants']['reader']=[]
            r=client.post('/retrieve',json=REQUEST,headers=HEADERS);self.assertEqual(r.status_code,403)
    def test_incomplete_and_failure_not_cached(self):
        with TestClient(create_app()) as client:
            for _ in range(2):self.assertEqual(client.post('/retrieve',json={**REQUEST,'query':'zzzz'},headers=HEADERS).json()['cache'],'bypass')
        calls=[]
        def fail(snapshot):calls.append(1);raise RuntimeError('private')
        with TestClient(create_app(lambda:Authorization(tool_factory=fail))) as client:
            for _ in range(2):self.assertEqual(client.post('/retrieve',json=REQUEST,headers=HEADERS).status_code,503)
        self.assertEqual(len(calls),2)
if __name__=='__main__':unittest.main()

class RealHTTPTests(unittest.TestCase):
    def test_real_http_hit_and_validation(self):
        import tempfile
        from pathlib import Path
        from local_http import server
        with tempfile.TemporaryDirectory() as logs,server(Path(__file__).parent,logs) as client:
            self.assertEqual(client.post('/retrieve',json=REQUEST,headers=HEADERS).json()['cache'],'miss')
            self.assertEqual(client.post('/retrieve',json=REQUEST,headers=HEADERS).json()['cache'],'hit')
            self.assertEqual(client.post('/retrieve',json={**REQUEST,'k':True},headers=HEADERS).status_code,422)
            self.assertEqual(client.post('/retrieve',content=b'x'*8193,headers={'Content-Type':'application/json'}).status_code,413)
