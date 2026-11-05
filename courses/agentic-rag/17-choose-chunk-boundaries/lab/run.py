"""Compare actual source spans under three declared chunk-boundary policies."""
import argparse
import json
from pathlib import Path
from chunk_index import CONFIGS,build_index,validate_index

INSTRUCTION='Call save_copy(path, text)'
QUALIFIER='This operation refuses an existing path.'

def run():
    root=Path(__file__).parent
    indexes={name:build_index(root/'fixtures/source-manifest.json',config) for name,config in CONFIGS.items()}
    comparisons=[]
    for name,index in indexes.items():
        validate_index(index)
        source=next(doc for doc in index['documents'] if doc['source_id']=='aster-copy-v1')
        instruction_start=source['text'].index(INSTRUCTION);qualifier_start=source['text'].index(QUALIFIER)
        containing=[chunk for chunk in index['chunks'] if chunk['source_id']==source['source_id'] and chunk['start']<=instruction_start and chunk['end']>=instruction_start+len(INSTRUCTION)]
        comparisons.append({'strategy':name,'chunk_count':len(index['chunks']),'instruction_span':[instruction_start,instruction_start+len(INSTRUCTION)],'qualifier_span':[qualifier_start,qualifier_start+len(QUALIFIER)],'instruction_containing_chunk_ids':[c['chunk_id'] for c in containing],'instruction_and_qualifier_share_chunk':any(c['start']<=qualifier_start and c['end']>=qualifier_start+len(QUALIFIER) for c in containing)})
    return {'execution_mode':'offline-synthetic-source-processing','fixture_scope':'Original synthetic Aster API contracts; no real SDK facts, embeddings or semantic-quality experiment.','comparisons':comparisons,'indexes':indexes}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();result=run()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'execution_mode':result['execution_mode'],'comparisons':result['comparisons']},sort_keys=True))
