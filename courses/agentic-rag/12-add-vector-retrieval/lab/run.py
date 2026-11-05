"""Replay development queries through the actual installed LangChain store."""
import json
from vector_retriever import VectorRetriever,load_inputs


def run():
    snapshot,embeddings,cases=load_inputs();retriever=VectorRetriever(snapshot,embeddings)
    results=[]
    for case in cases:
        rows=retriever.search(case['input'],k=2,policy={'version':{'$eq':case['tags']['python_version']}})
        results.append({'case_id':case['id'],'case_class':case['class'],'query':case['input'],'requested_version':case['tags']['python_version'],'results':rows})
    try:retriever.search('An unrecorded developer question')
    except ValueError as error:refusal=str(error)
    return {'execution_mode':'offline-recorded-vector-replay','model_called':False,'store':'langchain_core.vectorstores.InMemoryVectorStore','snapshot_id':snapshot['snapshot_id'],'development_cases':results,'unknown_query_refusal':refusal,'interpretation':'Similarity scores order stored passages; returned passages do not establish that a question is answerable.'}


if __name__=='__main__':print(json.dumps(run(),indent=2))
