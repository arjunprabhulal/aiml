"""Deliver a docs-changed event to the agent's trigger endpoints, shaped as Pub/Sub or Eventarc sends it.

Start the server first: TRIGGER_TOKEN=local-dev-token python main.py
Then: TRIGGER_TOKEN=local-dev-token python publish.py pubsub tokens --message-id 1001
      python publish.py eventarc rollback --event-id ev-77
"""
import argparse
import base64
import json
import os

import httpx

BASE_URL = os.environ.get("ADK_URL", "http://127.0.0.1:8767")
APP = "docs_reviewer"
TOKEN = os.environ.get("TRIGGER_TOKEN", "")


def pubsub_body(page: str, message_id: str, raw_data: str | None = None) -> dict:
    """A Pub/Sub push request: the payload is base64 in message.data."""
    data = raw_data if raw_data is not None else base64.b64encode(
        json.dumps({"page": page, "commit": "4f2a9c1"}).encode()).decode()
    return {"message": {"data": data, "attributes": {"repo": "docuctl-docs"}, "messageId": message_id,
                        "publishTime": "2026-10-21T18:00:00Z"},
            "subscription": "projects/docs/subscriptions/docs-changed"}


def eventarc_headers(event_id: str) -> dict:
    """Eventarc binary content mode: CloudEvents attributes travel as ce-* headers."""
    return {"ce-id": event_id, "ce-type": "google.cloud.pubsub.topic.v1.messagePublished",
            "ce-source": "//pubsub.googleapis.com/projects/docs/topics/docs-changed", "ce-specversion": "1.0"}


def deliver(client: httpx.Client, source: str, page: str, event_id: str, raw_data: str | None = None,
            token: str | None = None) -> httpx.Response:
    body = pubsub_body(page, event_id, raw_data)
    auth = {"Authorization": f"Bearer {TOKEN if token is None else token}"}
    if source == "pubsub":
        return client.post(f"/apps/{APP}/trigger/pubsub", json=body, headers=auth)
    return client.post(f"/apps/{APP}/trigger/eventarc", json={"message": body["message"]},
                       headers={**auth, **eventarc_headers(event_id)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=["pubsub", "eventarc"])
    parser.add_argument("page")
    parser.add_argument("--message-id", "--event-id", dest="event_id", default="1001")
    parser.add_argument("--raw-data", help="send this string as message.data instead of base64 JSON")
    args = parser.parse_args()
    with httpx.Client(base_url=BASE_URL, timeout=120) as client:
        r = deliver(client, args.source, args.page, args.event_id, args.raw_data)
    print(f"HTTP {r.status_code} {r.text}")


if __name__ == "__main__":
    main()
