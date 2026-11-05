import copy
import hashlib
import json
import unittest
from unittest.mock import Mock, patch
from agentic_rag.concepts import ROOT, Reply, chunks, prompt
from agentic_rag.request_trace import (BoundReplay, ReplayRequestMismatch, chunk_id,
                                       digest, load_runtime, trace_request)

class RequestTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved, cls.index, cls.adapter, cls.identity = load_runtime()
        cls.question = cls.saved["questions"][0]

    def test_each_replayed_result_matches_the_preserved_original_run(self):
        for expected in reversed(self.saved["results"]):
            actual = trace_request(expected["question"], self.index, self.adapter, self.identity)
            self.assertEqual(actual["result"], expected)

    def test_replay_is_bound_to_question_not_iteration_order(self):
        for i in [1, 0, 1, 0]:
            self.assertEqual(self.adapter.generate(self.saved["questions"][i], self.saved["requests"][i]), self.saved["model_replies"][i])

    def test_changed_question_cannot_receive_a_saved_reply(self):
        with self.assertRaises(ReplayRequestMismatch):
            self.adapter.generate("A different question", self.saved["requests"][0])

    def test_changed_policy_cannot_receive_a_saved_reply(self):
        messages = copy.deepcopy(self.saved["requests"][0]); messages[0][1] += " Extra policy"
        with self.assertRaises(ReplayRequestMismatch): self.adapter.generate(self.question, messages)

    def test_changed_context_cannot_receive_a_saved_reply(self):
        messages = copy.deepcopy(self.saved["requests"][0]); payload = json.loads(messages[-1][1]); payload["context"][0]["text"] += " Changed"
        messages[-1][1] = json.dumps(payload)
        with self.assertRaises(ReplayRequestMismatch): self.adapter.generate(self.question, messages)

    def test_changed_context_order_is_a_different_replay_request(self):
        messages = copy.deepcopy(self.saved["requests"][0]); payload = json.loads(messages[-1][1]); payload["context"].reverse()
        messages[-1][1] = json.dumps(payload)
        with self.assertRaises(ReplayRequestMismatch): self.adapter.generate(self.question, messages)

    def test_saved_binding_is_not_changed_by_the_callers_objects(self):
        saved = copy.deepcopy(self.saved); adapter = BoundReplay(saved)
        saved["model_replies"][0]["answer"] = "changed outside adapter"
        first = adapter.generate(self.question, self.saved["requests"][0]); first["source_ids"].append("foreign")
        self.assertEqual(adapter.generate(self.question, self.saved["requests"][0]), self.saved["model_replies"][0])

    def test_missing_reply_binding_is_refused(self):
        saved = copy.deepcopy(self.saved); saved["model_replies"].pop()
        with self.assertRaisesRegex(ValueError, "one question and reply"): BoundReplay(saved)

    def test_saved_question_must_match_saved_prompt(self):
        saved = copy.deepcopy(self.saved); saved["questions"][0] = "changed"
        with self.assertRaisesRegex(ValueError, "does not match"): BoundReplay(saved)

    def test_duplicate_saved_request_is_refused(self):
        saved = copy.deepcopy(self.saved)
        for name in ["questions", "requests", "model_replies"]: saved[name].append(copy.deepcopy(saved[name][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"): BoundReplay(saved)

    def test_real_ranked_candidates_match_the_actual_index_scores(self):
        result = trace_request(self.question, self.index, self.adapter, self.identity)
        candidates = result["events"][1]["candidates"]
        independently_ranked = self.index.similarity_search_with_score(self.question, k=2)
        self.assertEqual([row["source_id"] for row in candidates], [doc.metadata["id"] for doc, _ in independently_ranked])
        self.assertEqual([row["score"] for row in candidates], [float(score) for _, score in independently_ranked])
        self.assertGreaterEqual(candidates[0]["score"], candidates[1]["score"])
        self.assertEqual(candidates[0]["source_id"], "path-read")
        self.assertEqual(result["result"]["source_ids"], ["path-write"])

    def test_emitted_order_and_request_match_the_operations_that_ran(self):
        result = trace_request(self.question, self.index, self.adapter, self.identity)
        self.assertEqual([e["kind"] for e in result["events"]], ["request_accepted", "retrieval_completed", "context_selected", "model_request_ready", "model_reply_returned", "reply_checked", "source_links_resolved", "request_completed"])
        self.assertEqual([e["sequence"] for e in result["events"]], list(range(1, 9)))
        self.assertEqual(json.loads(json.dumps(result["events"][3]["messages"])), self.saved["requests"][0])
        self.assertEqual(result["events"][3]["request_sha256"], digest(self.saved["requests"][0]))
        self.assertEqual(result["events"][3]["schema"], Reply.model_json_schema())
        self.assertFalse(any("latency" in e or "span_id" in e for e in result["events"]))

    def test_unsupported_question_still_retrieves_but_returns_no_links(self):
        result = trace_request(self.saved["questions"][1], self.index, self.adapter, self.identity)
        self.assertTrue(result["events"][1]["candidates"])
        self.assertEqual(result["result"]["status"], "not_in_docs")
        self.assertEqual(result["result"]["source_links"], [])
        self.assertIn("model_reply_returned", [e["kind"] for e in result["events"]])

    def test_real_empty_index_skips_the_model_and_has_a_distinct_identity(self):
        _, index, _, identity = load_runtime(empty_index=True); adapter = Mock()
        result = trace_request(self.question, index, adapter, identity)
        adapter.generate.assert_not_called()
        self.assertEqual(identity["index_descriptor"]["chunk_ids"], [])
        self.assertNotEqual(identity["logical_index_id"], self.identity["logical_index_id"])
        self.assertEqual(result["result"]["status"], "not_in_docs")
        self.assertIn("model_skipped", [e["kind"] for e in result["events"]])
        self.assertNotIn("model_request_ready", [e["kind"] for e in result["events"]])

    def test_unrecorded_question_is_refused_without_fabricating_an_embedding(self):
        adapter, events = Mock(), []
        with self.assertRaisesRegex(ValueError, "No query embedding"):
            trace_request("How do I open a socket?", self.index, adapter, self.identity, events=events)
        adapter.generate.assert_not_called()
        self.assertEqual(events[-1]["kind"], "retrieval_refused")

    def test_blank_question_stops_before_search_or_model(self):
        index, adapter, events = Mock(), Mock(), []
        with self.assertRaisesRegex(ValueError, "nonblank"): trace_request(" ", index, adapter, self.identity, events=events)
        index.similarity_search_with_score.assert_not_called(); adapter.generate.assert_not_called()
        self.assertEqual(events, [{"sequence": 1, "kind": "request_rejected", "reason": "blank_question"}])

    def test_mismatched_replay_emits_refusal_without_returned_reply(self):
        adapter = Mock(mode="controlled probe"); adapter.generate.side_effect = ReplayRequestMismatch("changed")
        events = []
        with self.assertRaises(ReplayRequestMismatch): trace_request(self.question, self.index, adapter, self.identity, events=events)
        self.assertEqual(events[-1]["kind"], "replay_refused")
        self.assertFalse(any(e["kind"] == "model_reply_returned" for e in events))

    def test_source_outside_selected_context_is_rejected_even_when_in_corpus(self):
        adapter = Mock(mode="controlled reply mutation"); adapter.generate.return_value = {"status": "answered", "answer": "Something", "source_ids": ["json-text"]}
        events = []
        with self.assertRaisesRegex(ValueError, "only source IDs"): trace_request(self.question, self.index, adapter, self.identity, events=events)
        self.assertEqual(events[-1]["kind"], "reply_rejected")
        self.assertFalse(any(e["kind"] == "source_links_resolved" for e in events))

    def test_not_in_docs_cannot_attach_a_retrieved_but_unrelated_source(self):
        adapter = Mock(mode="controlled reply mutation"); adapter.generate.return_value = {"status": "not_in_docs", "answer": "Missing", "source_ids": ["path-read"]}
        with self.assertRaisesRegex(ValueError, "unrelated"): trace_request(self.question, self.index, adapter, self.identity)

    def test_bad_reply_shape_stops_before_link_resolution(self):
        adapter = Mock(mode="controlled reply mutation"); adapter.generate.return_value = {"status": "maybe", "answer": "Something", "source_ids": []}
        events = []
        with self.assertRaises(ValueError): trace_request(self.question, self.index, adapter, self.identity, events=events)
        self.assertEqual(events[-1]["reason"], "invalid_shape")

    def test_link_membership_does_not_check_answer_truth(self):
        adapter = Mock(mode="controlled reply mutation"); adapter.generate.return_value = {"status": "answered", "answer": "Path.write_text appends instead of replacing.", "source_ids": ["path-write"]}
        result = trace_request(self.question, self.index, adapter, self.identity)
        self.assertEqual(result["result"]["answer"], adapter.generate.return_value["answer"])

    def test_corpus_or_record_change_changes_the_identity_or_refuses_loading(self):
        raw = (ROOT / "runs/2026-10-22-concept/recorded-run.json").read_bytes()
        self.assertEqual(self.identity["saved_run_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.identity["corpus_sha256"], hashlib.sha256((ROOT / "data/docs.json").read_bytes()).hexdigest())
        self.assertEqual(self.identity["index_descriptor"]["chunk_ids"], [chunk_id(d) for d in chunks()])
        original = type(ROOT).read_bytes
        def changed_bytes(path):
            return b"[]" if path.name == "docs.json" else original(path)
        with patch("pathlib.Path.read_bytes", changed_bytes):
            with self.assertRaisesRegex(ValueError, "corpus differs"): load_runtime()

    def test_request_key_varies_by_question_and_logical_index(self):
        one = trace_request(self.question, self.index, self.adapter, self.identity)["request_key"]
        other = trace_request(self.saved["questions"][1], self.index, self.adapter, self.identity)["request_key"]
        self.assertNotEqual(one, other)
        with self.assertRaisesRegex(ValueError, "empty event list"):
            trace_request(self.question, self.index, self.adapter, self.identity, events=[{}])

if __name__ == "__main__": unittest.main()
