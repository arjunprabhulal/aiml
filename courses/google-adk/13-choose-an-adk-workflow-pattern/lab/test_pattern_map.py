"""Check the recorded pattern map against the lessons' code, and pin two wiring mistakes."""
import json
import unittest
import warnings
from pathlib import Path

from google.adk import Agent, Workflow
from google.adk.agents import LoopAgent, ParallelAgent, SequentialAgent
from pydantic import ValidationError

from pattern_map import PATTERNS, describe, EXAMPLES

RECORD = json.loads(Path(__file__).with_name("pattern-map.json").read_text())


def shape(name):
    return next(entry["shape"] for entry in RECORD if entry["pattern"] == name)


class PatternMap(unittest.TestCase):
    def test_the_recorded_map_matches_the_lesson_code(self):
        self.assertEqual([describe(name) for name in PATTERNS], RECORD)

    def test_inspector_dependencies_are_inside_the_download(self):
        root=Path(__file__).resolve().parent
        self.assertEqual(EXAMPLES,root/'patterns')
        for folder,module,*_ in PATTERNS.values():
            self.assertTrue((EXAMPLES/folder/(module+'.py')).is_file())
        self.assertTrue((EXAMPLES/'adk-graph-routes'/'docs-pages.txt').is_file())

    def test_a_sequential_pipeline_never_branches(self):
        sources = [line.split(" -> ")[0] for line in shape("Sequential pipeline")]
        self.assertEqual(len(sources), len(set(sources)))

    def test_refinement_has_one_back_edge_into_its_check(self):
        self.assertIn("revise_entry -> check_entry", shape("Iterative refinement"))

    def test_the_join_waits_for_three_branches(self):
        into_join = [line for line in shape("Parallel fan-out and gather")
                     if line.endswith("-> gather")]
        self.assertEqual(len(into_join), 3)

    def test_an_unreachable_node_fails_when_the_graph_is_built(self):
        def draft(node_input: str):
            return node_input

        def review(node_input: str):
            return node_input

        with self.assertRaisesRegex(ValidationError, r"unreachable from START: \['review'\]"):
            Workflow(name="broken", edges=[("START", draft), (review, draft)])

    def test_the_template_workflow_agents_are_deprecated(self):
        step = Agent(name="step", model="gemini-3.8-flash", instruction="Summarize.")
        for template in (SequentialAgent, LoopAgent, ParallelAgent):
            with self.subTest(template.__name__), warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                template(name="old", sub_agents=[step.model_copy()])
                self.assertTrue(any("deprecated in favor of Workflow" in str(w.message)
                                    for w in caught))


if __name__ == "__main__":
    unittest.main()
