"""Create one Agent Runtime instance with no code: it holds Sessions and Memory Bank for the docs assistant."""
import os
import sys

import vertexai

LABEL = "use-agent-platform-models-sessions-and-memory-bank"


def memory_config(managed_topics_only: bool = False) -> dict:
    config = {"display_name": "docs-helper-memory", "labels": {"aiml-lesson": LABEL},
            "context_spec": {"memory_bank_config": {
                "ttl_config": {"default_ttl": "86400s"},
                "customization_configs": [{"memory_topics": [
                    {"managed_memory_topic": {"managed_topic_enum": "USER_PREFERENCES"}},
                    {"custom_memory_topic": {"label": "tool_versions",
                        "description": "Which version of a CLI, SDK or service the developer runs, for example 'runs docuctl 1.x'."}},
                ]}],
            }}}
    if managed_topics_only:
        config["context_spec"]["memory_bank_config"].pop("customization_configs", None)
    return config


def main() -> None:
    client = vertexai.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"],
                             location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    # Reproduce the bounded empty-memory comparison with the explicit optional flag.
    managed_only = sys.argv[1:] == ["--managed-topics-only"]
    if sys.argv[1:] and not managed_only:
        raise SystemExit("Usage: python create_memory_bank.py [--managed-topics-only]")
    engine = client.agent_engines.create(config=memory_config(managed_only))
    print("created", engine.api_resource.name)
    print("agent_engine_id", engine.api_resource.name.split("/")[-1], file=sys.stderr)


if __name__ == "__main__":
    main()
