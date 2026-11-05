# Log sink to route GenAI telemetry logs directly to BigQuery
resource "google_logging_project_sink" "genai_logs_to_bq" {
  name        = "${var.project_name}-genai-logs"
  project     = var.project_id
  destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.telemetry_dataset.dataset_id}"
  filter      = "labels.\"event.name\"=\"gen_ai.client.inference.operation.details\" AND (labels.\"gen_ai.input.messages_ref\" =~ \".*${var.project_name}.*\" OR labels.\"gen_ai.output.messages_ref\" =~ \".*${var.project_name}.*\")"

  unique_writer_identity = true

  bigquery_options {
    use_partitioned_tables = true
  }
}

# External table for completions data (messages/parts) stored in GCS
resource "google_bigquery_table" "completions_external_table" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.telemetry_dataset.dataset_id
  table_id   = "completions"

  external_data_configuration {
    autodetect    = false
    source_format = "NEWLINE_DELIMITED_JSON"
    source_uris   = ["gs://${google_storage_bucket.logs_data_bucket.name}/completions/*"]
    connection_id = google_bigquery_connection.genai_telemetry_connection.name
  }
}

# Pre-create the log export table so completions_view works on first deploy
resource "google_bigquery_table" "genai_logs_table" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.telemetry_dataset.dataset_id
  table_id   = "gen_ai_client_inference_operation_details"

  time_partitioning {
    type  = "DAY"
    field = "timestamp"
  }

  schema = file("${path.module}/../shared/genai_logs_schema.json")

  lifecycle {
    ignore_changes = [schema]
  }
}
