"""A policy boundary between untrusted content and the tools an agent may call. Standard library only.

Tool outputs, retrieved notes and messages handed over by another agent are data. A
model that has read them may still propose calls they asked for, so every proposed
call passes this boundary before it runs:

  trusted values   a page ID or reviewer address in a sensitive argument must be a
                   value the application holds for the signed-in user (their pages,
                   their reviewer), never one that only appeared in untrusted content
  taint            once untrusted text has entered the conversation, a call that changes
                   published documentation is held for a person instead of running
  handoff schema   a handoff from another agent carries exactly from, task, page_id and
                   summary, all text; anything else, such as a permissions field, is
                   refused before it reaches the model. Every field of a handoff that
                   passes is still untrusted text, not only the summary

The rules decide with application data only; they never read the untrusted text for
instructions. Checking that an argument equals a trusted value is a data-flow rule, not
a detector of injected text.
"""
import json

HANDOFF_KEYS = {"from", "task", "page_id", "summary"}
TOOLS = {
    # untrusted_output: the tool returns text the application did not write, so a result
    # that runs marks the conversation untrusted.
    "read_page_note": {"kind": "read", "description": "Read the latest documentation note on one of the caller's pages.",
                       "parameters": {"page_id": "string"}, "trusted": {"page_id": "pages"},
                       "untrusted_output": True},
    "submit_review": {"kind": "write", "description": "Prepare a review message.",
                   "parameters": {"reviewer": "string", "subject": "string", "body": "string"}, "trusted": {"reviewer": "reviewer"}},
    "publish_page": {"kind": "publishing", "description": "Propose publication of one page. Reason is correction, release or retire.",
                     "parameters": {"page_id": "string", "reason": "string"}, "trusted": {"page_id": "pages"},
                     "allowed": {"reason": ["correction", "release", "retire"]}},
}


class HandoffError(ValueError):
    """A handoff that breaks its schema never reaches the model."""


def check_handoff(handoff):
    if not isinstance(handoff, dict) or set(handoff) != HANDOFF_KEYS:
        raise HandoffError(f"a handoff carries exactly {sorted(HANDOFF_KEYS)}")
    if not all(isinstance(value, str) for value in handoff.values()):
        raise HandoffError("handoff fields must be text")
    return handoff


class Boundary:
    def __init__(self, account):
        self.account = account
        self.trusted = {"pages": set(account["pages"]), "reviewer": {account["reviewer"]}}
        self.tainted, self.decisions = False, []

    def mark_untrusted(self, source):
        """Untrusted text entered the conversation: from now on, publishing moves only after review."""
        self.tainted = True
        self.decisions.append({"event": "untrusted content", "source": source})

    def decide(self, call):
        """Return (decision, rule, reason) for one proposed call."""
        name = call.get("name") if isinstance(call, dict) else None
        if not (isinstance(name, str) and name in TOOLS):
            return "refused", "known tool", f"unknown tool {name!r}"
        tool = TOOLS[name]
        arguments = call.get("arguments")
        if not isinstance(arguments, dict) or set(arguments) != set(tool["parameters"]):
            return "refused", "arguments", f"arguments must be exactly {sorted(tool['parameters'])}"
        if not all(isinstance(value, str) for value in arguments.values()):
            return "refused", "arguments", "every argument must be text"
        for field, source in tool["trusted"].items():
            if arguments[field] not in self.trusted[source]:
                return "refused", "trusted values", f"{field} {arguments[field]!r} is not one of the caller's {source}"
        for field, values in tool.get("allowed", {}).items():
            if arguments[field] not in values:
                return "refused", "reason", f"{field} must be one of {', '.join(values)}"
        if tool["kind"] == "publishing" and self.tainted:
            return "held for review", "taint", "untrusted content is in the conversation; a person must approve a publication"
        return "allowed", None, None

    def record(self, call, decision, rule, reason):
        self.decisions.append({"call": call, "decision": decision, "rule": rule, "reason": reason})
        return decision


def describe(decision, rule, reason):
    return json.dumps({"decision": decision, "rule": rule, "reason": reason})
