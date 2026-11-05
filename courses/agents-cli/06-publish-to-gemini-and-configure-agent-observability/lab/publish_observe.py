"""Gemini registration resolver and two-tier observability validator for agents-cli."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def get_discovery_engine_endpoint(location: str) -> str:
    """Return the regional or global Discovery Engine endpoint (mirrors cmd_publish.py)."""
    if location == "global":
        return "https://discoveryengine.googleapis.com"
    return f"https://{location}-discoveryengine.googleapis.com"


def select_card_auth_token_type(agent_card_url: str) -> str:
    """Select access_token for *.googleapis.com and audience_id_token for Cloud Run / external URLs."""
    parsed = urlparse(agent_card_url)
    hostname = parsed.hostname or ""
    if hostname.endswith(".googleapis.com"):
        return "access_token"
    return "audience_id_token"


def resolve_publish_gemini_request(
    *,
    registration_type: str | None,
    gemini_app_id: str | None,
    agent_runtime_id: str | None = None,
    agent_card_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Validate programmatic `agents-cli publish gemini` arguments and build registration config."""
    if not registration_type and metadata:
        if metadata.get("is_a2a"):
            registration_type = "a2a"
        elif metadata.get("remote_agent_runtime_id"):
            registration_type = "adk"

    if not registration_type:
        raise ValueError(
            "--registration-type is required in programmatic mode. Rerun with one of:\n"
            "  --registration-type <a2a|adk>  a2a needs --agent-card-url, adk needs --agent-runtime-id\n"
            "  -i, --interactive              be prompted for each missing value"
        )

    if not gemini_app_id:
        raise ValueError("--gemini-app-id is required in programmatic mode.")

    parts = gemini_app_id.split("/")
    if len(parts) != 8 or parts[0] != "projects" or parts[2] != "locations" or parts[6] != "engines":
        raise ValueError(
            f"Invalid --gemini-app-id {gemini_app_id!r}; expected "
            "projects/<number>/locations/<location>/collections/<collection>/engines/<engine_id>."
        )
    location = parts[3]
    endpoint = get_discovery_engine_endpoint(location)

    if registration_type == "adk":
        runtime_id = agent_runtime_id or (metadata or {}).get("remote_agent_runtime_id")
        if not runtime_id:
            raise ValueError("ADK registration requires --agent-runtime-id or deployment_metadata.json.")
        return {
            "registration_type": "adk",
            "discovery_engine_endpoint": endpoint,
            "target_resource": runtime_id,
            "protocol": "streamQuery",
        }

    if registration_type == "a2a":
        card_url = agent_card_url
        if not card_url and metadata and metadata.get("remote_agent_runtime_id"):
            rt = metadata["remote_agent_runtime_id"]
            rt_parts = rt.split("/")
            rt_region = rt_parts[3]
            card_url = f"https://{rt_region}-aiplatform.googleapis.com/v1beta1/{rt}/a2a/v1/card"
        if not card_url:
            raise ValueError("A2A registration requires --agent-card-url or A2A deployment_metadata.json.")
        return {
            "registration_type": "a2a",
            "discovery_engine_endpoint": endpoint,
            "agent_card_url": card_url,
            "card_auth_token_type": select_card_auth_token_type(card_url),
            "protocol": "JSONRPC",
        }

    raise ValueError(f"Unsupported registration_type: {registration_type!r}")


def validate_observability_env(env: dict[str, str]) -> dict[str, Any]:
    """Validate the two-tier OpenTelemetry + GCS/BigQuery completions configuration."""
    span_capture = env.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "NO_CONTENT")
    adk_span_capture = env.get("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "true").lower() == "true"
    hook = env.get("OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK", "")
    bucket = env.get("LOGS_BUCKET_NAME", "").strip()
    upload_path = env.get("OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH", "").strip()

    if hook == "upload" and (not bucket or not upload_path.startswith("gs://")):
        raise ValueError(
            "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK='upload' requires LOGS_BUCKET_NAME "
            "and a gs:// OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH; otherwise prompt/response "
            "JSONL payloads are dropped while spans record NO_CONTENT."
        )

    return {
        "spans_include_message_content": (span_capture != "NO_CONTENT") or adk_span_capture,
        "gcs_completion_upload_enabled": hook == "upload" and bool(bucket),
        "upload_base_path": upload_path,
        "bigquery_join_table": "completions_view",
    }
