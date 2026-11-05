"""The same voice assistant without the docs pages, tools or checks: the baseline the eval must fail."""
import os

from google.adk.agents import Agent

root_agent = Agent(name="bare_voice", model=os.getenv("LIVE_MODEL", "gemini-3.8-live"),
                   instruction="You are a docs assistant on a voice call. Answer in one or two short sentences.")
