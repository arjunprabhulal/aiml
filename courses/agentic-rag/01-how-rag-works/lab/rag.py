"""Run the recorded RAG refresher without a model server."""
from agentic_rag.concepts import replay

for result in replay():
    print("Question:",result["question"])
    print("Retrieved:",", ".join(result["context_ids"]))
    print("Status:",result["status"])
    print("Answer:",result["answer"])
    print("Sources:",", ".join(result["source_links"])or"(none)")
    print()
