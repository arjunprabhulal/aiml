"""Native ADK app using the same spec, filter and auth as the Python Runner example.

Start ship_api first. ADK loads this package from the enclosing lab directory.
"""
import os
from google.adk.apps import App
from assistant import load_spec, make_agent, release_tools

key = os.environ.get("SHIP_API_KEY")
if not key:
    raise ValueError("Set SHIP_API_KEY to the same local demo key as ship_api before loading release_assistant")
app = App(name="release_assistant", root_agent=make_agent(release_tools(load_spec(), key)))
