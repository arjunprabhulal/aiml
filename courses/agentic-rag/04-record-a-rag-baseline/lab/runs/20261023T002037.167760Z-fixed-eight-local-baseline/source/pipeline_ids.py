"""Unchanged application ID functions from Build a RAG Pipeline."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def chunk_id(doc):
    return doc.metadata["id"] + ":" + digest({"text": doc.page_content, "url": doc.metadata["url"]})[:16]
