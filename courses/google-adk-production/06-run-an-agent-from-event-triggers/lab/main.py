"""Serve the docs reviewer with Pub/Sub and Eventarc trigger endpoints on this machine.

Run from this folder: TRIGGER_TOKEN=local-dev-token python main.py
ADK 2.12 refuses trigger endpoints without an authentication check. In Google Cloud that check is
--trigger_oidc_audience (Google-signed OIDC tokens); here it is a shared bearer token for local work.
"""
import hmac
import os
from pathlib import Path

import uvicorn
from fastapi import HTTPException, Request
from google.adk.cli.fast_api import get_fast_api_app

AGENTS_DIR = str(Path(__file__).resolve().parent)
TOKEN = os.environ.get("TRIGGER_TOKEN", "")


def verify_shared_token(request: Request) -> None:
    """Runs before every /apps/{app}/trigger/* request; raising rejects the delivery."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if not TOKEN or scheme.lower() != "bearer" or not hmac.compare_digest(token, TOKEN):
        raise HTTPException(status_code=401, detail="Missing or wrong trigger token.")


app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    web=False,
    session_service_uri=os.environ.get("SESSION_SERVICE_URI", "memory://"),
    trigger_sources=["pubsub", "eventarc"],
    trigger_auth_verifier=verify_shared_token,
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8767")))
