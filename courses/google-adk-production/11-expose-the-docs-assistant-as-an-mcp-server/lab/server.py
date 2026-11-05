"""The docs assistant as an MCP server: any MCP client can ask it docuctl questions.

Run over stdio (a local client starts this process):   python server.py
Run over Streamable HTTP (a networked client connects): python server.py http
to_mcp_server registers one MCP tool that runs the whole agent and returns its final answer.
"""
import os
import sys
from pathlib import Path

from google.adk import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import to_mcp_server
from google.genai import types

HERE = Path(__file__).resolve().parent
# Gemini through ADK's native client; set DOCS_MODEL=ollama_chat/gemma4:e2b to run Gemma locally.
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
PAGES = sorted(p.stem for p in (HERE / "docs").glob("*.md"))


def read_page(page: str) -> dict:
    """Read one page of the docuctl manual, such as rollback, hooks, secrets or upgrade-2x."""
    if page not in PAGES:
        return {"error": f"No page {page!r}. Pages: {', '.join(PAGES)}."}
    return {"page": page, "text": (HERE / "docs" / f"{page}.md").read_text(encoding="utf-8")}


root_agent = Agent(
    name="docuctl_docs",
    # The description becomes the MCP tool description: it is how a client's model decides to call it.
    description="Answer a question about docuctl, the team's deploy CLI, from its manual. "
                "Pass the full question; follow-up questions on the same connection keep the context.",
    model=LiteLlm(model=MODEL) if MODEL.startswith("ollama_chat/") else MODEL,
    instruction=f"""You answer questions about docuctl from its manual. Pages: {', '.join(PAGES)}.
Read the relevant page with read_page before you answer, and name the exact command.
If the developer said which docuctl version they use, answer for that version. Keep answers under 80 words.""",
    tools=[read_page],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
)

mcp_server = to_mcp_server(root_agent, instructions="Ask docuctl questions in plain English.")

if __name__ == "__main__":
    # stdout carries the protocol on stdio: never print to it; log to stderr instead.
    mcp_server.run(transport="streamable-http" if sys.argv[1:] == ["http"] else "stdio")
