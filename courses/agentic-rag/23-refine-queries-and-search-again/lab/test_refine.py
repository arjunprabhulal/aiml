import copy
import json
from pathlib import Path
import unittest
from refine import ScriptedPolicy,run_controller,rule_for
from tools import DocumentationTools,load_snapshot

QUESTION='Will write_text replace the contents of an existing file?'

class RefinementTests(unittest.TestCase):
    def setUp(self):
        self.tools=DocumentationTools(load_snapshot());self.addCleanup(self.tools.close)
    def config(self,**changes):return dict(rule_for(QUESTION),**changes)
    def test_actual_distinct_search_read_trace_preserves_original_question(self):
        result=run_controller(self.tools,QUESTION)
        self.assertEqual(result['question'],QUESTION);self.assertEqual(result['query_history'],['text','overwritten'])
        self.assertEqual([o['tool'] for o in result['observations']],['search','read','search','read'])
        self.assertEqual([o['result']['source_id'] for o in result['observations'] if o['tool']=='read'],['path-read','path-write'])
        self.assertEqual(result['status'],'completed');self.assertEqual(result['reason'],'configured_context_marker_found')
        self.assertNotIn('answer',result)
    def test_duplicate_query_stops_before_second_search(self):
        result=run_controller(self.tools,QUESTION,config=self.config(refinement_query='text',required_marker='absent'))
        self.assertEqual(result['reason'],'duplicate_query');self.assertEqual(result['query_history'],['text'])
    def test_no_new_passages_stops_without_duplicate_read(self):
        result=run_controller(self.tools,QUESTION,config=self.config(initial_query='overwritten',refinement_query='number',required_marker='absent'))
        self.assertEqual(result['reason'],'no_new_passages')
        self.assertEqual([o['tool'] for o in result['observations']],['search','read','search'])
    def test_no_hit_queries_are_bounded(self):
        result=run_controller(self.tools,QUESTION,config=self.config(initial_query='xyznotindexed',refinement_query='stillnotindexed'))
        self.assertEqual(result['status'],'incomplete');self.assertEqual(result['reason'],'round_limit')
        self.assertEqual(len(result['observations']),2)
    def test_policy_limits_and_empty_queries_refused(self):
        for change in [dict(max_rounds=True),dict(max_rounds=0),dict(initial_query=''),dict(refinement_query='text OR write'),dict(required_marker='')]:
            with self.assertRaisesRegex(ValueError,'invalid_policy'):ScriptedPolicy(QUESTION,'3.12',self.config(**change))
        with self.assertRaisesRegex(ValueError,'invalid_question'):ScriptedPolicy('', '3.12', self.config())
    def test_development_labels_are_not_policy_inputs(self):
        cases=json.loads((Path(__file__).parent/'fixtures/development-cases.json').read_text())
        for case in cases:
            changed=copy.deepcopy(case);changed['expected']={'status':'invented','targets':['wrong']};changed['class']='changed';changed['why']='changed'
            first=ScriptedPolicy(case['input'],case['tags']['python_version'])
            second=ScriptedPolicy(changed['input'],changed['tags']['python_version'])
            self.assertEqual(first.config,second.config);self.assertEqual(first([]),second([]))
    def test_unknown_question_has_no_general_reasoning_claim(self):
        result=run_controller(self.tools,'How frequently does our cloud provider back up these files?')
        self.assertEqual(result['status'],'incomplete');self.assertEqual(result['reason'],'no_refinement_rule')
    def test_corrupted_read_result_fails_controller(self):
        original=self.tools.read
        self.tools.read=lambda handle:dict(original(handle),text='invented')
        result=run_controller(self.tools,QUESTION)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['reason'],'invalid_read_result')

if __name__=='__main__':unittest.main()
