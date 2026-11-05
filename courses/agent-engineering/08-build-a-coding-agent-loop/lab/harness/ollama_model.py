"""Adapt the Ollama SDK's streaming chat responses to the loop."""
from ollama import Client


class LocalModel:
    def __init__(self, model="gemma4:e2b", host="http://127.0.0.1:11434"):
        self.client = Client(host=host, timeout=120)
        self.model = model

    def __call__(self, messages, tools):
        stream = self.client.chat(model=self.model, messages=messages, tools=tools,
                                  stream=True, think=True, keep_alive=0,
                                  options={"temperature": 0, "seed": 7,
                                           "num_ctx": 8192, "num_predict": 2048})
        try:
            for chunk in stream:
                yield chunk.model_dump(exclude_none=True)
        finally:
            stream.close()
