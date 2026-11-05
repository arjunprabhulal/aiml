"""Retrieve chart descriptions with PGVectorStore; send the selected PNGs to Gemini."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from PIL import Image
from langchain_core.documents import Document
from library import DocsEmbeddings, MODEL, RecordedEmbeddings, answer_question, vector_store
from pg_cluster import Cluster
ROOT=Path(__file__).parent
QUESTION='Which model size has the lowest p95 latency, and what is its value in ms?'

def pixel_hash(path:Path)->str:
    with Image.open(path) as image:
        image.load()
        gray=image.convert('L')
        return hashlib.sha256(f'{gray.width}x{gray.height}:'.encode()+gray.tobytes()).hexdigest()

def figure_documents():
    return [Document(id=str(uuid5(NAMESPACE_URL,f['id'])),page_content=f['text'],
            metadata={'source':f['id'],'team':'platform','image':f['image'],'pixel_sha256':f['pixel_sha256']})
            for f in json.loads((ROOT/'library-figures.json').read_text())]

def image_blocks(retrieved):
    content=[]
    for doc in retrieved:
        path=ROOT/doc.metadata['image']
        if pixel_hash(path)!=doc.metadata['pixel_sha256']:
            raise ValueError('selected image pixels changed after indexing')
        content += [{'type':'text','text':f'Image for source_id {doc.id} ({doc.metadata["source"]})'},
                    {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()}}]
    return content

def main():
    chunks=figure_documents()
    model=DocsEmbeddings(model=MODEL)
    vectors=model.embed_documents([d.page_content for d in chunks])
    record={'documents':dict(zip([d.page_content for d in chunks],vectors)),
            'queries':{QUESTION:model.embed_query(QUESTION)}}
    (ROOT/'library-image-vectors.json').write_text(json.dumps(record,indent=2)+'\n')
    with Cluster() as pg:
        with vector_store(pg.url,RecordedEmbeddings(record),table='figures') as store:
            store.add_documents(chunks,ids=[d.id for d in chunks])
            selected=store.similarity_search(QUESTION,k=2,filter={'team':'platform'})
            results=[]
            for mode in ['descriptions','images']:
                result=answer_question(QUESTION,selected,image_blocks(selected) if mode=='images' else None)
                results.append({'mode':mode,**result})
    output={'recorded_at':datetime.now(timezone.utc).isoformat(),'model':'gemini-3.8-flash',
            'runs_per_mode':1,'question':QUESTION,'expected':{'model_size':'medium','latency_ms':380},
            'chart_values_are':'supplied illustration values, not measurements of this pipeline',
            'selected':[{'id':d.id,**d.metadata} for d in selected],'results':results}
    (ROOT/'library-image-run.json').write_text(json.dumps(output,indent=2,default=str)+'\n')
    print(json.dumps(output,indent=2,default=str))
if __name__=='__main__': main()
