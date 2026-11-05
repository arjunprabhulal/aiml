import asyncio
from dataclasses import replace
import json
from pathlib import Path
import unittest
from acceptance import Policy, handle, invoke, encode, harness
from inspect_acceptance import record
import task

ROOT = Path(__file__).resolve().parent


class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = record()
        cases = harness.load_cases(ROOT / 'cases.json', harness.load_task('task'))
        cls.case = next(c for c in cases['cases'] if c['id'] == 'v3-production-lookup')
        cls.source = (ROOT / 'pages.json').read_bytes()

    def test_task_correctness_and_resource_limits_are_both_required(self):
        self.assertTrue(self.result['scenarios']['normal']['meets_contract'])
        wrong = self.result['scenarios']['wrong_command']
        self.assertEqual(wrong['resource_status'], 'within_limits')
        self.assertEqual(wrong['quality']['verdict'], 'fail')
        self.assertFalse(wrong['meets_contract'])
        self.assertIsNone(wrong['response'])

    def test_oversized_source_is_refused_before_application_call(self):
        row = self.result['scenarios']['oversized_source']
        self.assertFalse(row['called'])
        self.assertEqual(row['quality']['verdict'], 'not_run')
        self.assertEqual(row['resource_status'], 'source_too_large')

    def test_output_limit_withholds_without_truncating_a_command(self):
        row = self.result['scenarios']['output_limit']
        self.assertTrue(row['called'])
        self.assertEqual(row['quality']['verdict'], 'pass')
        self.assertGreater(row['output_bytes'], 1)
        self.assertIsNone(row['response'])
        self.assertFalse(row['meets_contract'])

    def test_full_queue_prevents_invocation(self):
        row = self.result['scenarios']['queue_full']
        self.assertFalse(row['called'])
        self.assertEqual(row['resource_status'], 'queue_full')
        self.assertEqual(row['capacity_after']['active'], 0)

    def test_expired_queue_wait_is_not_an_execution_timeout(self):
        row = self.result['scenarios']['wait_timeout']
        self.assertFalse(row['called'])
        self.assertEqual(row['resource_status'], 'wait_timeout')
        self.assertEqual(row['capacity_after']['active'], 0)
        self.assertEqual(row['capacity_after']['waiting'], 0)

    def test_required_refusal_can_meet_the_response_contract(self):
        row = self.result['scenarios']['required_refusal']
        self.assertTrue(row['called'])
        self.assertTrue(row['meets_contract'])
        self.assertIn('refused', row['response'])

    def test_source_byte_boundary_is_inclusive(self):
        async def check():
            policy = replace(Policy(), max_source_bytes=len(self.source))
            self.assertTrue((await handle(self.case, self.source, policy, policy.gate()))['called'])
            self.assertFalse((await handle(self.case, self.source+b' ', policy, policy.gate()))['called'])
        asyncio.run(check())

    def test_output_byte_boundary_is_inclusive(self):
        size = len(encode(invoke(self.case, json.loads(self.source))))
        async def check():
            for limit, expected in [(size, True), (size-1, False)]:
                policy = replace(Policy(), max_output_bytes=limit)
                row = await handle(self.case, self.source, policy, policy.gate())
                self.assertEqual(row['meets_contract'], expected)
        asyncio.run(check())

    def test_byte_count_uses_encoded_bytes_not_characters(self):
        value = {'text': 'é'}
        self.assertGreater(len(encode(value)), len(encode(value).decode('utf-8')))

    def test_invalid_policy_values_are_refused(self):
        for values in [dict(max_source_bytes=True), dict(max_output_bytes=0), dict(max_active=0), dict(wait_seconds=float('nan'))]:
            with self.assertRaises(ValueError):
                Policy(**values)

    def test_malformed_source_does_not_call_application(self):
        async def check():
            for source in (b'{', b'{}', b'\xff'):
                policy = Policy()
                result = await handle(self.case, source, policy, policy.gate())
                self.assertFalse(result['called'])
                self.assertEqual(result['resource_status'], 'source_invalid')
        asyncio.run(check())

    def test_gate_configuration_cannot_disagree_with_reported_policy(self):
        policy = Policy()
        async def check():
            with self.assertRaisesRegex(ValueError, 'must match'):
                await handle(self.case, self.source, policy, replace(policy, max_active=2).gate())
        asyncio.run(check())

    def test_nonserializable_output_is_withheld_without_losing_the_verdict(self):
        policy = Policy()
        async def check():
            row = await handle(self.case, self.source, policy, policy.gate(), lambda case, pages: {'a set'})
            self.assertEqual(row['quality']['verdict'], 'fail')
            self.assertEqual(row['resource_status'], 'output_not_serializable')
            self.assertIsNone(row['response'])
        asyncio.run(check())

    def test_record_matches_actual_local_outcomes(self):
        self.assertEqual(self.result, json.loads((ROOT / 'result.json').read_text()))


if __name__ == '__main__':
    unittest.main()
