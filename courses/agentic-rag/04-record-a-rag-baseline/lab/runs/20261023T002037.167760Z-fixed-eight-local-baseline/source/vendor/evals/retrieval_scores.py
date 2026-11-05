def retrieval_scores(retrieved: list[str], expected: list[str]) -> dict | None:
    if not expected:
        return None
    ranks = [retrieved.index(doc) + 1 for doc in expected if doc in retrieved]
    return {"hit": bool(ranks), "recall": len(ranks) / len(expected),
            "reciprocal_rank": 1 / min(ranks) if ranks else 0.0}
