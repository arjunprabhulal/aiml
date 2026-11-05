#!/usr/bin/env bash
# Create the lesson dataset (two tables, 1.5 KB of CSV) in your project. Load jobs are free.
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
DATASET="${DOCS_ANALYTICS_DATASET:-aiml_docs_analytics}"
LABEL="aiml-lesson:query-bigquery-with-bigquerytoolset"
bq --project_id="${PROJECT}" mk --dataset --location=US --label="${LABEL}" "${PROJECT}:${DATASET}"
bq --project_id="${PROJECT}" load --source_format=CSV --skip_leading_rows=1 \
  "${PROJECT}:${DATASET}.page_views" data/page_views.csv day:DATE,page:STRING,views:INT64,avg_seconds:INT64
bq --project_id="${PROJECT}" load --source_format=CSV --skip_leading_rows=1 \
  "${PROJECT}:${DATASET}.search_queries" data/search_queries.csv week:DATE,query:STRING,results:INT64,searches:INT64
for table in page_views search_queries; do
  bq --project_id="${PROJECT}" update --set_label="${LABEL}" "${PROJECT}:${DATASET}.${table}"
done
bq --project_id="${PROJECT}" ls "${PROJECT}:${DATASET}"
