"""Two versions of the keyword-rule inbox triage used as systems under test.

Both are deterministic rules, not models. Version 2 changes three rules, each to
fix one development failure of version 1.
"""
from harness import LiveSystem


def triage_v1(message):
    text = message.strip().lower()
    if not text:
        raise ValueError("message is blank")
    if any(word in text for word in ("password", "log in", "account")):
        return {"category": "account", "needs_human": "someone" in text}
    if any(word in text for word in ("charge", "refund", "invoice")):
        return {"category": "billing", "needs_human": False}
    if any(word in text for word in ("order", "arrive", "tracking")):
        return {"category": "delivery", "needs_human": False}
    return {"category": "other", "needs_human": False}


def triage_v2(message):
    if not isinstance(message, str):  # A missing body is rejected instead of crashing.
        raise ValueError("message is not text")
    text = message.strip().lower()
    if not text:
        raise ValueError("message is blank")
    if any(word in text for word in ("charge", "refund", "invoice")):  # Billing words come first.
        return {"category": "billing", "needs_human": False}
    if any(word in text for word in ("password", "log in", "account")):
        flagged = "someone" in text or "without my permission" in text  # One more review phrase.
        return {"category": "account", "needs_human": flagged}
    if any(word in text for word in ("order", "arrive", "tracking")):
        return {"category": "delivery", "needs_human": False}
    return {"category": "other", "needs_human": False}


baseline = LiveSystem("keyword-triage", "1", triage_v1)
candidate = LiveSystem("keyword-triage", "2", triage_v2)
