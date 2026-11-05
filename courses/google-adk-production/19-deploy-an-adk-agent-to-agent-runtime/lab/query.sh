#!/usr/bin/env bash
# Talk to the deployed docs assistant over the Agent Runtime REST API.
# Usage: PROJECT_ID=... RESOURCE_ID=... ./query.sh
set -euo pipefail
LOCATION_ID=${LOCATION_ID:-us-central1}
URL="https://${LOCATION_ID}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION_ID}/reasoningEngines/${RESOURCE_ID}"
AUTH="Authorization: Bearer $(gcloud auth print-access-token)"

query() {  # query CLASS_METHOD INPUT_JSON: one JSON response
  curl -s -H "$AUTH" -H "Content-Type: application/json" "$URL:query" \
    -d "{\"class_method\": \"$1\", \"input\": $2}"
}
stream() {  # stream USER SESSION MESSAGE: one JSON event per line
  curl -s -H "$AUTH" -H "Content-Type: application/json" "$URL:streamQuery?alt=sse" \
    -d "$(jq -n --arg u "$1" --arg s "$2" --arg m "$3" \
      '{class_method: "async_stream_query", input: {user_id: $u, session_id: $s, message: $m, run_config: {max_llm_calls: 4}}}')"
}
show() {  # print tool calls and the final text of a stream
  jq -r '.content.parts[]? | if .function_call then "call   \(.function_call.name) \(.function_call.args|tojson)"
    elif .function_response then "result \(.function_response.name)"
    elif (.text and (.thought|not)) then "answer \(.text)" else empty end'
}
timed() { local s=$(date +%s); "$@"; echo "# $(( $(date +%s) - s )) s" >&2; }

echo "# 1. Connection check: the methods this deployment serves"
curl -s -H "$AUTH" "$URL" | jq -r '[.spec.classMethods[].name] | join(", ")'

echo; echo "# 2. Conversation 1, in a new session"
S1=$(timed query async_create_session '{"user_id": "dana"}' | jq -r '.output.id')
echo "session $S1"
echo "> I run docuctl 1.x. How do I undo release r42 in production?"
timed stream dana "$S1" "I run docuctl 1.x. How do I undo release r42 in production?" | show

echo; echo "# 3. Add the finished session to Memory Bank"
SESSION=$(query async_get_session "{\"user_id\": \"dana\", \"session_id\": \"$S1\"}" | jq -c '.output')
query async_add_session_to_memory "{\"session\": $SESSION}" | jq -c '.'
for i in $(seq 1 40); do  # memories are extracted in the background
  FOUND=$(query async_search_memory '{"user_id": "dana", "query": "docuctl version"}' | jq -c '[.output.memories[]?.content.parts[0].text]')
  [ "$FOUND" != "[]" ] && break; sleep 5
done
echo "memories after about $(( i * 5 )) s: $FOUND"

echo; echo "# 4. Conversation 2, in another new session"
S2=$(query async_create_session '{"user_id": "dana"}' | jq -r '.output.id')
echo "> How do I undo the last production release?"
timed stream dana "$S2" "How do I undo the last production release?" | show
