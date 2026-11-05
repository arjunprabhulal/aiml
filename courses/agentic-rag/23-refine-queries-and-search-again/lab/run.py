"""Execute a declared rule controller; no model chooses tools or rewrites."""
import argparse
import json
from pathlib import Path
from tools import DocumentationTools,load_snapshot
from refine import run_controller

QUESTION='Will write_text replace the contents of an existing file?'

def run():
    tools=DocumentationTools(load_snapshot())
    try:
        result=run_controller(tools,QUESTION,'3.12')
        duplicate={'name':'controlled-duplicate-query','initial_query':'text','refinement_query':'text','required_marker':'not-present','max_rounds':2}
        stopped=run_controller(tools,QUESTION,'3.12',duplicate)
        return {'execution_mode':'offline-scripted-retrieval-controller','model_called':False,'corpus_id':tools.corpus_id,'controller':result,'controlled_duplicate_stop':stopped,'interpretation':'Declared question-only rules and literal passage checks; not an executed model agent or semantic quality experiment.'}
    finally:tools.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();result=run();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'execution_mode':result['execution_mode'],'status':result['controller']['status'],'reason':result['controller']['reason'],'query_history':result['controller']['query_history'],'read_sources':[o['result']['source_id'] for o in result['controller']['observations'] if o['tool']=='read'],'controlled_duplicate_reason':result['controlled_duplicate_stop']['reason']},sort_keys=True))
