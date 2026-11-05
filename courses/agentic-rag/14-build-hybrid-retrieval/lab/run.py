"""Run only the four preserved development questions, without inference."""
import argparse
import json
from pathlib import Path
import sqlite3
from hybrid import HybridRetriever
from vector_retriever import load_inputs

def run():
    snapshot,embeddings,cases=load_inputs();retriever=HybridRetriever(snapshot,embeddings)
    try:
        results=[]
        for case in cases:
            policy={'version':{'$eq':case['tags']['python_version']}}
            result=retriever.search(case['input'],k=2,candidate_budget=3,rank_constant=60,policy=policy)
            results.append({'case_id':case['id'],'case_class':case['class'],'policy':policy,**result})
        return {'execution_mode':'offline-saved-vector-replay-native-sqlite-langchain-rrf','model_called':False,'snapshot_id':snapshot['snapshot_id'],'sqlite_version':sqlite3.sqlite_version,'configuration':{'k':2,'candidate_budget_per_branch':3,'rank_constant':60},'development_cases':results,'interpretation':'Ranking only. Retrieval does not establish answer correctness or support; no held-out queries executed.'}
    finally:retriever.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=run();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'execution_mode':result['execution_mode'],'development_cases':[{'case_id':c['case_id'],'lexical_order':[r['source_id'] for r in c['lexical']],'vector_order':[r['source_id'] for r in c['vector']],'fused_order':[r['source_id'] for r in c['results']]} for c in result['development_cases']]},sort_keys=True))
