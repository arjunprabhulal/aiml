import warnings
warnings.filterwarnings("ignore")
"""Run request.sh against fake executables, never against Google Cloud."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
FAKE_CURL = r"""#!/usr/bin/env python3
import json,os,sys,time
args=sys.argv[1:];body=args[args.index('-o')+1]
url=next(a for a in args if a.startswith('https://'))
create=url.endswith('/sessions')
status=int(os.environ.get('CREATE_STATUS' if create else 'RUN_STATUS','200'))
with open(os.environ['CALLS'],'a') as log:log.write(json.dumps({'body':body,'create':create})+'\n')
value={'id':os.environ.get('SID','s1')} if create else [{'author':'docs_helper','content':{'parts':[{'text':'recorded answer'}]}}]
if status>=400:value={'detail':'injected HTTP failure'}
Path=None
with open(body,'w') as output:json.dump(value,output)
print('HTTP '+str(status)+' in 0 s')
time.sleep(.02)
sys.exit(22 if status>=400 and '--fail-with-body' in args else 0)
"""

class HttpClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        for name, text in [('curl', FAKE_CURL), ('gcloud', '#!/bin/sh\nprintf test-token')]:
            p=self.base/name;p.write_text(text);p.chmod(0o755)
        self.env={**os.environ,'PATH':str(self.base)+os.pathsep+os.environ['PATH'],
                  'SERVICE_URL':'https://unit.invalid','CALLS':str(self.base/'calls.jsonl')}

    def run_client(self, **extra):
        return subprocess.run(['bash',str(HERE/'request.sh'),'question'],env={**self.env,**extra},capture_output=True,text=True)

    def calls(self):
        return [json.loads(x) for x in (self.base/'calls.jsonl').read_text().splitlines()]

    def test_failed_session_creation_stops_before_the_model_request(self):
        result=self.run_client(CREATE_STATUS='500')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(len(self.calls()),1)
        self.assertIn('injected HTTP failure',result.stdout)

    def test_a_failed_run_exits_nonzero(self):
        self.assertNotEqual(self.run_client(RUN_STATUS='500').returncode,0)

    def test_simultaneous_clients_have_separate_response_files(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda sid:self.run_client(SID=sid),['first','second']))
        self.assertTrue(all(r.returncode==0 for r in results),results)
        paths={c['body'] for c in self.calls()}
        self.assertEqual(len(paths),2)
        self.assertTrue(all(not Path(p).exists() for p in paths))

if __name__ == '__main__':
    unittest.main()
