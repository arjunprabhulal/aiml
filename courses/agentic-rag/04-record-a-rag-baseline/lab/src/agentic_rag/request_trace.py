"""Inspect actual replay transitions, without inventing model spans or timings."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from .concepts import ROOT, Reply, SavedEmbeddings, build_index, check_reply, chunks, prompt
from langchain_core.vectorstores import InMemoryVectorStore


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def chunk_id(doc):
    return doc.metadata["id"] + ":" + digest({"text": doc.page_content, "url": doc.metadata["url"]})[:16]


class ReplayRequestMismatch(ValueError):
    pass


class BoundReplay:
    """Return a saved reply only for its exact saved application-level request."""
    mode = "exact-request offline replay"

    def __init__(self, saved):
        self.bindings = {}
        questions, requests, replies = (saved[key] for key in ("questions", "requests", "model_replies"))
        if len(questions) != len(requests) or len(requests) != len(replies):
            raise ValueError("Every saved request needs one question and reply.")
        for question, messages, reply in zip(questions, requests, replies, strict=True):
            wire = json.loads(json.dumps(messages))
            if not wire or wire[-1][0] != "human" or json.loads(wire[-1][1]).get("question") != question:
                raise ValueError("The saved question does not match its request.")
            key = digest(wire)
            if key in self.bindings:
                raise ValueError("Duplicate saved request binding.")
            self.bindings[key] = (question, wire, copy.deepcopy(reply))

    def generate(self, question, messages):
        wire = json.loads(json.dumps(messages))
        key = digest(wire)
        found = self.bindings.get(key)
        if found is None or found[0] != question or found[1] != wire:
            raise ReplayRequestMismatch("No reply is recorded for this exact question and prompt.")
        return copy.deepcopy(found[2])


def load_runtime(*, empty_index=False):
    record_file = ROOT / "runs/2026-10-22-concept/recorded-run.json"
    corpus_file = ROOT / "data/docs.json"
    raw = record_file.read_bytes()
    saved = json.loads(raw)
    corpus_sha = hashlib.sha256(corpus_file.read_bytes()).hexdigest()
    if corpus_sha != saved["corpus_sha256"]:
        raise ValueError("The corpus differs from the saved embeddings run.")
    prepared = [] if empty_index else chunks()
    descriptor = {"corpus_sha256": corpus_sha, "embedding_model": saved["models"]["qwen3-embedding:0.6b"],
                  "saved_vectors_sha256": digest({doc.page_content: saved["embeddings"]["documents"][doc.page_content] for doc in prepared}),
                  "splitter": {"name": "RecursiveCharacterTextSplitter", "chunk_size": 280, "chunk_overlap": 40},
                  "chunk_ids": [chunk_id(doc) for doc in prepared]}
    identity = {"saved_run_sha256": hashlib.sha256(raw).hexdigest(),
                "corpus_sha256": corpus_sha, "logical_index_id": digest(descriptor),
                "index_descriptor": descriptor, "model_digests": saved["models"]}
    index = InMemoryVectorStore(SavedEmbeddings(saved["embeddings"])) if empty_index else build_index(saved["embeddings"])
    return saved, index, BoundReplay(saved), identity


def trace_request(question, index, adapter, identity, *, events=None):
    events = [] if events is None else events
    if events:
        raise ValueError("Start each request with an empty event list.")
    def emit(kind, **data):
        events.append({"sequence": len(events) + 1, "kind": kind, **data})
    if not isinstance(question, str) or not question.strip():
        emit("request_rejected", reason="blank_question")
        raise ValueError("Ask a nonblank question.")
    request_key = digest({"question": question, "index": identity["logical_index_id"]})
    emit("request_accepted", question=question, request_key=request_key, identity=copy.deepcopy(identity))
    # This is the real maintained vector-store call, using saved real embeddings.
    try:
        ranked = index.similarity_search_with_score(question, k=2)
    except KeyError as error:
        emit("retrieval_refused", reason="unrecorded_query_embedding", error=str(error))
        raise ValueError("No query embedding is saved for this exact question.") from error
    candidates = [{"rank": rank, "chunk_id": chunk_id(doc), "source_id": doc.metadata["id"],
                   "score": float(score), "text": doc.page_content, "url": doc.metadata["url"]}
                  for rank, (doc, score) in enumerate(ranked, start=1)]
    emit("retrieval_completed", candidates=candidates, score_kind="InMemoryVectorStore cosine similarity")
    selected = [doc for doc, _ in ranked]
    emit("context_selected", chunk_ids=[chunk_id(doc) for doc in selected],
         source_ids=[doc.metadata["id"] for doc in selected])
    if not selected:
        emit("model_skipped", reason="empty_context")
        reply = Reply(status="not_in_docs", answer="No documentation was found.", source_ids=[])
    else:
        messages = prompt(question, selected)
        emit("model_request_ready", request_sha256=digest(messages), messages=messages,
             schema=Reply.model_json_schema(), adapter_mode=adapter.mode)
        try:
            raw_reply = adapter.generate(question, messages)
        except ReplayRequestMismatch as error:
            emit("replay_refused", error=str(error))
            raise
        emit("model_reply_returned", reply=copy.deepcopy(raw_reply), mode=adapter.mode)
        try:
            reply = Reply.model_validate(raw_reply)
        except ValueError as error:
            emit("reply_rejected", reason="invalid_shape", error=str(error))
            raise
    try:
        check_reply(reply, selected)
    except ValueError as error:
        emit("reply_rejected", reason="source_contract", error=str(error))
        raise
    emit("reply_checked", status=reply.status, source_ids=reply.source_ids,
         checks=["reply_shape", "source_membership", "status_source_consistency"])
    lookup = {doc.metadata["id"]: doc.metadata["url"] for doc in selected}
    result = {"question": question, "context_ids": [doc.metadata["id"] for doc in selected],
              **reply.model_dump(), "source_links": [lookup[source] for source in reply.source_ids]}
    emit("source_links_resolved", source_links=result["source_links"])
    emit("request_completed", status=reply.status)
    return {"request_key": request_key, "result": result, "events": events}
