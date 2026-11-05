import warnings
warnings.filterwarnings("ignore")
"""Local tool/configuration checks; remote deployment results are saved recordings."""
import json
import asyncio
from vertexai.agent_engines.templates.adk import AdkApp
from google.adk.sessions import InMemorySessionService
from pathlib import Path
import unittest
from docs_helper.agent import read_page, root_agent
HERE=Path(__file__).resolve().parent

class RuntimeConfiguration(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")

    def test_read_page_rejects_a_path_outside_the_docs(self):
        self.assertIn('error',read_page('../agent'))

    def test_streaming_method_is_registered_on_the_stream_surface(self):
        runtime=AdkApp(agent=root_agent)
        operations=runtime.register_operations()
        self.assertIn('async_stream_query',operations['async_stream'])
        self.assertNotIn('async_stream_query',operations['async'])

    def test_a_missing_user_session_does_not_return_another_users_history(self):
        runtime=AdkApp(agent=root_agent)
        runtime._tmpl_attrs['session_service']=InMemorySessionService()
        with self.assertRaisesRegex(RuntimeError,'Session not found'):
            asyncio.run(runtime.async_get_session(user_id='lee',session_id='missing'))

    def test_deployment_resource_limits_are_explicit(self):
        config=json.loads((HERE/'docs_helper/.agent_engine_config.json').read_text())
        self.assertEqual(config['max_instances'],1)
        self.assertEqual(config['resource_limits'],{'cpu':'1','memory':'1Gi'})

    def test_model_and_regional_services_can_use_different_locations(self):
        self.assertEqual(root_agent.model.client_kwargs['location'],'global')

if __name__ == '__main__':
    unittest.main()
