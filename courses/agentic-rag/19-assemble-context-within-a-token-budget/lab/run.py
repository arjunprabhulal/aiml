"""Execute pinned local tokenization and complete-request budget decisions."""
import json
from assembler import RequiredContextTooLarge,escape
from budget_windows import assemble_windows
from fixture_cases import normal_case,literal_case,QUESTION,LITERAL
from surround import expand_context
from tokenizer import counter


def run():
    measured=counter();index,seeds,windows=normal_case()
    roomy=assemble_windows(index,windows,seeds,QUESTION,measured,context_limit=2048,max_new_tokens=128,margin=32)
    tight=assemble_windows(index,windows,seeds,QUESTION,measured,context_limit=768,max_new_tokens=128,margin=32)
    empty=assemble_windows(index,expand_context(index,[],radius=1),[],QUESTION,measured,context_limit=768,max_new_tokens=128,margin=32)
    literal_index,literal_seeds,literal_windows=literal_case()
    boundary=assemble_windows(literal_index,literal_windows,literal_seeds,QUESTION,measured,context_limit=2048,max_new_tokens=128,margin=32)
    boundary.update({'source_literal':LITERAL,'escaped_literal':escape(LITERAL),'literal_is_escaped':escape(LITERAL) in boundary['messages'][1]['content'],'raw_literal_is_absent':LITERAL not in boundary['messages'][1]['content'],'roles':[m['role'] for m in boundary['messages']],'limit':'Escaping keeps the string inside a reference block; this does not establish semantic prompt-injection protection.'})
    try:assemble_windows(index,windows,seeds,QUESTION,measured,context_limit=256,max_new_tokens=64,margin=16,instructions='Retain the required instruction. '*200)
    except RequiredContextTooLarge as error:
        overflow={'status':'rejected','error':type(error).__name__,'required_input_tokens':error.required,'available_input_tokens':error.available,'context_limit':256,'max_new_tokens':64,'margin':16}
    return {'execution_mode':'offline-pinned-tokenizer-request-assembly','model_called':False,'tokenizer':measured.profile(),'index_id':index['index_id'],'question':QUESTION,'ranked_seed_ids':seeds,'windows':windows,'roomy':roomy,'tight':tight,'empty_retrieval':empty,'literal_boundary':boundary,'required_context_overflow':overflow,'limit':'Configured limits are controlled fixture budgets, not the model context capacity. Tokenization and structural receipts do not establish an answer outcome or a security guarantee.'}


if __name__=='__main__':print(json.dumps(run(),indent=2))
