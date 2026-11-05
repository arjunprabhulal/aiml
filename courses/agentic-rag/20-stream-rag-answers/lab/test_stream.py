import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from stream_core import (StreamConsumer,DEVELOPMENT_CASES,RECORDING_SHA256,load_binding,replay_frames,encode_frames,byte_fragments,consume,digest,MAX_TOTAL_BYTES,MAX_FRAME_BYTES)

class StreamTests(unittest.TestCase):
    def setUp(self):self.binding,self.raw=load_binding('replace-file')
    def frame(self,sequence,kind,**extra):return dict(sequence=sequence,kind=kind,binding_sha256=digest(self.binding),**extra)
    def content(self,text,terminal='done'):
        return [self.frame(1,'content_delta',text=text),self.frame(2,terminal,**({} if terminal=='done' else {'reason':'controlled_unit_failure'}))]
    def result(self,frames):return consume(byte_fragments(encode_frames(frames)),self.binding)
    def assert_withheld(self,result):
        self.assertIsNone(result['accepted_answer']);self.assertEqual(result['citations'],[])
        self.assertFalse(any(e['kind']=='validated_answer' for e in result['events']))
    def test_original_recording_pin_and_development_only_allowlist(self):
        raw=(Path(__file__).parent/'fixtures/recording.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),RECORDING_SHA256)
        with patch('pathlib.Path.read_bytes',side_effect=AssertionError('must refuse before reading')):
            with self.assertRaisesRegex(ValueError,'development_case_required'):load_binding('held-out-case')
    def test_all_four_original_contents_replay_exactly(self):
        for case in DEVELOPMENT_CASES:
            binding,raw=load_binding(case);result=consume(byte_fragments(encode_frames(replay_frames(case))),binding)
            self.assertEqual(result['status'],'complete');self.assertEqual(result['provisional_content'],raw)
            self.assertEqual(result['accepted_answer'],json.loads(raw))
    def test_split_utf8_and_json_boundaries_are_not_frames(self):
        # Controlled transport unit text, not a new or modified model recording.
        reply={'status':'answered','answer':'café λ is controlled unit text','source_ids':['path-write']}
        wire=encode_frames(self.content(json.dumps(reply,ensure_ascii=False)))
        result=consume((wire[i:i+1] for i in range(len(wire))),self.binding)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['accepted_answer'],reply)
        self.assertGreater(result['stats']['transport_fragments'],result['stats']['application_frames'])
    def test_done_is_provisional_until_transport_eof(self):
        consumer=StreamConsumer(self.binding)
        consumer.feed(encode_frames(replay_frames('replace-file')))
        self.assertFalse(any(e['kind']=='validated_answer' for e in consumer.events))
        self.assertEqual(consumer.finish()['status'],'complete')
    def test_valid_json_without_terminal_is_not_accepted(self):
        result=self.result(self.content(self.raw)[:-1]);self.assertEqual(result['status'],'incomplete');self.assert_withheld(result)
    def test_truncated_frame_and_utf8_refused(self):
        wire=encode_frames(self.content(self.raw))
        for wire,reason in [(wire[:-3],'truncated_frame'),(encode_frames(self.content(self.raw)[:-1])+b'\xc3','truncated_utf8'),(b'\xff','invalid_utf8')]:
            result=consume([wire],self.binding);self.assertEqual(result['reason'],reason);self.assert_withheld(result)
    def test_duplicate_out_of_order_and_boolean_sequences_refused(self):
        original=replay_frames('replace-file')
        for frames in [[original[0],original[0]], [original[1],original[0]], [dict(original[0],sequence=True)]]:
            result=self.result(frames);self.assertEqual(result['reason'],'invalid_sequence');self.assert_withheld(result)
    def test_no_frames_or_bytes_after_terminal(self):
        frames=self.content(self.raw)
        for wire in [encode_frames(frames+[self.frame(3,'done')]),encode_frames(frames+[self.frame(3,'content_delta',text='extra')]),encode_frames(frames)+b' ']:
            result=consume([wire],self.binding);self.assertEqual(result['status'],'invalid');self.assert_withheld(result)
    def test_producer_io_error_retains_partial_without_acceptance(self):
        for frames in [self.content(self.raw)[:1],self.content(self.raw)]:
            def broken_transport():
                yield encode_frames(frames)
                raise OSError('controlled producer unit failure')
            result=consume(broken_transport(),self.binding)
            self.assertEqual(result['status'],'error');self.assertEqual(result['reason'],'transport_io_error')
            self.assertEqual(result['provisional_content'],self.raw)
            self.assert_withheld(result)
    def test_cancel_and_error_withhold_even_complete_json(self):
        for terminal in ['cancel','error']:
            result=self.result(self.content(self.raw,terminal));self.assertIn(result['status'],['cancelled','error']);self.assert_withheld(result)
            self.assertEqual(result['provisional_content'],self.raw)
    def test_invalid_json_and_duplicate_keys_refused(self):
        for text in ['{"status":','{"status":"answered","status":"not_in_docs","answer":"x","source_ids":[]}','NaN']:
            result=self.result(self.content(text));self.assertEqual(result['status'],'invalid');self.assert_withheld(result)
    def test_invalid_schema_status_and_citation_consistency_refused(self):
        variants=[{'status':'answered','answer':'x','source_ids':[]},{'status':'not_in_docs','answer':'x','source_ids':['path-write']},{'status':'answered','answer':'','source_ids':['path-write']},{'status':'unknown','answer':'x','source_ids':['path-write']},{'status':'answered','answer':'x','source_ids':['path-write'],'extra':True}]
        for reply in variants:
            result=self.result(self.content(json.dumps(reply)));self.assertEqual(result['status'],'invalid');self.assert_withheld(result)
    def test_unknown_context_citation_refused(self):
        text=json.dumps({'status':'answered','answer':'x','source_ids':['unknown-source']})
        result=self.result(self.content(text));self.assertEqual(result['reason'],'unknown_context_citation');self.assert_withheld(result)
    def test_known_citation_links_resolve_from_bound_context(self):
        result=self.result(self.content(self.raw))
        self.assertEqual(result['citations'][0]['source_id'],'path-write')
        self.assertEqual(result['citations'][0]['url'],'https://docs.python.org/3.12/library/pathlib.html#pathlib.Path.write_text')
    def test_changed_messages_corpus_or_context_cannot_replay(self):
        for field in ['messages','corpus_identity','selected_context','request_sha256']:
            changed=copy.deepcopy(self.binding);changed[field]='changed'
            with self.assertRaisesRegex(ValueError,'request_binding_mismatch'):replay_frames('replace-file',request=changed)
            with self.assertRaisesRegex(ValueError,'request_binding_mismatch'):StreamConsumer(changed)
    def test_frame_request_identity_mismatch_refused(self):
        frames=self.content(self.raw);frames[0]['binding_sha256']='changed'
        result=self.result(frames);self.assertEqual(result['reason'],'frame_request_mismatch');self.assert_withheld(result)
    def test_stream_frame_content_and_count_limits(self):
        for wire,reason in [(b'x'*(MAX_TOTAL_BYTES+1),'stream_byte_limit'),(b'x'*(MAX_FRAME_BYTES+1),'frame_byte_limit')]:
            result=consume([wire],self.binding);self.assertEqual(result['reason'],reason);self.assert_withheld(result)
        frames=[self.frame(i+1,'content_delta',text='x'*4000) for i in range(5)]
        result=self.result(frames);self.assertEqual(result['reason'],'content_limit');self.assert_withheld(result)
        with patch('stream_core.MAX_FRAMES',1):
            result=self.result(self.content(self.raw));self.assertEqual(result['reason'],'frame_count_limit');self.assert_withheld(result)
    def test_invalid_frames_and_utf8_surrogate_content_refused(self):
        for frame in [self.frame(1,'unknown'),self.frame(1,'content_delta',text=''),self.frame(1,'content_delta',text='\ud800')]:
            wire=(json.dumps(frame)+'\n').encode()
            result=consume([wire],self.binding);self.assertEqual(result['status'],'invalid');self.assert_withheld(result)

if __name__=='__main__':unittest.main()
