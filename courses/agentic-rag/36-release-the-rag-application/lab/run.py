"""Run a local release-refusal and rollback drill; no cloud deployment."""
from pathlib import Path
import argparse,json,tempfile
from release import package,verify,smoke,task_gate,promote,rollback,atomic_state

def run():
    source=Path(__file__).parent
    with tempfile.TemporaryDirectory(prefix='rag-release-drill-') as temporary:
        root=Path(temporary);a=root/'a';b=root/'b';pointer=root/'active.json'
        first=package(source,a,'fixture-previous');candidate=package(source,b,'candidate')
        # This is explicitly a seeded artifact registry, not a claimed prior deployment.
        seed={'current':{'directory':str(a),'release_id':first},'previous':None}
        atomic_state(pointer,seed)
        staged=smoke(b,candidate);gate=task_gate(b,candidate)
        before=pointer.read_bytes()
        try:promote(pointer,b,candidate,staged)
        except ValueError as error:refusal=str(error)
        else:raise AssertionError('Recorded task misses must prevent promotion')
        unchanged=pointer.read_bytes()==before
        assert refusal=='task_gate_not_accepted' and unchanged
        # An explicitly seeded two-release registry exercises rollback mechanics only.
        atomic_state(pointer,{'current':{'directory':str(b),'release_id':candidate},'previous':seed['current']})
        restored=rollback(pointer)
        assert restored['current']['release_id']==first
        # A changed artifact cannot be accepted under its retained expected identity.
        (b/'api.py').write_text('# changed artifact\n')
        try:verify(b,candidate)
        except ValueError as error:tamper=str(error)
        else:raise AssertionError('Changed artifact was accepted')
        return {'schema_version':1,'execution_mode':'actual-local-staging-http-and-artifact-registry',
                'model_called':False,'release_ids':{'previous_fixture':first,'candidate':candidate},
                'runtime_smoke':staged,'task_gate':gate,
                'promotion':{'refused':refusal,'pointer_unchanged':unchanged},
                'rollback':{'setup':'synthetic two-entry artifact registry; not prior deployment',
                            'restored_previous_identity':restored['current']['release_id']==first},
                'changed_artifact':{'refused':tamper},
                'scope':'The staged service really ran over loopback HTTP. Promotion was blocked by archived task failures. Only a local artifact pointer is changed in the rollback drill; no running traffic, cloud release or answer-quality approval.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=run();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('staged runtime smoke:',result['runtime_smoke']['passed'])
    print('archived scripted task gate:',result['task_gate']['decision'])
    print('promotion:',result['promotion']['refused'],'pointer unchanged:',result['promotion']['pointer_unchanged'])
    print('seeded local rollback:',result['rollback']['restored_previous_identity'])
    print('changed artifact:',result['changed_artifact']['refused'])
