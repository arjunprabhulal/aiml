"""What each side fails with when its precondition is missing. Run: python failures.py"""
import os

import ollama

from ask_both import QUESTION, ask_hosted

try:  # the hosted API needs a key on every request
    os.environ.pop("GOOGLE_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    ask_hosted(QUESTION)
except ValueError as error:
    print("hosted, no API key ->", type(error).__name__, error)

try:  # the local API is a server on this machine; nothing answers if it is not running
    ollama.Client(host="http://127.0.0.1:11435").chat(model="gemma4:e2b", messages=[{"role": "user", "content": QUESTION}])
except ConnectionError as error:
    print("local, server not running ->", type(error).__name__, str(error).splitlines()[0])
