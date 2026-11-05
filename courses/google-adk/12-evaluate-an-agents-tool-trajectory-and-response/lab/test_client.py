"""No live evaluation: fake evaluator bookkeeping and real native loading only."""
import asyncio,hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from google.adk.cli.utils.agent_loader import AgentLoader
from docs_agent.agent import root_agent
import run_eval
HERE=Path(__file__).parent

class NativeAndOptIn(unittest.TestCase):
    def test_eval_requires_explicit_mode_and_opt_in_before_any_results_change(self):
        files=list(HERE.glob("*.json"));before={p:p.read_bytes()for p in files}
        for args in [[],["rouge"],["judge"]]:
            result=subprocess.run([sys.executable,"run_eval.py",*args],cwd=HERE,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,2)
        self.assertEqual(before,{p:p.read_bytes()for p in files})

class EvaluationHistory(unittest.TestCase):
    def temporary_inputs(self, folder):
        for name in ("docs_agent.test.json", "test_config.json"):
            shutil.copyfile(HERE / name, folder / name)

    def run_fake(self, folder, fake):
        with patch.object(run_eval, "HERE", folder), patch.object(run_eval.AgentEvaluator, "evaluate_eval_set", fake):
            asyncio.run(run_eval.evaluate("rouge"))

    def test_original_provider_failure_survives_missing_history(self):
        error = RuntimeError("original provider setup failure")
        async def fake(**kwargs): raise error
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); self.temporary_inputs(folder)
            with self.assertRaises(RuntimeError) as caught: self.run_fake(folder, fake)
            self.assertIs(caught.exception, error)
            self.assertFalse((folder / "rouge-result.json").exists())

    def test_stale_history_is_not_used_or_deleted_on_failure(self):
        async def fake(**kwargs): raise RuntimeError("setup failed")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); self.temporary_inputs(folder)
            old = folder / "eval-results/docs_voice/eval_history/old.json"; old.parent.mkdir(parents=True)
            old.write_text('{"run":"old"}'); os.utime(old, (2100000000, 2100000000))
            with self.assertRaises(RuntimeError): self.run_fake(folder, fake)
            self.assertEqual(old.read_text(), '{"run":"old"}')
            self.assertFalse((folder / "rouge-result.json").exists())

    def test_current_history_selected_over_future_dated_stale_file_and_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); self.temporary_inputs(folder)
            old = folder / "eval-results/docs_voice/eval_history/old.json"; old.parent.mkdir(parents=True)
            old.write_text('{"run":"old"}'); os.utime(old, (2100000000, 2100000000))
            current = old.with_name("current.json")
            async def fake(**kwargs): current.write_text('{"run":"current"}')
            self.run_fake(folder, fake)
            self.assertEqual(json.loads((folder / "rouge-result.json").read_text()), {"run":"current"})
            self.assertTrue(current.exists()); self.assertTrue(old.exists())

    def test_assertion_failure_keeps_nonzero_outcome_and_current_result(self):
        error = AssertionError("evaluation threshold failed")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); self.temporary_inputs(folder)
            current = folder / "eval-results/docs_voice/eval_history/current.json"
            async def fake(**kwargs):
                current.parent.mkdir(parents=True); current.write_text('{"run":"failed"}')
                raise error
            with self.assertRaises(AssertionError) as caught: self.run_fake(folder, fake)
            self.assertIs(caught.exception, error)
            self.assertEqual(json.loads((folder / "rouge-result.json").read_text()), {"run":"failed"})
            self.assertTrue(current.exists())

    def test_bad_current_history_cannot_mask_original_failure(self):
        error = RuntimeError("original provider failure")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); self.temporary_inputs(folder)
            current = folder / "eval-results/docs_voice/eval_history/current.json"
            async def fake(**kwargs):
                current.parent.mkdir(parents=True); current.write_text('not-json')
                raise error
            with self.assertRaises(RuntimeError) as caught: self.run_fake(folder, fake)
            self.assertIs(caught.exception, error)
            self.assertEqual(current.read_text(), 'not-json')


if __name__=="__main__":unittest.main()
