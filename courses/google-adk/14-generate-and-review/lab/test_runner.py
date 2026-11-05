"""Exercise the learner entry point through the real workflow without network calls."""
import asyncio
import contextlib
import io
import unittest
from run import compare
from harness import ReplayLlm
from google.genai import types
from unittest.mock import patch

EXPECTED = ['APPROVED', 'REJECTED', 'version fact: False']

class RunnerContract(unittest.TestCase):
    def test_comparison_reaches_each_case_outcome(self):
        output = io.StringIO()
        original = ReplayLlm.generate_content_async
        observed = []

        async def checked_replay(model, llm_request, stream=False):
            self.assertEqual(llm_request.config.max_output_tokens, 1024)
            self.assertEqual(llm_request.config.thinking_config.thinking_level,
                             types.ThinkingLevel.LOW)
            observed.append(llm_request)
            async for reply in original(model, llm_request, stream):
                yield reply

        with contextlib.redirect_stdout(output), \
                patch.object(ReplayLlm, "generate_content_async", checked_replay), \
                patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            asyncio.run(compare())
        self.assertTrue(observed)
        text = output.getvalue()
        for expected in EXPECTED:
            self.assertIn(expected, text)

if __name__ == "__main__":
    unittest.main()
