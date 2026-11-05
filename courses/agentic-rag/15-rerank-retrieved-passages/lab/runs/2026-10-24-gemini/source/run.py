"""Execute deterministic candidate reranking on actual hybrid retrieval output."""
import json
from vector_retriever import load_inputs
from hybrid import HybridRetriever
from rerank import rerank


def run():
    snapshot,embeddings,cases=load_inputs();retriever=HybridRetriever(snapshot,embeddings);results=[]
    try:
        for case in cases:
            before=retriever.search(case['input'],k=3,candidate_budget=3,rank_constant=60,policy={'version':{'$eq':case['tags']['python_version']}})
            results.append({'case_id':case['id'],'query':case['input'],'requested_version':case['tags']['python_version'],'before':before['results'],'after':rerank(case['input'],before['results'],snapshot,k=3)})
        try:rerank(cases[0]['input'],[{**results[0]['before'][0],'text':'altered passage'}],snapshot)
        except ValueError as error:refusal=str(error)
        # A diagnostic deliberately removes the version filter; it reuses only
        # the first development question and demonstrates the read/write limit.
        diagnostic=retriever.search(cases[0]['input'],k=4,candidate_budget=4)
        unfiltered={'query':cases[0]['input'],'policy':None,'before':diagnostic['results'],'after':rerank(cases[0]['input'],diagnostic['results'],snapshot,k=4),'scope':'read/write lexical overlap diagnostic, not a new evaluation case'}
    finally:retriever.close()
    controlled_before=list(reversed(results[1]['before']))
    controlled={'scope':'controlled candidate-order contract check; not an evaluation case or quality gain','query':cases[1]['input'],'before':controlled_before,'after':rerank(cases[1]['input'],controlled_before,snapshot,k=3)}
    return {'mechanism_check':controlled,'execution_mode':'offline-transparent-coverage-reranking','model_called':False,'learned_reranker':False,'snapshot_id':snapshot['snapshot_id'],'configuration':{'candidate_budget':3,'rank_constant':60,'rerank_k':3,'score':'unique query token coverage','tie':'incoming rank'},'development_cases':results,'unfiltered_read_write_diagnostic':unfiltered,'empty_candidates':rerank(cases[0]['input'],[],snapshot),'altered_candidate_refusal':refusal,'limit':'Token overlap does not establish that a passage answers the question; it does not understand write versus read or unsupported requests.'}


if __name__=='__main__':print(json.dumps(run(),indent=2))
