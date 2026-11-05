"""Exercise the learner entry point through the real workflow without network calls."""
import asyncio
import contextlib
import io
import unittest
from run import compare
from harness import ReplayLlm
from google.genai import types
from unittest.mock import patch
from upgrade_guide import build_tree

EXPECTED = ['depth: 2 | budget: 64', 'tree-wide model call budget of 1 exceeded', 'missing pages:']

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
        # The fresh replay must use the actual leaf's available read/search tools.
        leaf_requests = [str(request.config.system_instruction) for request in observed
                         if "Write one section of an upgrade guide:" in str(request.config.system_instruction)]
        self.assertTrue(leaf_requests)
        self.assertTrue(all("Use search_docs with one or two words" in request
                            for request in leaf_requests))
        text = output.getvalue()
        for expected in EXPECTED:
            self.assertIn(expected, text)

    def test_changed_system_instruction_has_no_recorded_reply(self):
        from types import SimpleNamespace
        from harness import system_key, history_key
        old = SimpleNamespace(config=SimpleNamespace(system_instruction="Get every fact from research_docs;"), contents=[])
        changed = SimpleNamespace(config=SimpleNamespace(system_instruction="Use search_docs with one or two words, then read_page. Get every fact from those pages;"), contents=[])
        model = ReplayLlm(model="gemini-3.8-flash",calls=[{"system":system_key(old),"history":history_key(old),"reply":{}}])
        async def attempt():
            async for _ in model.generate_content_async(changed):
                pass
        with self.assertRaisesRegex(LookupError,"no recorded reply"):
            asyncio.run(attempt())
        self.assertEqual(len(model.calls),1)

    def test_section_writer_instruction_matches_its_tools_at_each_depth(self):
        two_level_writer = build_tree("gemini-3.8-flash", max_depth=2).tools[0].agent
        self.assertEqual({tool.__name__ for tool in two_level_writer.tools},
                         {"search_docs", "read_page"})
        self.assertNotIn("research_docs", two_level_writer.instruction)
        self.assertIn("search_docs", two_level_writer.instruction)
        self.assertIn("read_page", two_level_writer.instruction)

        three_level_writer = build_tree("gemini-3.8-flash", max_depth=3).tools[0].agent
        self.assertEqual(three_level_writer.tools[0].agent.name, "research_docs")
        self.assertIn("Get every fact from research_docs;", three_level_writer.instruction)

if __name__ == "__main__":
    unittest.main()
