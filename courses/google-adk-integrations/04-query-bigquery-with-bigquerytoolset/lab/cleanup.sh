#!/usr/bin/env bash
# Delete the lesson dataset and both tables, then show that it is gone.
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
DATASET="${DOCS_ANALYTICS_DATASET:-aiml_docs_analytics}"
bq --project_id="${PROJECT}" rm -r -f -d "${PROJECT}:${DATASET}"
bq --project_id="${PROJECT}" show "${PROJECT}:${DATASET}" 2>&1 | grep -o "Not found: Dataset" || exit 1
