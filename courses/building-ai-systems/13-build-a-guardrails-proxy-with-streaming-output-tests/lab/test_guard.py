"""Tests for the streaming guardrails: python3 -m unittest -v test_guard.py

The proxy tests run the real HTTP proxy on 127.0.0.1 and replay recorded model
streams chunk by chunk. No model is called and nothing depends on timing.
"""
import json
import unittest
from pathlib import Path

import guard
import proxy
import run_guard

HERE = Path(__file__).resolve().parent
EMAIL, CARD = "jane.doe@example.com", "4111 1111 1111 1111"


class Guard(unittest.TestCase):
    def test_a_value_split_over_many_chunks_is_redacted(self):
        chunks = ["Email: jane", ".", "doe", "@", "example", ".", "com", " and card 4", "111 1", "111 1111 1111", "."]
        self.assertEqual("".join(guard.guarded(chunks)[0]), "Email: [email removed] and card [card removed].")

    def test_the_per_chunk_filter_misses_the_same_values(self):
        chunks = ["Email: jane", ".", "doe", "@", "example", ".", "com"]
        self.assertIn(EMAIL, guard.per_chunk_filter(chunks))

    def test_nothing_that_could_still_become_a_value_is_released(self):
        g = guard.StreamGuard()
        self.assertEqual(g.feed("Card 4111 1111 "), "Card ")  # the digits wait for the next chunk
        self.assertEqual(g.feed("1111 1111"), "")
        self.assertEqual(g.feed(" is on file"), "[card removed] is on ")
        self.assertEqual(g.finish(), "file")

    def test_a_complete_value_is_never_cut_by_the_release_point(self):
        # The trailing "1111." could still be the start of an email, which begins inside the
        # complete card. The guard holds the whole card instead of releasing its first digits.
        g = guard.StreamGuard()
        self.assertEqual(g.feed("Card " + CARD + "."), "Card ")
        self.assertEqual(g.finish(), "[card removed].")

    def test_a_digit_run_that_fails_the_luhn_check_is_left_alone(self):
        self.assertEqual("".join(guard.guarded(["Order 1234 5678 9012 3456."])[0]), "Order 1234 5678 9012 3456.")
        self.assertTrue(guard.luhn_ok("4111111111111111"))
        self.assertFalse(guard.luhn_ok("1234567890123456"))

    def test_block_releases_only_the_text_before_the_first_value(self):
        pieces, g = guard.guarded(["Hi ", "jane", ".doe@example.com", " more"], action="block")
        self.assertEqual(("".join(pieces), g.blocked), ("Hi ", "email"))

    def test_output_does_not_depend_on_how_the_stream_was_chunked(self):
        text = f"Write to {EMAIL} or use {CARD}, not 1234 5678 9012 3456."
        reference = "".join(guard.guarded([text])[0])
        for n in range(1, 15):
            self.assertEqual("".join(guard.guarded([text[i:i + n] for i in range(0, len(text), n)])[0]), reference, n)


class Proxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = {row["id"]: row for row in run_guard.results()["conversations"]}

    def test_saved_results_match_a_fresh_replay_byte_for_byte(self):
        self.assertEqual((HERE / "results.json").read_text(encoding="utf-8"),
                         run_guard.record({"model": proxy.MODEL["ollama_tag"], "conversations": list(self.rows.values())}))

    def test_the_recorded_answer_leaks_through_a_per_chunk_filter_but_not_the_proxy(self):
        row = self.rows["email-and-card"]
        self.assertTrue(EMAIL in row["per_chunk_filter"] and CARD in row["per_chunk_filter"])
        self.assertNotIn(EMAIL, row["redact"]["client_text"])
        self.assertNotIn(CARD, row["redact"]["client_text"])
        self.assertEqual(row["redact"]["final"]["guardrail"]["findings"], ["email", "card"])

    def test_block_ends_the_stream_and_stops_reading_the_model(self):
        row = self.rows["email-and-card"]
        self.assertEqual(row["block"]["final"]["done_reason"], "guardrail")
        self.assertLess(row["block"]["upstream_chunks_read"], row["chunks"])
        self.assertNotIn("@", row["block"]["client_text"])

    def test_answers_without_values_pass_through_unchanged(self):
        for name in ("card-only", "order-number", "no-personal-data"):
            row = self.rows[name]
            self.assertEqual(row["redact"]["client_text"], row["answer"], name)
            self.assertEqual(row["redact"]["final"]["guardrail"]["findings"], [], name)

    def test_every_recorded_answer_gives_the_same_output_for_any_chunking(self):
        self.assertTrue(all(row["same_output_for_any_chunking"] for row in self.rows.values()))

    def test_replay_refuses_a_request_that_was_not_recorded(self):
        payload = run_guard.request_for("A question nobody recorded")
        with self.assertRaises(LookupError):
            list(proxy.ReplayUpstream().stream(payload))


if __name__ == "__main__":
    unittest.main()
