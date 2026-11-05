"""Docs assistant: a LangChain agent on Gemini that searches the tracker docs and looks up issues.
Set DOCS_MODEL=gemma4:e2b and DOCS_EMBEDDER=qwen3-embedding:0.6b to run it on a local Ollama server."""
import json
import os
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_core.vectorstores import InMemoryVectorStore

HERE = Path(__file__).parent
CHAT_MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
EMBED_MODEL = os.environ.get("DOCS_EMBEDDER", "gemini-embedding-2")
K = 3
PROMPT = """You answer questions about `tracker`, an open-source task-tracker CLI.
Use search_docs for questions about how tracker works and get_issue for a numbered issue.
Answer only from what the tools return, in at most three sentences.
If a message needs no lookup, reply without calling a tool."""


def models():
    if CHAT_MODEL.startswith("gemini"):
        from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
        return (ChatGoogleGenerativeAI(model=CHAT_MODEL, thinking_level="low"),
                GoogleGenerativeAIEmbeddings(model=EMBED_MODEL))
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    return ChatOllama(model=CHAT_MODEL, temperature=0, reasoning=False), OllamaEmbeddings(model=EMBED_MODEL)


def build_agent(docs: list[dict], issues: dict):
    chat, embeddings = models()
    store = InMemoryVectorStore.from_documents(
        [Document(page_content=f"{d['title']}\n{d['text']}", id=d["id"]) for d in docs], embeddings)

    @tool
    def search_docs(query: str) -> str:
        """Search the tracker documentation and return the three closest pages."""
        return json.dumps([{"id": d.id, "text": d.page_content} for d in store.similarity_search(query, k=K)])

    @tool
    def get_issue(number: int) -> str:
        """Look up a tracker GitHub issue by number: its title, state and the version that fixed it."""
        issue = issues.get(str(number))
        return json.dumps({"number": number, **issue}) if issue else f"issue {number} does not exist"

    return create_agent(chat, tools=[search_docs, get_issue], system_prompt=PROMPT)


def run(agent, question: str) -> dict:
    """Run one question and keep the trajectory the evaluation needs."""
    messages = agent.invoke({"messages": [{"role": "user", "content": question}]})["messages"]
    calls = [{"name": c["name"], "args": c["args"]} for m in messages if isinstance(m, AIMessage) for c in m.tool_calls]
    outputs = [{"tool": m.name, "content": m.content} for m in messages if isinstance(m, ToolMessage)]
    retrieved = [d["id"] for o in outputs if o["tool"] == "search_docs" for d in json.loads(o["content"])]
    return {"answer": messages[-1].text, "tool_calls": calls, "tool_outputs": outputs, "retrieved": retrieved}


if __name__ == "__main__":
    import sys
    agent = build_agent(json.loads((HERE / "docs.json").read_text()), json.loads((HERE / "issues.json").read_text()))
    print(json.dumps(run(agent, sys.argv[1]), indent=2))
