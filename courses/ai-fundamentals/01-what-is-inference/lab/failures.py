"""Two ways inference goes wrong in practice. Run: python failures.py"""
import ollama

from inference import QUESTION, ask

client = ollama.Client()

# 1. The weights know nothing about docuctl, so the model answers anyway, from patterns.
print("1. no docs, three seeds:")
for seed in (1, 2, 3):
    reply = client.chat(model="gemma4:e2b", messages=[{"role": "user", "content": QUESTION}],
                        think=False, options={"temperature": 0.8, "seed": seed})
    print("  ", reply.message.content.strip().split(". ")[0].rstrip(".") + ".")

# 2. Inference needs the weight file on this machine; a tag that was never pulled fails.
print("2. a model that is not pulled:")
try:
    ask(client, QUESTION, model="gemma4:e4b")
except ollama.ResponseError as error:
    print("   ResponseError", error.status_code, error.error)
