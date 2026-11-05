"""Task definition for grounded support answers: output fields, expected outcomes and graders.

Loaded by the evaluation harness with --task grounded_task. A case expects one
fact, as a regular expression the answer must match, and the ID of the document
that holds it. The provenance grader runs before the fact grader, so an answer
that cites a stale or missing passage fails on provenance even when it guesses
the fact.
"""
import re

NAME = "grounded-support"
VERSION = "1"
PROVENANCE = ("supported", "uncited", "stale", "not_in_context", "unknown")
OUTPUT_FIELDS = {"answer": str, "cited": str, "provenance": str}


def validate_expected(expected):
    if set(expected) != {"fact", "source"} or not all(isinstance(v, str) and v for v in expected.values()):
        raise ValueError("expected must be exactly a fact pattern and a source document ID")
    try:
        re.compile(expected["fact"])
    except re.error as error:
        raise ValueError(f"fact is not a valid regular expression: {error}") from None


def contract_check(case, output):
    if not isinstance(output, dict) or set(output) != set(OUTPUT_FIELDS):
        return False, f"output must have exactly {sorted(OUTPUT_FIELDS)}"
    if not all(isinstance(output[k], str) for k in OUTPUT_FIELDS) or output["provenance"] not in PROVENANCE:
        return False, "answer and cited must be text, and provenance one of the known verdicts"
    return True, ""


def provenance_check(case, output):
    source = case["expected"]["source"]
    if output["provenance"] != "supported":
        return False, f"provenance {output['provenance']}"
    if source not in output["cited"].split(","):
        return False, f"does not cite {source}"
    return True, ""


def fact_check(case, output):
    if not re.search(case["expected"]["fact"], output["answer"], re.IGNORECASE):
        return False, f"answer does not state {case['expected']['fact']!r}"
    return True, ""


GRADERS = (
    {"name": "grounded-contract", "version": "1", "kind": "contract", "check": contract_check},
    {"name": "grounded-provenance", "version": "1", "kind": "outcome", "check": provenance_check},
    {"name": "grounded-fact", "version": "1", "kind": "outcome", "check": fact_check},
)
