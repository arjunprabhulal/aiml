"""Optional: inspect cosine distance using the saved vectors, not a replacement store."""
import json
from pathlib import Path
import numpy as np
from library import documents
ROOT=Path(__file__).parent

def cosine_distances(matrix,query):
    matrix=np.asarray(matrix,dtype=np.float64); query=np.asarray(query,dtype=np.float64)
    if matrix.ndim!=2 or query.ndim!=1 or matrix.shape[1]!=query.shape[0]: raise ValueError('vector dimensions differ')
    if not np.isfinite(matrix).all() or not np.isfinite(query).all(): raise ValueError('vectors must be finite')
    norms=np.linalg.norm(matrix,axis=1); query_norm=np.linalg.norm(query)
    if np.any(norms==0) or query_norm==0: raise ValueError('cosine distance needs nonzero vectors')
    return 1-(matrix@query)/(norms*query_norm)

def main():
    saved=json.loads((ROOT/'vectors.json').read_text()); docs=documents()
    question='How do I roll back a service?'
    values=cosine_distances([saved['documents'][d.page_content] for d in docs],saved['queries'][question])
    order=np.argsort(values,kind='stable')[:3]
    result={'question':question,'dimensions':len(saved['queries'][question]),'compared_vectors':len(docs),
            'top3':[{'id':docs[int(i)].id,'source':docs[int(i)].metadata['source'],'cosine_distance':float(values[i])} for i in order]}
    (ROOT/'library-exact.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))
if __name__=='__main__': main()
