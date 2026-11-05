#!/usr/bin/env bash
# Two requests the deployed agent rejects. Usage: PROJECT_ID=... RESOURCE_ID=... ./failures.sh
set -uo pipefail
LOCATION_ID=${LOCATION_ID:-us-central1}
URL="https://${LOCATION_ID}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION_ID}/reasoningEngines/${RESOURCE_ID}"
AUTH="Authorization: Bearer $(gcloud auth print-access-token)"
post() { curl -s -H "$AUTH" -H "Content-Type: application/json" "$@"; }

echo "# 1. A streaming method sent to :query"
S=$(post "$URL:query" -d '{"class_method": "async_create_session", "input": {"user_id": "dana"}}' | jq -r '.output.id')
post "$URL:query" -d "{\"class_method\": \"async_stream_query\", \"input\": {\"user_id\": \"dana\", \"session_id\": \"$S\", \"message\": \"hi\"}}" | jq -c '.error // .'

echo; echo "# 2. Dana's session id sent with another user id"
post "$URL:streamQuery?alt=sse" -d "{\"class_method\": \"async_stream_query\", \"input\": {\"user_id\": \"lee\", \"session_id\": \"$S\", \"message\": \"What did I ask before?\"}}" | head -c 600; echo
