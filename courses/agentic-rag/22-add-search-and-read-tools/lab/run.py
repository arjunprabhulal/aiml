"""Execute real native search and exact local passage resolution."""
import argparse
import json
from pathlib import Path
from tools import DocumentationTools,load_snapshot,ToolError

def run():
    tools=DocumentationTools(load_snapshot())
    try:
        search=tools.search('overwritten',k=2,version='3.12')
        reads=[tools.read(handle) for handle in search['results']]
        for handle,result in zip(search['results'],reads):tools.validate_read(result,handle)
        empty=tools.search('xyznotindexed',k=2,version='3.12')
        wrong_version=tools.search('overwritten',k=2,version='3.13')
        altered=dict(search['results'][0],version='3.13')
        try:tools.read(altered)
        except ToolError as error:refusal=str(error)
        return {'execution_mode':'offline-native-document-search-and-read','model_called':False,'corpus_id':tools.corpus_id,'search':search,'reads':reads,'no_match':empty,'empty_eligible_version':wrong_version,'changed_handle_refusal':refusal,'interpretation':'Tool contract checks and native retrieval only; no model selection, answer generation or permission system.'}
    finally:tools.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();result=run();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'execution_mode':result['execution_mode'],'search_results':len(result['search']['results']),'read_source_ids':[row['source_id'] for row in result['reads']],'changed_handle_refusal':result['changed_handle_refusal'],'no_match_count':len(result['no_match']['results']),'empty_eligible_count':len(result['empty_eligible_version']['results'])},sort_keys=True))
