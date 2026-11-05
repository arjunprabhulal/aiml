import json,unittest
from run import run
class HTTPTests(unittest.TestCase):
    def test_real_http_ids_redaction_and_failure(self):
        r=run();a,b=r['cases'][:2]
        self.assertEqual(a['content_request_id'],b['content_request_id']);self.assertNotEqual(a['execution_trace_id'],b['execution_trace_id'])
        self.assertEqual([a['http_status'],b['http_status']],[200,200]);self.assertEqual(r['invalid_request_http_status'],422)
        for tid,rows in r['record']['traces'].items():
            self.assertTrue(all(x['trace_id']==tid for x in rows));self.assertTrue(all(x['status']!='running' for x in rows))
        self.assertTrue(any(x['status']=='denied' for rows in r['record']['traces'].values() for x in rows))
        f=r['controlled_tool_failure'];self.assertEqual(f['http_status'],503)
        rows=f['record']['traces'][f['execution_trace_id']];self.assertEqual(rows[0]['status'],'error');self.assertIn('error',[x['name'] for x in rows]);self.assertNotIn('SENSITIVE_ERROR_SENTINEL',json.dumps(f['record']))
        self.assertTrue(r['lifecycle']['shutdown_complete_observed'])
