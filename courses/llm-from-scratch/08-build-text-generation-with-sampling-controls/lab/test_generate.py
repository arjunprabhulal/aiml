"""Tests for generate.py. Run: python3 -m unittest -v test_generate.py"""
import math
import subprocess
import sys
import unittest
from pathlib import Path

import checkpoint as ck
import generate as g
import model as m
import train as t
from bpe import Tokenizer

HERE = Path(__file__).parent
TOK = Tokenizer.load(HERE / "tokenizer.json")
P = ck.load(HERE / "best.json", t.CONFIG, ck.input_signature(TOK, (HERE / "corpus.txt").read_text()))["params"]
LOGITS = m.forward(P, TOK.encode("mia has a red ball. mia goes to the park. now leo has the"))[0][-1]


class Recorded(unittest.TestCase):
    def test_recorded_trace(self):
        result = subprocess.run([sys.executable, "trace_generate.py", "--check"], cwd=HERE)
        self.assertEqual(result.returncode, 0)


class Selection(unittest.TestCase):
    def test_greedy_puts_all_probability_on_the_top_score(self):
        probs = g.next_token_probs(LOGITS, 0.0, None)
        self.assertEqual(probs.index(1.0), max(range(len(LOGITS)), key=lambda i: LOGITS[i]))
        self.assertEqual(sum(probs), 1.0)

    def test_greedy_ties_go_to_the_lowest_token_id(self):
        self.assertEqual(g.next_token_probs([1.0, 5.0, 5.0, 2.0], 0.0, None), [0.0, 1.0, 0.0, 0.0])

    def test_temperature_one_is_plain_softmax(self):
        self.assertEqual(g.next_token_probs(LOGITS, 1.0, None), m.softmax_row(LOGITS))

    def test_lower_temperature_sharpens(self):
        tops = [max(g.next_token_probs(LOGITS, temp, None)) for temp in (2.0, 1.0, 0.5)]
        self.assertEqual(tops, sorted(tops))
        self.assertLess(tops[0], tops[2])

    def test_top_k_keeps_exactly_k_tokens(self):
        probs = g.next_token_probs(LOGITS, 1.0, 3)
        kept = [i for i, v in enumerate(probs) if v > 0]
        self.assertEqual(len(kept), 3)
        self.assertEqual(sorted(kept), sorted(sorted(range(len(LOGITS)), key=lambda i: -LOGITS[i])[:3]))
        self.assertAlmostEqual(math.fsum(probs), 1.0, places=12)

    def test_top_k_ties_keep_the_highest_scores(self):
        probs = g.next_token_probs([1.0, 1.0, 5.0], 1.0, 2)
        self.assertEqual([v > 0 for v in probs], [True, False, True])
        self.assertEqual([v > 0 for v in g.next_token_probs([2.0, 2.0, 2.0, 0.0], 1.0, 2)], [True, True, False, False])

    def test_same_seed_same_text(self):
        a = g.generate(P, TOK, "zoe has a blue kite.", temperature=1.0, seed=1)
        b = g.generate(P, TOK, "zoe has a blue kite.", temperature=1.0, seed=1)
        c = g.generate(P, TOK, "zoe has a blue kite.", temperature=1.0, seed=2)
        self.assertEqual(a, b)
        self.assertNotEqual(a["text"], c["text"])


class Stopping(unittest.TestCase):
    def test_stops_at_the_end_of_a_story(self):
        result = g.generate(P, TOK, "mia has a red ball.")
        self.assertEqual(result["stopped"], "end of story")
        self.assertTrue(result["text"].endswith("\n"))

    def test_stops_at_max_new_tokens(self):
        result = g.generate(P, TOK, "mia has a red ball.", max_new_tokens=2)
        self.assertEqual((result["stopped"], len(result["steps"])), ("max_new_tokens", 2))

    def test_stops_when_the_context_is_full(self):
        prompt = TOK.decode(TOK.encode((HERE / "corpus.txt").read_text())[:63])
        result = g.generate(P, TOK, prompt)
        self.assertEqual(result["stopped"], "context full")
        self.assertEqual(len(TOK.encode(result["text"])), 64)


class FailureCases(unittest.TestCase):
    def test_invalid_temperature(self):
        for bad in (-0.1, 0.001, float("nan"), float("inf"), True, "1"):
            with self.subTest(temperature=bad), self.assertRaisesRegex(ValueError, "temperature must be"):
                g.generate(P, TOK, "mia", temperature=bad)

    def test_invalid_top_k(self):
        for bad in (0, 97, True, 2.0):
            with self.subTest(top_k=bad), self.assertRaisesRegex(ValueError, "top_k must be"):
                g.generate(P, TOK, "mia", temperature=1.0, top_k=bad)

    def test_empty_prompt(self):
        with self.assertRaisesRegex(ValueError, "empty prompt"):
            g.generate(P, TOK, "")

    def test_prompt_longer_than_the_context(self):
        prompt = TOK.decode(TOK.encode((HERE / "corpus.txt").read_text())[:65])
        self.assertEqual(len(TOK.encode(prompt)), 65)
        with self.assertRaisesRegex(ValueError, "prompt of 65 tokens is longer than the 64 positions"):
            g.generate(P, TOK, prompt)

    def test_story_check_rejects_a_broken_story(self):
        broken = g.generate(P, TOK, "maya has a purple umbrella.")["text"]
        self.assertEqual(g.follows_story("maya has a purple umbrella.", broken),
                         {"well_formed": False, "keeps_color_and_object": False})


if __name__ == "__main__":
    unittest.main()
