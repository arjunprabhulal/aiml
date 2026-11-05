"""Two proposed changes to version 2 of the triage rules, for the regression gate.

Both are keyword rules, not models. Version 3a adds Spanish keywords, each
taken from a development case's translation and none from a held-out one.
Version 3b is a refactor that drops the review phrase "without my
permission".
"""
from harness import LiveSystem


def _triage(message, billing, account, delivery, review_phrases):
    if not isinstance(message, str):
        raise ValueError("message is not text")
    text = message.strip().lower()
    if not text:
        raise ValueError("message is blank")
    if any(word in text for word in billing):
        return {"category": "billing", "needs_human": False}
    if any(word in text for word in account):
        return {"category": "account", "needs_human": any(phrase in text for phrase in review_phrases)}
    if any(word in text for word in delivery):
        return {"category": "delivery", "needs_human": False}
    return {"category": "other", "needs_human": False}


# Every Spanish keyword occurs in a development case's translation; a test checks it.
SPANISH = {"billing": ("cobr", "reembolso"), "account": ("contraseña", "cuenta"),
           "delivery": ("pedido", "llegó", "llegado", "seguimiento"), "review_phrases": ("sin mi permiso",)}


def triage_v3_spanish(message):
    return _triage(message,
                   billing=("charge", "refund", "invoice", *SPANISH["billing"]),
                   account=("password", "log in", "account", *SPANISH["account"]),
                   delivery=("order", "arrive", "tracking", *SPANISH["delivery"]),
                   review_phrases=("someone", "without my permission", *SPANISH["review_phrases"]))


def triage_v3_refactor(message):
    return _triage(message,
                   billing=("charge", "refund", "invoice"),
                   account=("password", "log in", "account"),
                   delivery=("order", "arrive", "tracking"),
                   review_phrases=("someone",))


spanish = LiveSystem("keyword-triage", "3a", triage_v3_spanish)
refactor = LiveSystem("keyword-triage", "3b", triage_v3_refactor)
