"""Evaluate the docs assistant per stage (tools, retrieval, grounding) and write a report."""
import argparse
import functools
import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
from deepeval.metrics import (  # noqa: E402
    AnswerRelevancyMetric, ContextualPrecisionMetric, ContextualRecallMetric, FaithfulnessMetric, ToolCorrectnessMetric)
from deepeval.models import GeminiModel, OllamaModel  # noqa: E402
from deepeval.test_case import LLMTestCase, ToolCall  # noqa: E402

from assistant import CHAT_MODEL, EMBED_MODEL, K, PROMPT, build_agent, run  # noqa: E402
from cassette import Cassette  # noqa: E402

HERE = Path(__file__).parent
THRESHOLD = 0.7
STAGES = ["tools", "retrieval", "faithfulness", "contextual_recall", "answer_relevancy"]
# calibrate.py: the default faithfulness metric passed an answer with an unsupported claim; strict mode caught it.
STRICT_FAITHFULNESS = True
JUDGE_MODEL = "gemini-3.8-flash"  # fixed, so scores stay comparable when the assistant's model changes


def sha(value) -> str:
    """Content hash: editing a case, a page, an issue or the prompt changes it."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]


def recording_key(cases: dict, docs: list[dict], issues: dict) -> dict:
    """Everything a recorded trace or verdict depends on. A replay with any other value is refused."""
    return {"cases": f"{cases['name']}@{cases['version']}", "cases_sha": sha(cases),
            "docs_sha": sha({"docs": docs, "issues": issues}), "prompt_sha": sha(PROMPT), "k": K,
            "model": CHAT_MODEL, "embedder": EMBED_MODEL, "judge": JUDGE_MODEL,
            "strict_faithfulness": STRICT_FAITHFULNESS}


def make_judge(name: str = JUDGE_MODEL):
    if name.startswith("gemini"):
        return GeminiModel(model=name)
    return OllamaModel(model=name, base_url="http://localhost:11434", temperature=0)


def retrieval_scores(retrieved: list[str], expected: list[str]) -> dict | None:
    if not expected:
        return None
    ranks = [retrieved.index(doc) + 1 for doc in expected if doc in retrieved]
    return {"hit": bool(ranks), "recall": len(ranks) / len(expected),
            "reciprocal_rank": 1 / min(ranks) if ranks else 0.0}


def tool_scores(question: str, calls: list[dict], expected: list[str], judge) -> dict:
    case = LLMTestCase(
        input=question,
        tools_called=[ToolCall(name=c["name"], input_parameters=c["args"]) for c in calls],
        expected_tools=[ToolCall(name=name) for name in expected],
    )
    # Without available_tools the metric only compares names and never calls the judge,
    # but it still requires a model object.
    metric = ToolCorrectnessMetric(model=judge, async_mode=False)
    metric.measure(case)
    unexpected = [c["name"] for c in calls if c["name"] not in expected]
    return {"score": metric.score, "unexpected": unexpected, "pass": metric.score == 1.0 and not unexpected}


def judged_scores(case: dict, trace: dict, judge) -> dict:
    """DeepEval's judged metrics. Context metrics run only when a tool returned context."""
    context = [d["text"] for o in trace["tool_outputs"] if o["tool"] == "search_docs" for d in json.loads(o["content"])]
    context += [o["content"] for o in trace["tool_outputs"] if o["tool"] == "get_issue"]
    test_case = LLMTestCase(input=case["question"], actual_output=trace["answer"],
                            expected_output=case["reference"], retrieval_context=context or None)
    metrics = {"answer_relevancy": AnswerRelevancyMetric(THRESHOLD, model=judge, async_mode=False)}
    if context:
        metrics |= {"faithfulness": FaithfulnessMetric(THRESHOLD, model=judge, async_mode=False,
                                                       penalize_ambiguous_claims=STRICT_FAITHFULNESS),
                    "contextual_precision": ContextualPrecisionMetric(THRESHOLD, model=judge, async_mode=False),
                    "contextual_recall": ContextualRecallMetric(THRESHOLD, model=judge, async_mode=False)}
    scores = {}
    for name, metric in metrics.items():
        metric.measure(test_case)
        scores[name] = {"score": metric.score, "reason": metric.reason}
    return scores


def first_failure(row: dict) -> str | None:
    checks = {"tools": row["tools"]["pass"],
              "retrieval": row["retrieval"] is None or row["retrieval"]["recall"] == 1.0,
              **{n: row["judged"][n]["score"] >= THRESHOLD for n in row["judged"]}}
    return next((stage for stage in STAGES if checks.get(stage) is False), None)


def evaluate(cases: dict, cassette: Cassette, judge) -> dict:
    """`judge` is a callable that builds the judge model, so a replay needs no API key."""
    agent = None
    rows = []
    for case in cases["cases"]:
        def live_run():
            nonlocal agent
            agent = agent or build_agent(json.loads((HERE / "docs.json").read_text()),
                                         json.loads((HERE / "issues.json").read_text()))
            return run(agent, case["question"])
        trace = cassette.get(f"agent/{case['id']}", live_run)
        row = {"id": case["id"], "answer": trace["answer"], "calls": [c["name"] for c in trace["tool_calls"]],
               "tools": cassette.get(f"tools/{case['id']}", lambda: tool_scores(
                   case["question"], trace["tool_calls"], case["expected_tools"], judge())),
               "retrieval": retrieval_scores(trace["retrieved"], case["expected_docs"]),
               "judged": cassette.get(f"judge/{case['id']}", lambda: judged_scores(case, trace, judge()))}
        rows.append({**row, "first_failure": first_failure(row)})
        print(f"evaluated {case['id']} ({len(rows)}/{len(cases['cases'])})", file=sys.stderr, flush=True)
    return {"key": cassette.key, "k": K, "threshold": THRESHOLD, "rows": rows, "summary": summarize(rows)}


def summarize(rows: list[dict]) -> dict:
    ranked = [r["retrieval"] for r in rows if r["retrieval"]]
    faith = [r["judged"]["faithfulness"]["score"] for r in rows if "faithfulness" in r["judged"]]
    return {"cases": len(rows), "passed": sum(r["first_failure"] is None for r in rows),
            "tool_pass": sum(r["tools"]["pass"] for r in rows),
            f"hit_at_{K}": f"{sum(r['hit'] for r in ranked)}/{len(ranked)}",
            f"recall_at_{K}": round(sum(r["recall"] for r in ranked) / len(ranked), 3),
            "mrr": round(sum(r["reciprocal_rank"] for r in ranked) / len(ranked), 3),
            "mean_faithfulness": round(sum(faith) / len(faith), 3)}


def markdown(report: dict) -> str:
    fmt = lambda x: "-" if x is None else f"{x:.2f}"  # noqa: E731
    lines = [f"| case | tools called | tools | hit@{report['k']} | recall@{report['k']} | RR | ctx precision | "
             "faithful | ctx recall | relevancy | first failure |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in report["rows"]:
        ret, j = r["retrieval"], r["judged"]
        lines.append(f"| {r['id']} | {', '.join(r['calls']) or 'none'} | {'pass' if r['tools']['pass'] else 'FAIL'} | "
                     f"{'-' if ret is None else ('yes' if ret['hit'] else 'NO')} | {fmt(ret and ret['recall'])} | "
                     f"{fmt(ret and ret['reciprocal_rank'])} | {fmt(j.get('contextual_precision', {}).get('score'))} | "
                     f"{fmt(j.get('faithfulness', {}).get('score'))} | {fmt(j.get('contextual_recall', {}).get('score'))} | "
                     f"{fmt(j.get('answer_relevancy', {}).get('score'))} | "
                     f"{r['first_failure'] or '-'} |")
    s, k = report["summary"], report["k"]
    lines.append(f"\n{s['passed']}/{s['cases']} cases pass every stage. Tools {s['tool_pass']}/{s['cases']}, "
                 f"hit@{k} {s[f'hit_at_{k}']}, recall@{k} {s[f'recall_at_{k}']}, MRR {s['mrr']}, "
                 f"mean faithfulness {s['mean_faithfulness']}.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="call the models and rewrite the recording")
    live = parser.parse_args().live
    cases = json.loads((HERE / "cases.json").read_text())
    key = recording_key(cases, json.loads((HERE / "docs.json").read_text()), json.loads((HERE / "issues.json").read_text()))
    name = CHAT_MODEL.replace(":", "-")  # one recording and one report per model under test
    cassette = Cassette(HERE / "recordings" / f"{name}.json", key, live)
    report = evaluate(cases, cassette, functools.cache(make_judge))
    if live:
        cassette.save()
    (HERE / "runs" / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n")
    (HERE / "runs" / f"{name}.md").write_text(markdown(report) + "\n")
    print(markdown(report))


if __name__ == "__main__":
    main()
