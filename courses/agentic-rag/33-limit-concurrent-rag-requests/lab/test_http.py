import unittest
from run import run
class HTTPTests(unittest.TestCase):
    def test_real_http_admission_timeout_and_release(self):
        r=run();c=r['cases'];self.assertEqual(c['queue_overflow']['http_status'],429);self.assertEqual(c['wait_deadline']['status'],'wait_timeout')
        self.assertEqual(c['first_completed']['status'],'completed');self.assertEqual(c['idle']['active'],0)
        self.assertEqual(c['client_timeout']['server_after_timeout']['active'],1);self.assertEqual(c['client_timeout']['server_after_completion']['active'],0)
        self.assertEqual([x['status'] for x in c['fifo_promotion']['responses']],['completed','completed'])
        self.assertEqual(c['server_constructor_failure']['response']['http_status'],500);self.assertEqual(c['server_constructor_failure']['state']['active'],0)
        for scenario in ['idle']:
            self.assertTrue(all(e['active']<=1 and e['waiting']<=1 for e in c[scenario]['events']))
        self.assertTrue(r['lifecycle']['shutdown_complete_observed'])
