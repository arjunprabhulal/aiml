"""Tests for the traced pipeline: python3 -m unittest -v test_tracing.py

The tests start the real retrieval service as a separate process and replay the
recorded model calls, so they call no model and use no network beyond loopback.
Span timing comes from a counting clock, so every duration they check is exact.
"""
import json
import tempfile
import unittest
from pathlib import Path
from urllib import request as urlrequest

import harness
import pipeline
import trace_run
from diagnose import diagnose
from tracing import CountingClock, DerivedIds, JsonLinesExporter, Tracer, collect, format_traceparent, \
    parse_traceparent, read_spans, walk

HERE = Path(__file__).resolve().parent
CASES = {case["id"]: case for case in json.loads((HERE / "cases.json").read_text())["cases"]}
BEFORE = trace_run.CONFIGS[0]


class Service:
    """The retrieval service in its own process, with its spans in a scratch file."""

    def __init__(self, index="index_snapshot"):
        self.folder = tempfile.TemporaryDirectory()
        self.spans = Path(self.folder.name) / "spans-retrieval.jsonl"
        self.spans.write_text("")
        self.process = trace_run.RetrievalProcess(self.spans, index)

    def close(self):
        self.process.__exit__()
        self.folder.cleanup()


class TracedRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = Service()

    @classmethod
    def tearDownClass(cls):
        cls.service.close()

    def handle(self, case_id, trial=0, model=None, limit=BEFORE["context_limit"]):
        """Run one case through the pipeline; return (output, trace_id, gateway spans, clock)."""
        exported, clock = [], CountingClock()
        flow = pipeline.Pipeline(pipeline.RetrievalClient(self.service.process.url),
                                 model or pipeline.ReplayModel(trace_run.RECORDING), exported.append, limit, clock=clock)
        output, trace_id = flow.handle(CASES[case_id]["input"], seed=pipeline.MODEL["seeds"][trial],
                                       ids=DerivedIds(f"{case_id}:{trial}"))
        return output, trace_id, exported

    def trace(self, trace_id, gateway):
        return collect(gateway + read_spans(self.service.spans))[trace_id]

    def test_retrieval_span_joins_the_callers_trace_across_processes(self):
        # Fails if the gateway stops sending traceparent: the service would start its own trace.
        _, trace_id, gateway = self.handle("standard-delivery")
        tree = self.trace(trace_id, gateway)
        self.assertEqual(len(tree["roots"]), 1)
        self.assertEqual(tree["orphans"], [])
        names = [(depth, span["service"], span["name"]) for depth, span in walk(tree["roots"][0])]
        self.assertEqual(names, [
            (0, "gateway", "answer request"),
            (1, "gateway", "retrieval support-docs"),
            (2, "retrieval", "retrieval support-docs"),
            (1, "gateway", "assemble context"),
            (1, "gateway", "chat gemma4:e2b"),
            (1, "gateway", "check citations"),
        ])

    def test_counting_clock_gives_exact_span_durations(self):
        _, _, gateway = self.handle("standard-delivery")
        by_name = {span["name"]: span for span in gateway}
        # The clock advances 1 ms per reading: a leaf span reads it twice, 1 ms apart.
        self.assertEqual(by_name["assemble context"]["duration_ms"], 1.0)
        self.assertEqual(by_name["answer request"]["duration_ms"], 9.0)

    def test_invalid_traceparent_restarts_the_trace_and_says_so(self):
        body = json.dumps({"query": "refund", "k": 1}).encode()
        bad = format_traceparent("A" * 32, "b" * 16)  # uppercase hex is invalid
        req = urlrequest.Request(self.service.process.url + "/search", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "traceparent": bad})
        urlrequest.urlopen(req, timeout=30).read()
        span = read_spans(self.service.spans)[-1]
        self.assertIsNone(span["parent_id"])
        self.assertNotEqual(span["trace_id"], "a" * 32)
        self.assertEqual(span["events"], [{"name": "invalid traceparent ignored; trace restarted"}])

    def test_spans_carry_ids_and_hashes_not_question_passage_or_answer_text(self):
        output, trace_id, gateway = self.handle("change-address")
        text = json.dumps(gateway + read_spans(self.service.spans))
        corpus = json.loads((HERE / "corpus.json").read_text())
        for secret in (CASES["change-address"]["input"], output["answer"],
                       corpus["documents"]["address-change"]["versions"]["1"]):
            self.assertNotIn(secret, text)
        self.assertIn(pipeline.sha256(CASES["change-address"]["input"]), text)

    def test_a_stale_index_passage_is_flagged_although_the_citation_is_real(self):
        output, _, gateway = self.handle("refund-window")
        check = next(span for span in gateway if span["name"] == "check citations")["attributes"]
        self.assertEqual(output["provenance"], "stale")
        self.assertEqual(check["app.citations"][0]["citation"], "refund-policy")
        self.assertEqual((check["app.citations"][0]["version"], check["app.citations"][0]["current_version"]), (1, 2))

    def test_a_blank_question_marks_the_root_span_as_an_error(self):
        exported = []
        flow = pipeline.Pipeline(None, None, exported.append, 2, clock=CountingClock())
        with self.assertRaises(ValueError):
            flow.handle("   ", seed=1, ids=DerivedIds("blank"))
        self.assertEqual((exported[0]["status"], exported[0]["attributes"]["error.type"]), ("error", "ValueError"))

    def test_replay_refuses_a_request_that_was_not_recorded(self):
        # A changed context limit changes the prompt, so its request hash matches no recording.
        with self.assertRaises(LookupError):
            self.handle("unwanted-parcel", limit=1)


class Provenance(unittest.TestCase):
    retrieved = [{"id": "refund-policy", "version": 1, "sha256": "a", "rank": 1},
                 {"id": "returns", "version": 1, "sha256": "b", "rank": 2},
                 {"id": "warranty", "version": 1, "sha256": "c", "rank": 3}]
    current = {"refund-policy": "2", "returns": "1", "warranty": "1"}

    def verdicts(self, answer):
        kept = self.retrieved[:2]
        return [v["verdict"] for v in pipeline.check_citations(answer, self.retrieved, kept, self.current)]

    def test_each_citation_gets_its_own_verdict(self):
        answer = "A [returns]. B [refund-policy]. C [warranty]. D [made-up-doc]. E [returns]."
        self.assertEqual(self.verdicts(answer), ["supported", "stale", "not_in_context", "unknown"])

    def test_an_answer_without_citations_is_uncited(self):
        self.assertEqual(self.verdicts("I do not know."), ["uncited"])

    def test_overall_provenance_is_the_worst_verdict(self):
        verdicts = [{"verdict": "supported"}, {"verdict": "stale"}, {"verdict": "not_in_context"}]
        self.assertEqual(pipeline.overall(verdicts), "not_in_context")


class TraceContext(unittest.TestCase):
    def test_traceparent_round_trip_and_invalid_values(self):
        header = format_traceparent("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7")
        self.assertEqual(header, "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        self.assertEqual(parse_traceparent(header), ("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7"))
        for bad in ("00-" + "0" * 32 + "-00f067aa0ba902b7-01", "00-4bf92f3577b34da6a3ce929d0e0e4736-" + "0" * 16 + "-01",
                    "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01", header.upper(), "", None):
            self.assertIsNone(parse_traceparent(bad), bad)

    def test_a_span_without_its_parent_is_reported_as_an_orphan(self):
        spans = []
        tracer = Tracer("one", spans.append, clock=CountingClock(), ids=DerivedIds("t"))
        with tracer.span("root") as root:
            with tracer.span("child"):
                pass
        child = [s for s in spans if s["name"] == "child"]
        tree = collect(child)[root.trace_id]
        self.assertEqual((tree["roots"], [s["name"] for s in tree["orphans"]]), ([], ["child"]))


class RecordedRuns(unittest.TestCase):
    def test_saved_runs_match_a_fresh_replay_apart_from_timing(self):
        with tempfile.TemporaryDirectory() as scratch:
            trace_run.execute_all(scratch, pipeline.ReplayModel(trace_run.RECORDING))
            self.assertEqual(trace_run.comparable(scratch), trace_run.comparable(HERE / "runs"))

    def test_diagnosis_names_the_step_that_lost_the_evidence(self):
        cases = list(CASES.values())
        for name, expected in (("before", {("refund-window", "index"), ("unwanted-parcel", "context assembly")}),
                               ("after", set())):
            folder = HERE / "runs" / name
            run = json.loads((folder / "run.json").read_text())
            traces = collect(read_spans(folder / "spans-gateway.jsonl", folder / "spans-retrieval.jsonl"))
            rows = diagnose(run, cases, traces, pipeline.CORPUS["current"])
            self.assertEqual({(row["case_id"], row["step"]) for row in rows}, expected, name)

    def test_replay_refuses_a_recording_made_with_another_model_pin(self):
        recording = json.loads(trace_run.RECORDING.read_text())
        recording["model"] = dict(recording["model"], ollama_digest="0" * 64)
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "other.json"
            harness.write(path, recording)
            with self.assertRaises(RuntimeError):
                pipeline.ReplayModel(path)


if __name__ == "__main__":
    unittest.main()
