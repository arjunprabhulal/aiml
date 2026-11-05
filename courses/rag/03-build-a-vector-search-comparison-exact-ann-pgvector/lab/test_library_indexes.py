import json
from pathlib import Path
import unittest
from library_compare import compare
ROOT=Path(__file__).parent

def scans(value):
    if isinstance(value,dict):
        if 'Node Type' in value:yield value
        for item in value.values():yield from scans(item)
    elif isinstance(value,list):
        for item in value:yield from scans(item)

class IndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.comparison=compare()
    def test_query_plans_identify_the_search_actually_used(self):
        self.assertTrue(any(p['Node Type']=='Seq Scan' for p in scans(self.comparison['default_plan'])))
        for mode in self.comparison['modes'][1:]:
            self.assertTrue(any(p.get('Index Name')=='docs_ann' for p in scans(mode['plan'])))
    def test_approximate_results_are_compared_with_exact_ids(self):
        exact={q['question']:set(q['ids']) for q in self.comparison['modes'][0]['queries']}
        for mode in self.comparison['modes'][1:]:
            for q in mode['queries']:
                self.assertEqual(q['recall_at_3'],len(set(q['ids'])&exact[q['question']])/len(exact[q['question']]))
        recorded=json.loads((ROOT/'library-comparison.json').read_text())
        self.assertTrue(any(q['recall_at_3']<1 for q in recorded['modes'][2]['queries']))
if __name__=='__main__':unittest.main(verbosity=2)
