"""Record existing local models only. This script never pulls model weights."""
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path
from ollama import Client
from langchain_ollama import ChatOllama, OllamaEmbeddings
from agentic_rag.concepts import ROOT, Reply, answer, build_index, chunks

QUESTIONS = ['How do I save UTF-8 text with pathlib?',
             'How many days does this service keep backups?']
MODELS = ['qwen3-embedding:0.6b', 'gemma4:e2b']
client = Client()
models = {m.model: m.digest for m in client.list().models}
if any(name not in models for name in MODELS):
    raise RuntimeError('This recording requires the already installed models; no weights are downloaded.')
embedder = OllamaEmbeddings(model=MODELS[0], client_kwargs={'timeout': 120})
texts = [d.page_content for d in chunks()]
query_input = lambda q: 'Instruct: Retrieve Python documentation that answers the developer question\nQuery: ' + q
vectors = {'documents': dict(zip(texts, embedder.embed_documents(texts))),
           'questions': {q: embedder.embed_query(query_input(q)) for q in QUESTIONS}}
index = build_index(vectors)
model = ChatOllama(model=MODELS[1], temperature=0, num_predict=400,
                   client_kwargs={'timeout': 180}).with_structured_output(Reply)
replies, requests, results = [], [], []
def generate(messages):
    requests.append(messages)
    reply = model.invoke(messages).model_dump()
    replies.append(reply)
    return reply
for question in QUESTIONS:
    results.append(answer(question, index, generate))
record = {'recorded_on': '2026-10-22', 'run_scope': 'One local run per question; not a quality benchmark.',
          'models': {name: models[name] for name in MODELS},
          'environment': {'python': platform.python_version(), 'packages': {name: version(name) for name in
              ['langchain-core','langchain-ollama','langchain-text-splitters','ollama','pydantic']}},
          'corpus_sha256': hashlib.sha256((ROOT/'data'/'docs.json').read_bytes()).hexdigest(),
          'query_instruction': 'Retrieve Python documentation that answers the developer question',
          'embeddings': vectors, 'questions': QUESTIONS, 'requests': requests,
          'model_replies': replies, 'results': results}
(ROOT/'runs'/'2026-10-22-concept'/'recorded-run.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(results, indent=2))
