"""Independent failure checks for the local artifact release boundary."""
from pathlib import Path
import copy,json,tempfile,unittest
from unittest.mock import patch
import release

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.source=Path(__file__).parent
        self.a=self.root/'a';self.b=self.root/'b';self.pointer=self.root/'active.json'
        self.aid=release.package(self.source,self.a,'a');self.bid=release.package(self.source,self.b,'b')
        self.smoke={'release_id':self.bid,'passed':True,'checks':{n:True for n in ['health','valid_request','strict_refusal','wire_digest','no_model']}}
    def test_changed_file_refused(self):
        (self.b/'api.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'file_hash'):release.verify(self.b,self.bid)
    def test_resigned_manifest_needs_retained_identity(self):
        m=json.loads((self.b/'manifest.json').read_bytes());m['files']['api.py']='0'*64
        (self.b/'manifest.json').write_bytes(release.canonical(m))
        with self.assertRaisesRegex(ValueError,'identity'):release.verify(self.b,self.bid)
    def test_extra_file_and_symlink_refused(self):
        extra=self.b/'extra.txt';extra.write_text('not declared')
        with self.assertRaisesRegex(ValueError,'unexpected'):release.verify(self.b,self.bid)
        extra.unlink();extra.symlink_to(self.a/'api.py')
        with self.assertRaisesRegex(ValueError,'unexpected'):release.verify(self.b,self.bid)
    def test_actual_recorded_task_failure_blocks_promotion(self):
        release.atomic_state(self.pointer,{'current':{'directory':str(self.a),'release_id':self.aid},'previous':None})
        before=self.pointer.read_bytes()
        self.assertEqual(release.task_gate(self.b,self.bid)['decision'],'FAIL')
        with self.assertRaisesRegex(ValueError,'task_gate'):release.promote(self.pointer,self.b,self.bid,self.smoke)
        self.assertEqual(self.pointer.read_bytes(),before)
    def test_smoke_binding_checks_are_required(self):
        for changed in [dict(self.smoke,release_id=self.aid),dict(self.smoke,passed=False),dict(self.smoke,checks={})]:
            with self.subTest(changed=changed),self.assertRaisesRegex(ValueError,'smoke'):release.promote(self.pointer,self.b,self.bid,changed)
    def test_positive_control_atomic_pointer_and_rollback(self):
        # This is a unit-test stub of a passing task gate, not a measured quality pass.
        first=dict(self.smoke,release_id=self.aid)
        with patch.object(release,'task_gate',return_value={'decision':'PASS'}):
            release.promote(self.pointer,self.a,self.aid,first)
            release.promote(self.pointer,self.b,self.bid,self.smoke)
        state=release.rollback(self.pointer)
        self.assertEqual(state['current']['release_id'],self.aid)
        self.assertFalse(list(self.root.glob('.candidate-*')))
    def test_rollback_revalidates_previous_bundle(self):
        release.atomic_state(self.pointer,{'current':{'directory':str(self.b),'release_id':self.bid},'previous':{'directory':str(self.a),'release_id':self.aid}})
        before=self.pointer.read_bytes();(self.a/'api.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'file_hash'):release.rollback(self.pointer)
        self.assertEqual(self.pointer.read_bytes(),before)
    def test_failed_atomic_replace_keeps_old_pointer(self):
        release.atomic_state(self.pointer,{'old':True});before=self.pointer.read_bytes()
        with patch.object(release.os,'replace',side_effect=OSError('controlled failure')):
            with self.assertRaises(OSError):release.atomic_state(self.pointer,{'new':True})
        self.assertEqual(self.pointer.read_bytes(),before)
        self.assertFalse(list(self.root.glob('.candidate-*')))
    def test_real_http_staged_runtime_and_refusal_drill(self):
        from run import run
        actual=run()
        self.assertTrue(actual['runtime_smoke']['passed'])
        self.assertEqual(actual['task_gate']['decision'],'FAIL')
        self.assertTrue(actual['promotion']['pointer_unchanged'])
        self.assertTrue(actual['rollback']['restored_previous_identity'])
    def test_smoke_does_not_write_bytecode_into_sealed_bundle(self):
        result=release.smoke(self.b,self.bid)
        self.assertTrue(result['passed'])
        self.assertFalse(list(self.b.rglob('*.pyc')))
        release.verify(self.b,self.bid)

if __name__=='__main__':unittest.main()
