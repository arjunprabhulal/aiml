"""The baseline plus the docs pages in its instruction and the input and output checks, on Gemini 2.5 Live."""
import os

from google.adk.agents import Agent

from docs_voice.agent import CORPUS, screen_input, screen_output

root_agent = Agent(name="grounded_voice", model=os.getenv("LIVE_MODEL", "gemini-3.8-live"),
                   instruction=("You are a docs assistant on a voice call. Answer in one or two short sentences, only from "
                                "these pages, and say so when they do not cover the question.\n\n" + CORPUS),
                   before_model_callback=screen_input, after_model_callback=screen_output)
