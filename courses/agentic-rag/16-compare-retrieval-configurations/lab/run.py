"""Retrieve first, then join original development labels and calculate metrics."""
import json
from vector_retriever import load_inputs
from compare import bind_targets,evaluate,retrieve_runs,CANDIDATE_BUDGET,RANK_CONSTANT,CUTOFFS,CONFIGURATIONS


def run():
    snapshot,embeddings,cases=load_inputs()
    questions=[{'case_id':c['id'],'query':c['input'],'version':c['tags']['python_version']} for c in cases]
    rankings=retrieve_runs(snapshot,embeddings,questions)
    bindings,receipts=bind_targets(snapshot,cases)
    result=evaluate(rankings,bindings)
    return {'execution_mode':'offline-frozen-development-comparison','model_called':False,'snapshot_id':snapshot['snapshot_id'],'frozen_configuration':{'names':CONFIGURATIONS,'candidate_budget_per_branch':CANDIDATE_BUDGET,'rank_constant':RANK_CONSTANT,'cutoffs':CUTOFFS,'scope':'four original development cases; no held-out queries; no configuration tuning'},'label_binding_receipts':receipts,'retrieval_runs':rankings,**result,'limit':'Descriptive results on three supported development questions, not a general search-quality estimate or model comparison. Unsupported questions have no retrieval target and are excluded from metric means.'}


if __name__=='__main__':print(json.dumps(run(),indent=2))
