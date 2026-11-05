#!/usr/bin/env bash
# Call the private Cloud Run service. Usage: SERVICE_URL=https://... ./request.sh "message"
set -euo pipefail
APP=docs_helper USER_ID=dana
TOKEN=$(gcloud auth print-identity-token)
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT
call() { curl --fail-with-body -sS -o "$BODY" -w "HTTP %{http_code} in %{time_total} s\n" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" "$@"; }

SESSION=${SESSION:-}
if [ -z "$SESSION" ]; then
  if ! call -X POST "$SERVICE_URL/apps/$APP/users/$USER_ID/sessions"; then cat "$BODY"; exit 1; fi
  SESSION=$(jq -r .id "$BODY"); echo "session $SESSION"
fi
if ! call "$SERVICE_URL/run" -d "$(jq -n --arg a $APP --arg u $USER_ID --arg s "$SESSION" --arg m "$1" \
  '{app_name: $a, user_id: $u, session_id: $s, run_config: {max_llm_calls: 4}, new_message: {role: "user", parts: [{text: $m}]}}')"; then cat "$BODY"; exit 1; fi
jq -r 'if type == "array" then .[] | .content.parts[]? |
    if .functionCall then "call   \(.functionCall.name) \(.functionCall.args|tojson)"
    elif .functionResponse then "result \(.functionResponse.name)"
    elif (.text and (.thought|not)) then "answer \(.text)" else empty end
  else . end' "$BODY"
