from collections import Counter
from math import log, sqrt
import re

DOCUMENTS = [
    "Retrieval finds relevant documents for a query.",
    "Training updates model weights using examples and a loss.",
    "Quantization stores model weights with fewer bits to reduce memory.",
]

def tokens(text):
    return re.findall(r"[a-z]+", text.lower())

def rank(query, documents):
    if not documents:
        return []
    counts = [Counter(tokens(doc)) for doc in documents]
    vocabulary = sorted(set().union(*(set(c) for c in counts)))
    idf = {
        term: log((1 + len(documents)) /
                  (1 + sum(term in c for c in counts))) + 1
        for term in vocabulary
    }

    def vector(count):
        return [count[term] * idf[term] for term in vocabulary]

    def cosine(a, b):
        numerator = sum(x * y for x, y in zip(a, b))
        denominator = sqrt(sum(x*x for x in a) * sum(y*y for y in b))
        return numerator / denominator if denominator else 0.0

    q = vector(Counter(tokens(query)))
    scores = [(cosine(q, vector(c)), doc)
              for c, doc in zip(counts, documents)]
    return sorted(scores, key=lambda pair: pair[0], reverse=True)

if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) or "retrieval documents query"
    for score, document in rank(query, DOCUMENTS):
        print(f"{score:.3f}  {document}")
