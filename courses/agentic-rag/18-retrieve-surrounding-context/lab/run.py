"""Expand controlled seed IDs; seeds are not model or search execution claims."""
import argparse
import json
from pathlib import Path
from chunk_index import build_index,CONFIGS
from surround import expand_context,validate_windows

def run():
    index=build_index(Path(__file__).parent/'fixtures/source-manifest.json',CONFIGS['paragraph'])
    primary=[c for c in index['chunks'] if c['source_id']=='aster-copy-v1' and c['section_title']=='Create a copy']
    seeds=[primary[0]['chunk_id'],primary[2]['chunk_id']]
    windows=expand_context(index,seeds,1);validate_windows(index,windows)
    return {'execution_mode':'offline-explicit-seed-expansion','fixture_scope':'Controlled seed IDs in synthetic API documents; neighbor passages are not retrieval hits.','index':index,'windows':windows}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();result=run()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'execution_mode':result['execution_mode'],'seed_count':len(result['windows']['seed_ids']),'groups':[{'source_id':g['source_id'],'version':g['version'],'section_title':g['section_title'],'chunk_count':len(g['chunk_ids']),'seed_count':len(g['seed_ids']),'member_roles':[m['role'] for m in g['members']]} for g in result['windows']['groups']]},sort_keys=True))
