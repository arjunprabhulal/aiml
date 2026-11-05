"""A local stand-in for the docuctl release API: FastAPI, an API key header, and its own OpenAPI spec.

Run: SHIP_API_KEY=... uvicorn ship_api:app --port 8766
The spec is served at /openapi.json; every request is logged with its X-Request-ID.
"""
import os
import secrets
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

app = FastAPI(title="docuctl release API", version="2.4.0")
api_key = APIKeyHeader(name="X-Ship-Key", auto_error=False)
REQUESTS: list[dict] = []  # what the server saw, for the recording and the tests

RELEASES = {
    "staging": [
        {"release": "r43", "status": "failed", "commit": "0be77c3", "reason": "health check failed"},
        {"release": "r42", "status": "failed", "commit": "d41e9a7", "reason": "pre_deploy exited 1"},
        {"release": "r41", "status": "live", "commit": "8c1f2e0", "reason": None},
    ],
    "production": [
        {"release": "r40", "status": "live", "commit": "5e2a913", "reason": None},
        {"release": "r39", "status": "previous", "commit": "77d0c41", "reason": None},
    ],
}


class Release(BaseModel):
    release: str
    status: Literal["live", "previous", "degraded", "failed", "pending"]
    commit: str
    reason: str | None


class Rollback(BaseModel):
    to: str


def check_key(request: Request, key: str | None = Security(api_key)) -> None:
    REQUESTS.append({"method": request.method, "path": request.url.path,
                     "request_id": request.headers.get("x-request-id"), "key_sent": key is not None})
    if key is None or not secrets.compare_digest(key, os.environ["SHIP_API_KEY"]):
        raise HTTPException(status_code=401, detail="missing or invalid X-Ship-Key")


@app.get("/envs/{env}/releases", operation_id="listReleases", response_model=list[Release],
         dependencies=[Depends(check_key)])
def list_releases(env: Literal["staging", "production"], status: str | None = None):
    """List the releases of one environment, newest first. Filter by status, such as failed."""
    return [r for r in RELEASES[env] if status is None or r["status"] == status]


@app.get("/releases/{release}", operation_id="getRelease", response_model=Release,
         dependencies=[Depends(check_key)])
def get_release(release: str):
    """Show one release: its status, commit and failure reason."""
    for env in RELEASES.values():
        for r in env:
            if r["release"] == release:
                return r
    raise HTTPException(status_code=404, detail=f"no release {release}")


@app.post("/envs/{env}/rollback", operation_id="rollbackEnvironment", response_model=Release,
          dependencies=[Depends(check_key)])
def rollback(env: Literal["staging", "production"], body: Rollback):
    """Move an environment back to an earlier release."""
    raise HTTPException(status_code=403, detail="this key may not roll back")
