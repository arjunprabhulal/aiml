"""Task-specific automatic answer contracts; no faithfulness grader or LLM judge."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent/'src'))
from langchain_core.documents import Document
from agentic_rag.concepts import Reply,check_reply
from eval_task import validate_expected
NAME='rag-baseline-contracts'
VERSION='1'
OUTPUT_FIELDS={'status':str}
def reply_contract(case,output):
 try:
  reply=Reply.model_validate({k:output[k]for k in ('status','answer','source_ids')})
  selected=[Document(page_content='',metadata={'id':id})for id in output['context_ids']]
  check_reply(reply,selected)
 except (ValueError,KeyError,TypeError)as exc:return False,str(exc)
 return True,''
def expected_status(case,output):
 return output.get('status')==case['expected']['status'],'Reply status differs from the annotation.'
def target_source(case,output):
 if case['expected']['status']=='not_in_docs':return True,''
 targets={t['source_id']for t in case['expected']['targets']}
 return bool(targets&set(output.get('source_ids',[]))),'No designated target source is linked; this is alignment, not faithfulness.'
GRADERS=({'name':'reply-contract','version':'1','kind':'contract','check':reply_contract},
 {'name':'expected-status','version':'1','kind':'outcome','check':expected_status},
 {'name':'target-source-alignment','version':'1','kind':'contract','check':target_source})
