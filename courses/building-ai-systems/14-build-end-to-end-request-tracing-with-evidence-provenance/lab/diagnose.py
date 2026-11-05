"""Follow each failed evaluation row to its trace and name the step where the evidence went wrong.

The harness stores the trace ID in each row's metadata. The trace shows what the
retrieval service returned, what the assembly step kept and dropped, and how the
citation check judged the answer. The rules are checked in pipeline order, so the
first step that lost or corrupted the expected source document is the one reported:

  retrieval         the source document was not among the top k passages
  index             it was retrieved from an older version than the current document
  context assembly  it was retrieved but dropped before the model call
  model             it reached the model, and the answer still failed a grader
"""
from tracing import walk


def spans(tree):
    """Every span in the trace, orphans included, in tree order."""
    for root in tree["roots"] + tree["orphans"]:
        for _, span in walk(root):
            yield span


def locate(case, row, tree, current):
    source = case["expected"]["source"]
    served = next((s for s in spans(tree) if s["service"] == "retrieval"), None)
    if served is None:
        return {"step": "trace", "detail": "no retrieval service span joined this trace"}
    context = next(s for s in spans(tree) if s["name"] == "assemble context")["attributes"]
    passages = {p["id"]: p for p in served["attributes"]["app.retrieval.passages"]}
    if source not in passages:
        return {"step": "retrieval",
                "detail": f"{source} was not in the top {served['attributes']['gen_ai.retrieval.top_k']}"}
    if passages[source]["version"] < int(current[source]):
        return {"step": "index", "detail": f"{source} was served at version {passages[source]['version']}; "
                                           f"the current version is {current[source]}"}
    dropped = {d["id"]: d["rank"] for d in context["app.context.dropped"]}
    if source in dropped:
        return {"step": "context assembly", "detail": f"{source} was retrieved at rank {dropped[source]} and "
                                                      f"dropped by the limit of {context['app.context.limit']} passages"}
    return {"step": "model", "detail": f"{source} was in the context; the answer failed {row['check']}: {row['reason']}"}


def diagnose(run_record, cases, traces, current):
    by_id = {case["id"]: case for case in cases}
    rows = []
    for row in run_record["results"]:
        trace_id = row["metadata"].get("trace_id")
        if row["verdict"] == "pass" or trace_id is None:
            continue
        found = locate(by_id[row["case_id"]], row, traces[trace_id], current)
        rows.append({"case_id": row["case_id"], "trial": row["trial"], "verdict": row["verdict"],
                     "trace_id": trace_id, **found})
    return rows
