"""Run actual vector and FTS5 version-filtered searches with shared candidates."""
import json
from vector_retriever import VectorRetriever,load_inputs
from filtered_retrievers import LexicalRetriever,candidates


def run():
    snapshot,embeddings,cases=load_inputs();vector=VectorRetriever(snapshot,embeddings);lexical=LexicalRetriever(snapshot)
    steps=[]
    try:
        for version in ['3.12','3.13','9.99']:
            policy={'version':{'$eq':version}}
            steps.append({'policy':policy,'candidate_chunk_ids':candidates(vector.rows,policy),'vector_query':cases[0]['input'],'vector_results':vector.search(cases[0]['input'],k=2,policy=policy),'lexical_query':'encoding','lexical_results':lexical.search('encoding',k=2,policy=policy)})
        policy={'version':{'$eq':'3.13'}}
        raw=vector.search(cases[1]['input'],k=1)
        raw_lexical=lexical.search('encoding',k=1)
        underfill={'vector_query':cases[1]['input'],'lexical_query':'encoding','policy':policy,'vector_unfiltered_top1':raw,'vector_postfilter_top1':[r for r in raw if r['version']=='3.13'],'vector_prefilter_top1':vector.search(cases[1]['input'],k=1,policy=policy),'lexical_unfiltered_top1':raw_lexical,'lexical_postfilter_top1':[r for r in raw_lexical if r['version']=='3.13'],'lexical_prefilter_top1':lexical.search('encoding',k=1,policy=policy)}
        try:vector.search(cases[0]['input'],policy={'version':{'$ne':'3.12'}})
        except ValueError as error:refusal=str(error)
    finally:lexical.close()
    return {'execution_mode':'offline-recorded-vector-and-fts5-replay','model_called':False,'steps':steps,'prefilter_comparison':underfill,'invalid_operator_refusal':refusal,'policy':'None or empty object means all versions; only version $eq with a numeric major.minor string is supported. Unknown versions return no candidates.'}


if __name__=='__main__':print(json.dumps(run(),indent=2))
