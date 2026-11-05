"""A slow local docs host: every page takes a second to serve, like a busy wiki or a remote API.

Run: uvicorn docs_server:app --port 8770
Each request records when it started and finished, so overlap between tool calls is measurable.
"""
import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException

HERE = Path(__file__).resolve().parent
DELAY_SECONDS = 1.0
app = FastAPI(title="docs host")
SERVED: list[dict] = []


@app.get("/pages/{page}")
async def page(page: str):
    path = HERE / "docs" / f"{page}.md"
    start = time.perf_counter()
    await asyncio.sleep(DELAY_SECONDS)  # the server is slow; the client should not wait for one page at a time
    SERVED.append({"page": page, "start": start, "end": time.perf_counter()})
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no page {page}")
    return {"page": page, "text": path.read_text(encoding="utf-8")}
