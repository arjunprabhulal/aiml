"""Two ways similarity search misleads you. Run: python failures.py (after rank_pages.py)"""
import numpy as np
import ollama

from rank_pages import HERE, PAGES, embed, rank

client = ollama.Client()
pages = np.load(HERE / "page-vectors.npy")
names = list(PAGES)

# 1. The query must be embedded exactly as the pages were: same model, same settings.
try:
    other = np.array(client.embed(model="qwen3-embedding:0.6b", input=["how do I undo a bad deploy"], dimensions=512).embeddings[0])
    print(f"1. query embedded with dimensions=512: {other.shape[0]} values, pages have {pages.shape[1]}")
    rank(other, pages, names)
except ValueError as error:
    print("   ->", type(error).__name__, str(error).splitlines()[0][:100])
try:
    client.embed(model="qwen3.5:0.8b", input=["how do I undo a bad deploy"])
except ollama.ResponseError as error:
    print("1b. a chat model as the embedder ->", error.status_code, error.error)

# 2. Every query gets a top page, even one the docs cannot answer.
for query in ["what is the capital of France", "how do I pin a Python dependency"]:
    best = rank(embed(client, [query])[0], pages, names)[0]
    print(f"2. {query!r} -> top page {best[0]} at {best[1]:.3f}")
