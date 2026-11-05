"""Run the original synthetic contract gate locally; never generate an answer."""
import json
from pathlib import Path
import shutil
import tempfile
from conflicts import DirectiveError,gate
from load_documents import IngestionError

ROOT=Path(__file__).parent


def run():
    manifest=ROOT/'fixtures/source-manifest.json'
    cases=[]
    for name,ids,version,key in [
        ('newer-wrong-version-excluded',['quill-guide','quill-new-version'],'1.0','existing_path'),
        ('compatible-agreement',['quill-guide','quill-reference'],'1.0','existing_path'),
        ('same-version-conflict',['quill-guide','quill-conflicting-guide'],'1.0','existing_path'),
        ('absent-version',['quill-guide','quill-new-version'],'3.0','existing_path'),
        ('missing-claim',['quill-guide'],'1.0','close_required'),
        ('partial-missing-claim',['quill-guide','quill-missing-claim'],'1.0','existing_path'),
        ('unknown-directive-value',['quill-unknown-value'],'1.0','existing_path'),
        ('malformed-directive',['quill-malformed'],'1.0','existing_path'),
    ]:
        try:result=gate(manifest,ids,version,key)
        except DirectiveError as error:result={'status':'refused','error':type(error).__name__,'reason':str(error),'answer_request':None}
        cases.append({'case_id':name,'candidate_ids':ids,'requested_version':version,'claim_key':key,'result':result})
    with tempfile.TemporaryDirectory() as tmp:
        copy=Path(tmp)/'fixtures';shutil.copytree(ROOT/'fixtures',copy)
        with (copy/'docs/quill-guide.md').open('a') as stream:stream.write('\nChanged source after pinning.\n')
        try:gate(copy/'source-manifest.json',['quill-guide'],'1.0')
        except IngestionError as error:changed={'status':'refused','error':type(error).__name__,'reason':str(error),'answer_request':None}
    return {'execution_mode':'offline-explicit-synthetic-directive-gate','model_called':False,'fixture_kind':'original synthetic developer documentation; Quill is fictional','grammar':'exact whole line @quill create_copy existing_path=refuse|overwrite or close_required=yes|no','cases':cases,'changed_source':changed,'policy':'Exact requested version before directive parsing. Any eligible source missing the requested key withholds the request. No source-priority or newest-version winner.','limit':'This parses explicit machine-readable teaching contracts, not arbitrary prose contradictions or semantic agreement. A prepared cited request is not a generated answer or a correctness/security guarantee.'}


if __name__=='__main__':print(json.dumps(run(),indent=2))
