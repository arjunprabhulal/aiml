"""Native ADK entry point for the async tool; the thread-pool experiment uses RunConfig in assistant.py."""
from assistant import make_agent
root_agent = make_agent()
