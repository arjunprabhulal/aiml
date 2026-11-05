import copy
import unittest
from tools import DocumentationTools,load_snapshot
from refine import ScriptedPolicy
from limits import Limits,run_limited

QUESTION='Will write_text replace the contents of an existing file?'


class SpyTools(DocumentationTools):
    def __init__(self,snapshot):super().__init__(snapshot);self.calls=[]
    def search(self,**arguments):self.calls.append('search');return super().search(**arguments)
    def read(self,handle):self.calls.append('read');return super().read(handle)


class LimitTests(unittest.TestCase):
    def setUp(self):self.tools=SpyTools(load_snapshot());self.addCleanup(self.tools.close)

    def test_all_limits_stop_before_denied_tool_invocation(self):
        cases=[(Limits(max_steps=0),'max_steps',[]),(Limits(max_searches=0),'max_searches',[]),(Limits(max_reads=0),'max_reads',['search']),(Limits(max_source_bytes=0),'max_source_bytes',['search'])]
        for limits,reason,calls in cases:
            tools=SpyTools(load_snapshot())
            try:
                result=run_limited(tools,ScriptedPolicy(QUESTION,'3.12'),limits)
                self.assertEqual(result['controller_status'],'limited');self.assertEqual(result['terminal_reason'],reason)
                self.assertEqual(tools.calls,calls);self.assertFalse(result['trace'][-1]['invoked'])
            finally:tools.close()

    def test_cumulative_step_search_read_and_byte_limits(self):
        cases=[(Limits(max_steps=2),'max_steps',2),(Limits(max_searches=1),'max_searches',2),(Limits(max_reads=1),'max_reads',3),(Limits(max_source_bytes=200),'max_source_bytes',3)]
        for limits,reason,count in cases:
            tools=SpyTools(load_snapshot())
            try:
                result=run_limited(tools,ScriptedPolicy(QUESTION,'3.12'),limits)
                self.assertEqual(result['terminal_reason'],reason)
                self.assertEqual(len(tools.calls),count)
                self.assertLessEqual(result['usage']['reserved_source_bytes'],limits.max_source_bytes)
            finally:tools.close()

    def test_success_records_real_validated_reads_and_actual_counters(self):
        result=run_limited(self.tools,ScriptedPolicy(QUESTION,'3.12'))
        self.assertEqual(result['controller_status'],'completed')
        self.assertEqual(result['usage']['steps'],4);self.assertEqual(self.tools.calls,['search','read','search','read'])
        delivered=sum(len(o['result']['text'].encode('utf-8')) for o in result['observations'] if o['tool']=='read')
        self.assertEqual(result['usage']['delivered_source_bytes'],delivered)
        self.assertEqual(result['usage']['reserved_source_bytes'],delivered)

    def test_invalid_limits_and_action_schema_fail_closed(self):
        for value in [True,-1,101]:
            with self.subTest(value=value),self.assertRaises(ValueError):Limits(max_steps=value)
        for action in [{'tool':'delete','arguments':{}},{'tool':'search','arguments':{'query':'text','version':'3.12','k':11}},{'tool':'search','arguments':{'query':'text OR read','version':'3.12'}},{'tool':'read','arguments':{'handle':{}}},{'tool':'search','arguments':{'query':'text','version':'3.12'},'extra':1}]:
            result=run_limited(self.tools,lambda observations:action)
            self.assertEqual(result['controller_status'],'failed');self.assertFalse(result['trace'][0]['invoked'])
        self.assertEqual(self.tools.calls,[])

    def test_repeated_call_is_rejected_without_second_invocation(self):
        action={'tool':'search','arguments':{'query':'text','version':'3.12','k':2}}
        result=run_limited(self.tools,lambda observations:copy.deepcopy(action))
        self.assertEqual(result['controller_status'],'failed');self.assertIn('repeated_action',result['terminal_reason'])
        self.assertEqual(self.tools.calls,['search'])

    def test_tool_error_is_terminal_and_attempt_consumes_budget(self):
        original=self.tools.search
        def failure(**arguments):original(**arguments);raise RuntimeError('controlled_after_search_fault')
        self.tools.search=failure
        result=run_limited(self.tools,ScriptedPolicy(QUESTION,'3.12'))
        self.assertEqual(result['controller_status'],'failed');self.assertEqual(result['usage']['steps'],1)
        self.assertEqual(result['usage']['searches'],1);self.assertEqual(result['observations'],[])
        self.assertTrue(result['trace'][0]['invoked'])
        self.assertEqual(len(result['trace']),1)
        self.assertIn('controlled_after_search_fault',result['terminal_reason'])

    def test_tampered_same_size_read_is_not_accepted_as_observation(self):
        original=self.tools.read
        def altered(handle):
            result=original(handle);result['text']='X'+result['text'][1:];return result
        self.tools.read=altered
        result=run_limited(self.tools,ScriptedPolicy(QUESTION,'3.12'))
        self.assertEqual(result['controller_status'],'failed');self.assertIn('invalid_read_result',result['terminal_reason'])
        self.assertEqual([o['tool'] for o in result['observations']],['search'])
        self.assertEqual(result['usage']['delivered_source_bytes'],0)

    def test_case_and_default_k_variants_are_still_repeated_search(self):
        def policy(observations):
            if not observations:return {'tool':'search','arguments':{'query':'TEXT','version':'3.12'}}
            return {'tool':'search','arguments':{'query':'text','version':'3.12','k':2}}
        result=run_limited(self.tools,policy)
        self.assertEqual(result['controller_status'],'failed')
        self.assertIn('repeated_action',result['terminal_reason'])
        self.assertEqual(self.tools.calls,['search'])

if __name__=='__main__':unittest.main()
