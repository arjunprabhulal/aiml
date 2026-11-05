"""Read-only checks for selected fresh local telemetry; no inference/export."""
import json
from pathlib import Path
import unittest
RUN = Path(__file__).resolve().parent / 'runs/live-2026-10-23'
class SelectedTraceTests(unittest.TestCase):
    def test_actual_local_span_tree_and_resource(self):
        spans = [json.loads(s) for s in (RUN / 'receipts/telemetry/traces.jsonl').read_text().splitlines()]
        self.assertEqual(len(spans), 10)
        ids = {s['context']['span_id'] for s in spans}
        self.assertEqual(sum(s['parent_id'] is None for s in spans), 1)
        self.assertTrue(all(s['parent_id'] is None or s['parent_id'] in ids for s in spans))
        self.assertEqual(sum(s['name'] == 'call_llm' for s in spans), 3)
        self.assertEqual({s['name'] for s in spans if s['name'].startswith('execute_tool')}, {'execute_tool list_pages', 'execute_tool read_page'})
        self.assertTrue(all(s['resource']['attributes']['service.name'] == 'docs-assistant' for s in spans))
    def test_answer_and_bounded_actual_request_count(self):
        self.assertIn('docs-assistant index --rebuild', (RUN / 'receipts/stdout.txt').read_text())
        ledger = json.loads((RUN / 'request-ledger.json').read_text())
        self.assertEqual(len(ledger), 3)
        self.assertTrue(all(s['max_output_tokens'] == 1024 for s in ledger))
if __name__ == '__main__':
    unittest.main()
