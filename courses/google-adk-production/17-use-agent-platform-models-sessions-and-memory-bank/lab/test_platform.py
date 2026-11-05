import warnings
warnings.filterwarnings("ignore")
"""Offline SDK/configuration and data-preservation checks; no cloud or model calls."""
import asyncio
import importlib
import os
from types import SimpleNamespace
import unittest
from unittest import mock
os.environ.update(GOOGLE_CLOUD_PROJECT="test-project", GOOGLE_CLOUD_LOCATION="us-central1", AGENT_ENGINE_ID="123")
import create_memory_bank
import delete_memory_bank
import record

class ManagedServices(unittest.TestCase):
    def test_import_does_not_create_a_cloud_instance(self):
        with mock.patch("vertexai.Client") as client:
            importlib.reload(create_memory_bank)
            client.assert_not_called()

    def test_config_includes_the_cli_version_topic(self):
        config = create_memory_bank.memory_config()
        topics = config["context_spec"]["memory_bank_config"]["customization_configs"][0]["memory_topics"]
        self.assertEqual(topics[1]["custom_memory_topic"]["label"], "tool_versions")

    def test_existing_memories_are_not_deleted_for_a_recording(self):
        client = mock.Mock()
        client.agent_engines.memories.list.return_value = [object()]
        with mock.patch("vertexai.Client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "existing memories"):
                asyncio.run(record.require_empty())
        client.agent_engines.memories.delete.assert_not_called()

    def test_existing_sessions_are_not_deleted_for_a_recording(self):
        client = mock.Mock()
        client.agent_engines.memories.list.return_value = []
        sessions = mock.Mock()
        sessions.list_sessions = mock.AsyncMock(return_value=SimpleNamespace(sessions=[object()]))
        with mock.patch("vertexai.Client", return_value=client), mock.patch.object(record, "VertexAiSessionService", return_value=sessions):
            with self.assertRaisesRegex(RuntimeError, "existing sessions"):
                asyncio.run(record.require_empty())
        sessions.delete_session.assert_not_called()

    def test_cleanup_refuses_an_unlabelled_instance(self):
        client = mock.Mock()
        client.agent_engines.get.return_value.api_resource.labels = {}
        with self.assertRaisesRegex(ValueError, "lesson.s label"):
            delete_memory_bank.delete_owned(client, "projects/test/locations/test/reasoningEngines/123")
        client.agent_engines.delete.assert_not_called()

    def test_cleanup_accepts_its_own_label(self):
        client = mock.Mock()
        client.agent_engines.get.return_value.api_resource.labels = {"aiml-lesson": delete_memory_bank.LABEL}
        delete_memory_bank.delete_owned(client, "owned-instance")
        client.agent_engines.delete.assert_called_once_with(name="owned-instance", force=True)

if __name__ == "__main__":
    unittest.main()
