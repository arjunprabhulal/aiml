"""Exercise the learner entry point through the real workflow without network calls."""
import asyncio
import contextlib
import io
import unittest
from run import compare
from harness import ReplayLlm
from google.genai import types
from unittest.mock import patch

EXPECTED = ['graph | release-3.5.0.md', 'FileNotFoundError', 'Link check: not run']

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

    def test_partial_case_prints_the_failed_child_before_the_page(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            asyncio.run(compare())
        partial = output.getvalue().split("partial | release-3.6.0.md", 1)[1]
        diagnostic = "check_links@1 failed: FileNotFoundError:"
        self.assertIn(diagnostic, partial)
        self.assertIn("site-3.6.0/sitemap.txt not found", partial)
        self.assertLess(partial.index(diagnostic), partial.index("# docuctl 3.6.0 release notes"))
        self.assertIn("Link check: not run (see the error above).", partial)

if __name__ == "__main__":
    unittest.main()
