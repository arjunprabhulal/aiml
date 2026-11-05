"""The retrieval service: a separate process that searches an index snapshot over HTTP.

    python3 retrieval_service.py --corpus corpus.json --spans spans.jsonl [--index current] [--derived-ids]

It listens on 127.0.0.1 on a port the operating system chooses and prints that port
on its first line. POST /search takes {"query": ..., "k": ...} and returns the top k
passages, each with its document ID, the document version the index was built from,
the SHA-256 of the passage text, its rank and its TF-IDF cosine score (from the
retriever build, retrieve.py). If the request carries a valid traceparent header,
the service's span joins the caller's trace; otherwise it starts a new trace.
The service exports its spans to its own file. Standard library only.
"""
import argparse
import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import retrieve
from tracing import DerivedIds, JsonLinesExporter, RandomIds, Tracer

DATA_SOURCE = "support-docs"


def load_index(path, which="index_snapshot"):
    """Passages as the index holds them: one version of every document.

    index_snapshot is the index as it was built, before the refund policy changed;
    current is the index rebuilt from the current document versions.
    """
    corpus = json.loads(Path(path).read_text(encoding="utf-8"))
    passages = []
    for doc_id, version in corpus[which].items():
        document = corpus["documents"][doc_id]
        text = f"{document['title']}. {document['versions'][version]}"
        passages.append({"id": doc_id, "version": int(version), "text": text,
                         "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    return passages


def search(passages, query, k):
    ranked = retrieve.rank(query, [p["text"] for p in passages])
    by_text = {p["text"]: p for p in passages}
    return [dict(by_text[text], rank=i + 1, score=round(score, 6)) for i, (score, text) in enumerate(ranked[:k])]


def make_handler(passages, exporter, derived_ids):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            incoming = self.headers.get("traceparent")
            # Reproducible fixtures derive span IDs from the incoming header; real use is random.
            ids = DerivedIds(f"retrieval:{incoming}") if derived_ids else RandomIds()
            tracer = Tracer("retrieval", exporter, ids=ids)
            with tracer.span(f"retrieval {DATA_SOURCE}", traceparent=incoming, **{
                    "gen_ai.operation.name": "retrieval", "gen_ai.data_source.id": DATA_SOURCE}) as span:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                found = search(passages, body["query"], body["k"])
                span.set(**{"gen_ai.retrieval.top_k": body["k"],
                            # IDs, versions and hashes only; the passage text stays out of telemetry.
                            "app.retrieval.passages": [{key: p[key] for key in ("id", "version", "sha256", "rank", "score")}
                                                       for p in found]})
            payload = json.dumps({"passages": found}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # keep stdout for the port line only
            pass

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--spans", required=True)
    parser.add_argument("--index", choices=["index_snapshot", "current"], default="index_snapshot")
    parser.add_argument("--derived-ids", action="store_true", help="reproducible span IDs for fixtures")
    options = parser.parse_args(argv)
    server = HTTPServer(("127.0.0.1", 0), make_handler(load_index(options.corpus, options.index),
                                                       JsonLinesExporter(options.spans), options.derived_ids))
    print(server.server_address[1], flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
