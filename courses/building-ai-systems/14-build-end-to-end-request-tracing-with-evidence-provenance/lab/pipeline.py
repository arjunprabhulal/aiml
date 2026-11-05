"""The grounded support pipeline, traced end to end. Python standard library only.

One request runs through four steps, each in its own span of one trace:

  retrieval        HTTP call to retrieval_service.py, with the traceparent header
  assemble context keep the top context_limit passages, record the ones dropped
  chat             one model call; live through Ollama, or replayed from a recording
  check citations  give every [passage-id] citation in the answer a provenance verdict

Spans carry IDs, versions, hashes and counts, never the question, passage or answer
text. The answer itself goes to the caller, and the evaluation harness stores it.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib import request as urlrequest

from harness import Answer
from tracing import DerivedIds, Tracer

HERE = Path(__file__).resolve().parent
MODEL = json.loads((HERE / "model.json").read_text(encoding="utf-8"))
CORPUS = json.loads((HERE / "corpus.json").read_text(encoding="utf-8"))
TOP_K = 3
PROMPT_VERSION = "1"
INSTRUCTIONS = ("You answer customer support questions for an online shop. Use only the passages below. "
                "After each sentence that uses a passage, cite it by its ID in square brackets, for example "
                "[delivery-times]. If the passages do not contain the answer, say that you do not know.")
CITATION = re.compile(r"\[([a-z0-9-]+)\]")
# Worst first: the first verdict found in this order is the answer's overall provenance.
VERDICTS = ("unknown", "not_in_context", "stale", "uncited", "supported")


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class RetrievalClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def search(self, query, k, traceparent):
        body = json.dumps({"query": query, "k": k}).encode("utf-8")
        headers = {"Content-Type": "application/json", "traceparent": traceparent}
        req = urlrequest.Request(self.base_url + "/search", data=body, headers=headers, method="POST")
        with urlrequest.urlopen(req, timeout=30) as response:
            return json.load(response)["passages"]


class OllamaModel:
    """Live calls to a local Ollama server, refused unless the pinned digest is installed."""

    replayed = False

    def __init__(self, base_url="http://127.0.0.1:11434"):
        self.base_url = base_url
        with urlrequest.urlopen(base_url + "/api/tags", timeout=30) as response:
            installed = {m["name"]: m["digest"] for m in json.load(response)["models"]}
        if installed.get(MODEL["ollama_tag"]) != MODEL["ollama_digest"]:
            raise RuntimeError(f"{MODEL['ollama_tag']} is missing or not the pinned digest")
        self.recorded = {}

    def chat(self, payload):
        req = urlrequest.Request(self.base_url + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
        with urlrequest.urlopen(req, timeout=600) as response:
            raw = json.load(response)
        kept = {key: raw.get(key) for key in ("model", "done_reason", "prompt_eval_count", "eval_count",
                                              "load_duration", "prompt_eval_duration", "eval_duration",
                                              "total_duration")}
        kept["content"] = raw["message"]["content"]
        self.recorded[sha256(canonical(payload))] = kept
        return kept


class ReplayModel:
    """Answers from recorded responses, keyed by the SHA-256 of the exact request payload."""

    replayed = True

    def __init__(self, path):
        recording = json.loads(Path(path).read_text(encoding="utf-8"))
        if recording["model"] != MODEL:
            raise RuntimeError("recording was made with a different model pin")
        self.calls = recording["calls"]

    def chat(self, payload):
        try:
            return self.calls[sha256(canonical(payload))]
        except KeyError:
            # The request changed (prompt, passages, seed or options): no recording matches it.
            raise LookupError("no recorded response for this exact request") from None


def assemble(passages, limit):
    """Keep the `limit` best passages in rank order; return (kept, dropped)."""
    return passages[:limit], passages[limit:]


def messages(question, kept):
    block = "\n".join(f"[{p['id']}] {p['text']}" for p in kept)
    return [{"role": "system", "content": f"{INSTRUCTIONS}\n\nPassages:\n{block}"},
            {"role": "user", "content": question}]


def check_citations(answer, retrieved, kept, current):
    """One verdict per distinct citation, plus 'uncited' when the answer cites nothing.

    unknown         the ID was not among the retrieved passages
    not_in_context  retrieved, but dropped before the model call
    stale           in the context, but the index served an older document version
    supported       in the context, from the current document version
    """
    retrieved_ids = {p["id"]: p for p in retrieved}
    kept_ids = {p["id"] for p in kept}
    verdicts = []
    for cited in dict.fromkeys(CITATION.findall(answer)):
        passage = retrieved_ids.get(cited)
        if passage is None:
            verdict = "unknown"
        elif cited not in kept_ids:
            verdict = "not_in_context"
        elif passage["version"] < int(current[cited]):
            verdict = "stale"
        else:
            verdict = "supported"
        verdicts.append({"citation": cited, "verdict": verdict,
                         **({"version": passage["version"], "current_version": int(current[cited]),
                             "sha256": passage["sha256"], "rank": passage["rank"]} if passage else {})})
    if not verdicts:
        verdicts.append({"citation": None, "verdict": "uncited"})
    return verdicts


def overall(verdicts):
    return next(v for v in VERDICTS if any(item["verdict"] == v for item in verdicts))


class Pipeline:
    def __init__(self, retrieval, model, exporter, context_limit, clock=None):
        self.retrieval, self.model, self.exporter, self.clock = retrieval, model, exporter, clock
        self.context_limit = context_limit

    def handle(self, question, seed, ids):
        tracer = Tracer("gateway", self.exporter, ids=ids, **({"clock": self.clock} if self.clock else {}))
        with tracer.span("answer request", **{"app.question.sha256": sha256(question),
                                              "app.question.length": len(question)}) as root:
            if not question.strip():
                raise ValueError("question is blank")
            with tracer.span("retrieval support-docs", **{"gen_ai.operation.name": "retrieval",
                                                          "gen_ai.data_source.id": "support-docs",
                                                          "gen_ai.retrieval.top_k": TOP_K}) as hop:
                passages = self.retrieval.search(question, TOP_K, hop.traceparent())
                hop.set(**{"app.retrieval.passage_ids": [p["id"] for p in passages]})
            with tracer.span("assemble context", **{"app.context.limit": self.context_limit}) as step:
                kept, dropped = assemble(passages, self.context_limit)
                step.set(**{"app.context.kept": [p["id"] for p in kept],
                            "app.context.dropped": [{"id": p["id"], "rank": p["rank"]} for p in dropped]})
            payload = {"model": MODEL["ollama_tag"], "messages": messages(question, kept), "stream": False,
                       "think": MODEL["think"], "options": {**MODEL["options"], "seed": seed}}
            with tracer.span(f"chat {MODEL['ollama_tag']}", **{
                    "gen_ai.operation.name": "chat", "gen_ai.provider.name": "ollama",
                    "gen_ai.request.model": MODEL["ollama_tag"], "gen_ai.request.seed": seed,
                    "gen_ai.request.max_tokens": MODEL["options"]["num_predict"],
                    "app.request.sha256": sha256(canonical(payload)), "app.prompt.version": PROMPT_VERSION}) as chat:
                reply = self.model.chat(payload)
                chat.set(**{"gen_ai.usage.input_tokens": reply["prompt_eval_count"],
                            "gen_ai.usage.output_tokens": reply["eval_count"],
                            "gen_ai.response.finish_reasons": [reply["done_reason"]],
                            # Ollama's own timing for the call, recorded with it. A replayed call
                            # takes almost no time, so the span's duration is not the model's.
                            "app.model.replayed": self.model.replayed,
                            "app.model.reported_total_ms": round(reply["total_duration"] / 1e6, 1),
                            "app.answer.sha256": sha256(reply["content"])})
            with tracer.span("check citations") as check:
                verdicts = check_citations(reply["content"], passages, kept, CORPUS["current"])
                check.set(**{"app.citations": verdicts, "app.provenance": overall(verdicts)})
            root.set(**{"app.provenance": overall(verdicts)})
        cited = sorted({v["citation"] for v in verdicts if v["citation"]})
        return {"answer": reply["content"], "cited": ",".join(cited), "provenance": overall(verdicts)}, root.trace_id


class TracedSystem:
    """The pipeline as a system under test for the evaluation harness."""

    name, mode = "grounded-support", "live"
    prompt, tools = f"support-instructions-v{PROMPT_VERSION}", None

    def __init__(self, pipeline, version, replayed):
        self.pipeline, self.version = pipeline, version
        self.model = f"{MODEL['ollama_tag']}@{MODEL['ollama_digest'][:12]}" + (" (replayed)" if replayed else "")

    def respond(self, case, trial):
        output, trace_id = self.pipeline.handle(case["input"], seed=MODEL["seeds"][trial],
                                                ids=DerivedIds(f"{case['id']}:{trial}"))
        return Answer(output, {"trace_id": trace_id})
