#!/usr/bin/env bash
# Delete the deployment. force=true also deletes its sessions and Memory Bank memories.
set -euo pipefail
LOCATION_ID=${LOCATION_ID:-us-central1}
curl -s -X DELETE -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://${LOCATION_ID}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION_ID}/reasoningEngines/${RESOURCE_ID}?force=true" \
  | jq '{name: (.name | sub("projects/[0-9]+/"; "projects/PROJECT_NUMBER/")), done: (.done // false)}'
