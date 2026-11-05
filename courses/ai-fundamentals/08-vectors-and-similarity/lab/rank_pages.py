"""Embed the docuctl docs pages and rank them against questions by cosine similarity. Run: python rank_pages.py"""
import json
from pathlib import Path

import numpy as np
import ollama

MODEL = "qwen3-embedding:0.6b"
HERE = Path(__file__).parent
PAGES = {page.name: page.read_text() for page in sorted((HERE / "docs").glob("*.md"))}
QUERIES = ["how do I undo a bad deploy", "where should the CI credential live", "what replaced release revert"]


def embed(client: ollama.Client, texts: list[str], model: str = MODEL) -> np.ndarray:
    return np.array(client.embed(model=model, input=texts).embeddings)


def cosine(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of one vector against each row: dot product of unit-length vectors."""
    return matrix @ query / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(query))


def rank(query_vector: np.ndarray, page_vectors: np.ndarray, names: list[str]) -> list[tuple[str, float]]:
    scores = cosine(query_vector, page_vectors)
    return sorted(zip(names, scores.round(3).tolist()), key=lambda item: -item[1])


def main() -> None:
    client = ollama.Client()
    names = list(PAGES)
    pages = embed(client, list(PAGES.values()))
    queries = embed(client, QUERIES)
    print(f"{len(names)} pages, {pages.shape[1]} dimensions per vector")
    results = {}
    for query, vector in zip(QUERIES, queries):
        results[query] = rank(vector, pages, names)
        print(f"\n{query!r}")
        for name, score in results[query]:
            print(f"  {score:.3f}  {name}")
    output = HERE / "runs/local-docuctl"
    output.mkdir(parents=True, exist_ok=True)
    (output / "rankings.json").write_text(json.dumps({"model": MODEL, "rankings": results}, indent=1) + "\n")
    np.save(output / "page-vectors.npy", pages)


if __name__ == "__main__":
    main()
