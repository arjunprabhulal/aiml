"""Task definition for inbox triage: output fields, expected outcomes and graders.

The harness core knows nothing about triage. It loads this module with
--task triage_task, validates cases with OUTPUT_FIELDS and validate_expected,
runs GRADERS in order, and records this file's SHA-256 in every run record.
"""
NAME = "inbox-triage"
VERSION = "1"
CATEGORIES = ("billing", "delivery", "account", "other")
# Field name -> required type. fail_if conditions may only name these fields.
OUTPUT_FIELDS = {"category": str, "needs_human": bool}


def validate_expected(expected):
    """Raise ValueError unless a non-rejection expectation names one allowed category."""
    if set(expected) != {"category"} or expected["category"] not in CATEGORIES:
        raise ValueError(f"expected must be exactly one category from {CATEGORIES}")


def contract_check(case, output):
    if not isinstance(output, dict) or set(output) != set(OUTPUT_FIELDS):
        return False, f"output must have exactly {sorted(OUTPUT_FIELDS)}"
    if output["category"] not in CATEGORIES:
        return False, f"unknown category {output['category']!r}"
    if not isinstance(output["needs_human"], bool):
        return False, "needs_human must be true or false"
    return True, ""


def outcome_check(case, output):
    if output["category"] != case["expected"]["category"]:
        return False, f"category: expected {case['expected']['category']!r}, got {output['category']!r}"
    return True, ""


# Run in this order after the harness has handled rejections and no-output trials.
GRADERS = (
    {"name": "triage-contract", "version": "1", "kind": "contract", "check": contract_check},
    {"name": "triage-outcome", "version": "1", "kind": "outcome", "check": outcome_check},
)
