"""Two proposed changes to version 2 of the triage rules, for the regression gate.

Both are keyword rules, not models. Version 3a adds Spanish keywords. Version 3b
is a refactor that drops the special review phrase "without my permission".
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


def triage_v3_spanish(message):
    return _triage(message,
                   billing=("charge", "refund", "invoice", "cobr", "reembolso", "pago"),
                   account=("password", "log in", "account", "contraseña", "cuenta", "iniciar sesión"),
                   delivery=("order", "arrive", "tracking", "pedido", "llegó", "llegado", "paquete", "seguimiento"),
                   review_phrases=("someone", "without my permission", "sin mi permiso", "desconocido"))


def triage_v3_refactor(message):
    return _triage(message,
                   billing=("charge", "refund", "invoice"),
                   account=("password", "log in", "account"),
                   delivery=("order", "arrive", "tracking"),
                   review_phrases=("someone",))


spanish = LiveSystem("keyword-triage", "3a", triage_v3_spanish)
refactor = LiveSystem("keyword-triage", "3b", triage_v3_refactor)
