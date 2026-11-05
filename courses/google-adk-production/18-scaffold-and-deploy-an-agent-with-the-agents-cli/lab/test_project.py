import warnings
warnings.filterwarnings("ignore")
"""Check the downloaded project and installed CLI flags offline."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
HERE=Path(__file__).resolve().parent

class ScaffoldProject(unittest.TestCase):
    def test_model_call_budget_stops_before_the_fifth_request(self):
        from types import SimpleNamespace
        from docs_helper.agent import bounded_model_calls
        context=SimpleNamespace(state={},invocation_id="one")
        for _ in range(4):self.assertIsNone(bounded_model_calls(context,None))
        self.assertIsNotNone(bounded_model_calls(context,None))
        self.assertEqual(context.state["temp:model_call_budget"]["calls"],4)

    def test_a_new_invocation_has_its_own_call_budget(self):
        from types import SimpleNamespace
        from docs_helper.agent import bounded_model_calls
        context=SimpleNamespace(state={},invocation_id="one")
        for _ in range(4):bounded_model_calls(context,None)
        context.invocation_id="two"
        self.assertIsNone(bounded_model_calls(context,None))
        self.assertEqual(context.state["temp:model_call_budget"]["calls"],1)

    def test_manifest_selects_agent_runtime_and_the_existing_agent(self):
        config=yaml.safe_load((HERE/'agents-cli-manifest.yaml').read_text())
        self.assertEqual(config['create_params']['deployment_target'],'agent_runtime')
        self.assertEqual(config['agent_directory'],'docs_helper')
        self.assertTrue((HERE/config['agent_directory']/'agent.py').is_file())

    def test_download_does_not_target_the_recorded_deleted_deployment(self):
        self.assertFalse((HERE/'deployment_metadata.json').exists())

    def test_conflicting_preview_flags_report_an_error_even_with_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=subprocess.run(['agents-cli','scaffold','enhance','--dry-run','--force','--skip-checks','--auto-approve'],cwd=tmp,capture_output=True,text=True)
        self.assertEqual(result.returncode,0)
        self.assertIn('--dry-run is not compatible with --force mode',result.stdout)

    def test_documented_limits_and_identity_flags_exist(self):
        result=subprocess.run(['agents-cli','deploy','--help'],capture_output=True,text=True,check=True)
        for flag in ['--no-agent-identity','--max-instances','--memory','--region','--dry-run']:
            self.assertIn(flag,result.stdout)

if __name__ == '__main__':
    unittest.main()
