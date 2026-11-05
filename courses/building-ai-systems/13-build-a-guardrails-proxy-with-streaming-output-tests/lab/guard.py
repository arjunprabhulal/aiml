"""Output guardrails for a streamed model answer. Python standard library only.

A model streams its answer in small chunks, often one token each. A value such as
an email address or a card number arrives spread over several chunks, so a check
that looks at one chunk at a time never sees it whole.

StreamGuard holds back the end of the text that could still become part of a value:
the trailing run of characters an email address can contain, and the trailing run of
digits, spaces and hyphens that a card number can contain. Everything before that
run is final, because no later chunk can change it. The guard looks for complete
values in the final text and releases it.

Two actions:
  redact  replace each value with a marker, such as [email removed]
  block   stop at the first value: release the text before it, then end the stream

Text already released cannot be recalled; that is why nothing that might still grow
into a value is released early.
"""
import re

RULES = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
    "card": re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
}
MARKERS = {"email": "[email removed]", "card": "[card removed]"}
EMAIL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-@")
CARD_CHARS = frozenset("0123456789 -")


def luhn_ok(digits):
    """The Luhn mod-10 checksum. The card rule requires it, so most other long digit runs are left alone."""
    total, double = 0, False
    for char in reversed(digits):
        value = int(char) * (2 if double else 1)
        total += value - 9 if value > 9 else value
        double = not double
    return total % 10 == 0


def find(text):
    """Every complete value in text, as (start, end, rule), in order."""
    found = []
    for rule, pattern in RULES.items():
        for match in pattern.finditer(text):
            if rule == "card" and not luhn_ok(re.sub(r"\D", "", match.group())):
                continue  # a long order number is not a card number
            found.append((match.start(), match.end(), rule))
    return sorted(found)


def pending_start(text):
    """Where the trailing text that could still grow into a value begins."""
    email = len(text)
    while email and text[email - 1] in EMAIL_CHARS:
        email -= 1
    card = len(text)
    while card and text[card - 1] in CARD_CHARS:
        card -= 1
    digits = [i for i in range(card, len(text)) if text[i].isdigit()]
    card = digits[0] if digits else len(text)  # trailing spaces alone can be released
    return min(email, card)


class StreamGuard:
    def __init__(self, action="redact"):
        if action not in ("redact", "block"):
            raise ValueError("action must be redact or block")
        self.action, self.buffer, self.findings, self.blocked = action, "", [], None
        self.max_held = 0

    def _release(self, final):
        """Return the text that is final now, with values redacted; keep the rest."""
        text = self.buffer
        safe = len(text) if final else pending_start(text)
        values = find(text)
        for start, end, _ in reversed(values):
            if start < safe < end:
                safe = start  # never cut through a value that is already complete
        out, cursor = [], 0
        for start, end, rule in (v for v in values if v[1] <= safe):
            self.findings.append(rule)
            if self.action == "block":
                self.blocked, self.buffer = rule, ""
                return "".join(out) + text[cursor:start]
            out.append(text[cursor:start] + MARKERS[rule])
            cursor = end
        out.append(text[cursor:safe])
        self.buffer = text[safe:]
        return "".join(out)

    def feed(self, chunk):
        if self.blocked:
            return ""
        self.buffer += chunk
        self.max_held = max(self.max_held, len(self.buffer))  # Peak buffer before release, including this chunk.
        return self._release(final=False)

    def finish(self):
        return "" if self.blocked else self._release(final=True)


def per_chunk_filter(chunks):
    """The naive filter: redact values found inside each chunk on its own."""
    out = []
    for chunk in chunks:
        for start, end, rule in reversed(find(chunk)):
            chunk = chunk[:start] + MARKERS[rule] + chunk[end:]
        out.append(chunk)
    return "".join(out)


def guarded(chunks, action="redact"):
    """Run a whole stream through a StreamGuard; return (released pieces, guard)."""
    guard = StreamGuard(action)
    pieces = [guard.feed(chunk) for chunk in chunks]
    pieces.append(guard.finish())
    return pieces, guard
