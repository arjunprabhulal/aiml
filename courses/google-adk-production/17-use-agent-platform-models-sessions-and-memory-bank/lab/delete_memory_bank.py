"""Delete only an instance carrying this lesson's ownership label."""
import os
import sys
import vertexai

LABEL = "use-agent-platform-models-sessions-and-memory-bank"


def delete_owned(client, name: str) -> None:
    engine = client.agent_engines.get(name=name)
    if (engine.api_resource.labels or {}).get("aiml-lesson") != LABEL:
        raise ValueError("Refusing to delete an instance without this lesson's label")
    client.agent_engines.delete(name=name, force=True)


def main() -> None:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    name = f"projects/{project}/locations/{location}/reasoningEngines/{sys.argv[1]}"
    delete_owned(vertexai.Client(project=project, location=location), name)
    print("deleted", name)


if __name__ == "__main__":
    main()
