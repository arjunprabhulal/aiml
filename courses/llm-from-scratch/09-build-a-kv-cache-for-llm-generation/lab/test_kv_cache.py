"""Tests for kv_cache.py. Run: python3 -m unittest -v test_kv_cache.py"""
import copy
import subprocess
import sys
import unittest
from pathlib import Path

import checkpoint as ck
import generate as g
import kv_cache as kv
import model as m
import train as t
import trace_kv as tk
from bpe import Tokenizer

HERE = Path(__file__).parent
TOK = Tokenizer.load(HERE / "tokenizer.json")
P = ck.load(HERE / "best.json", t.CONFIG, ck.input_signature(TOK, (HERE / "corpus.txt").read_text()))["params"]
STORIES = t.split_stories((HERE / "corpus.txt").read_text())[2]


class Recorded(unittest.TestCase):
    def test_recorded_trace(self):
        result = subprocess.run([sys.executable, "trace_kv.py", "--check"], cwd=HERE)
        self.assertEqual(result.returncode, 0)


class Equivalence(unittest.TestCase):
    def test_every_cached_row_equals_the_full_forward_pass(self):
        ids = TOK.encode(STORIES[1])[:-1]
        full, _ = m.forward(P, ids)
        cache = kv.KVCache(P)
        for pos, token_id in enumerate(ids):
            self.assertEqual(kv.forward_step(P, cache, token_id, pos), full[pos])

    def test_cached_generation_matches_uncached(self):
        for i, story in enumerate(STORIES[:5]):
            opening = story.split(". ")[0] + "."
            for settings in ({}, {"temperature": 1.0, "seed": i}, {"temperature": 1.0, "top_k": 3, "seed": i}):
                with self.subTest(story=i, settings=settings):
                    self.assertEqual(kv.generate_cached(P, TOK, opening, **settings),
                                     g.generate(P, TOK, opening, **settings))

    def test_context_full_stops_at_the_same_point(self):
        prompt = TOK.decode(TOK.encode((HERE / "corpus.txt").read_text())[:63])
        self.assertEqual(kv.generate_cached(P, TOK, prompt), g.generate(P, TOK, prompt))

    def test_work_counts_match_the_rows_the_model_processes(self):
        rows = []
        original = m.forward
        m.forward = lambda p, ids, *a: (rows.append(len(ids)), original(p, ids, *a))[1]
        try:
            opening = STORIES[0].split(". ")[0] + "."
            result = g.generate(P, TOK, opening)
        finally:
            m.forward = original
        counts = tk.work(len(TOK.encode(opening)), len(result["steps"]))
        self.assertEqual(sum(rows), counts["uncached_rows"])
        self.assertEqual(sum(n * (n + 1) // 2 for n in rows), counts["uncached_scores"])

    def test_cached_work_counts_match_the_forward_step_calls(self):
        positions = []
        original = kv.forward_step
        kv.forward_step = lambda p, cache, token_id, position: (positions.append(position), original(p, cache, token_id, position))[1]
        try:
            opening = STORIES[0].split(". ")[0] + "."
            result = kv.generate_cached(P, TOK, opening)
        finally:
            kv.forward_step = original
        counts = tk.work(len(TOK.encode(opening)), len(result["steps"]))
        self.assertEqual(len(positions), counts["cached_rows"])
        self.assertEqual(sum(pos + 1 for pos in positions), counts["cached_scores"])  # one score per cached key


class FailureCases(unittest.TestCase):
    def test_reusing_a_cache_for_a_new_prompt(self):
        cache = kv.KVCache(P)
        kv.forward_step(P, cache, TOK.ids["mia"], 0)
        with self.assertRaisesRegex(ValueError, "expected position 1, got 0"):
            kv.forward_step(P, cache, TOK.ids["mia"], 0)

    def test_tokens_out_of_order(self):
        with self.assertRaisesRegex(ValueError, "expected position 0, got 2"):
            kv.forward_step(P, kv.KVCache(P), TOK.ids["mia"], 2)

    def test_cache_from_other_parameters(self):
        other = copy.deepcopy(P)
        cache = kv.KVCache(other)
        with self.assertRaisesRegex(ValueError, "different parameters"):
            kv.forward_step(P, cache, TOK.ids["mia"], 0)

    def test_position_beyond_the_table(self):
        cache = kv.KVCache(P)
        cache.keys = cache.values = [[0.0]] * 64
        with self.assertRaisesRegex(ValueError, "beyond the 64 positions"):
            kv.forward_step(P, cache, TOK.ids["mia"], 64)

    def test_token_outside_the_vocabulary(self):
        for bad in (-1, 96, True):
            with self.subTest(token=bad), self.assertRaisesRegex(ValueError, "outside the vocabulary"):
                kv.forward_step(P, kv.KVCache(P), bad, 0)


if __name__ == "__main__":
    unittest.main()
