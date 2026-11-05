import json
from pathlib import Path
import unittest
from docuctl_policy import Boundary, HandoffError, check_handoff
from docuctl_demo import ACCOUNT, call, run

class DocuctlPolicy(unittest.TestCase):
    def test_only_declared_pages_and_reviewers_are_allowed(self):
        b=Boundary(ACCOUNT)
        self.assertEqual(b.decide(call('publish_page',page_id='private-page',reason='release'))[:2],('refused','trusted values'))
        self.assertEqual(b.decide(call('submit_review',reviewer='outsider@example.test',subject='x',body='x'))[:2],('refused','trusted values'))
    def test_untrusted_content_holds_even_an_owned_page(self):
        b=Boundary(ACCOUNT);proposal=call('publish_page',page_id='deploy-35',reason='release')
        self.assertEqual(b.decide(proposal)[0],'allowed');b.mark_untrusted('page note')
        self.assertEqual(b.decide(proposal)[:2],('held for review','taint'))
    def test_untrusted_text_cannot_grant_access_to_another_page(self):
        b=Boundary(ACCOUNT);b.mark_untrusted('handoff')
        self.assertEqual(b.decide(call('publish_page',page_id='private-page',reason='release'))[0],'refused')
    def test_reason_is_an_explicit_enum(self):
        self.assertEqual(Boundary(ACCOUNT).decide(call('publish_page',page_id='deploy-35',reason='urgent'))[:2],('refused','reason'))
    def test_unknown_tool_extra_fields_and_nontext_values_are_refused(self):
        b=Boundary(ACCOUNT)
        for proposal in [None,{'name':[]},call('erase_all'),call('read_page_note',page_id='deploy-35',admin='yes'),call('read_page_note',page_id=3),{'name':'read_page_note','arguments':None}]:
            self.assertEqual(b.decide(proposal)[0],'refused')
    def test_handoff_exact_fields_and_text_types_are_required(self):
        good={'from':'worker','task':'read','page_id':'deploy-35','summary':'text'}
        self.assertEqual(check_handoff(good),good)
        for bad in [None,{**good,'permission':'admin'},{**good,'summary':3}]:
            with self.assertRaises(HandoffError):check_handoff(bad)
    def test_valid_handoff_still_marks_the_conversation_untrusted(self):
        data=run();self.assertEqual(data['after_handoff'][0]['decision'],'held for review')
        self.assertEqual(data['after_handoff'][1]['decision'],'refused')
    def test_saved_decisions_match_current_code(self):
        self.assertEqual(run(),json.loads((Path(__file__).parent/'docuctl-output.json').read_text()))
