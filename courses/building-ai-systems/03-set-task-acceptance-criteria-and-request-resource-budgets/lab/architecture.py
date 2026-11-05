"""A local documentation lookup and action-proposal workflow; no model or network."""
from dataclasses import dataclass
from pathlib import Path
import json
import re

@dataclass(frozen=True)
class Request:
    operation: str
    version: str
    environment: str
    role: str = "reader"
    release: str = ""

class Refused(ValueError):
    pass

def answer(request, pages):
    if request.role not in {"reader", "maintainer"}:
        raise Refused("unknown caller role")
    if request.environment not in {"staging", "production"}:
        raise Refused("choose staging or production")
    if request.operation not in {"lookup_rollback", "propose_rollback"}:
        raise Refused("unsupported operation: send for review")
    if request.operation == "propose_rollback" and request.role != "maintainer":
        raise Refused("maintainer role required for an action proposal")
    matches = [p for p in pages if p["version"] == request.version
               and p["environment"] == request.environment and p["topic"] == "rollback"]
    if len(matches) != 1:
        raise Refused("expected one matching page; review missing or conflicting evidence")
    page = matches[0]
    if request.operation == "lookup_rollback":
        return {"architecture": "filtered_lookup", "command_template": page["command"],
                "citation": page["id"], "executed": False}
    if not re.fullmatch(r"r[1-9][0-9]*", request.release):
        raise Refused("release must be an r-prefixed positive integer")
    return {"architecture": "bounded_workflow", "proposed_command":
            page["command"].replace("RELEASE", request.release), "citation": page["id"],
            "approval_required": True, "executed": False}

def naive_answer(request):
    """Deliberately inadequate baseline: ignores version and environment."""
    return "docuctl rollback RELEASE --env staging"

if __name__ == "__main__":
    root = Path(__file__).parent
    pages = json.loads((root / "pages.json").read_text())
    cases = json.loads((root / "cases.json").read_text())
    for case in cases:
        request = Request(**case["request"])
        try:
            result = answer(request, pages)
            result["baseline_matches_source"] = naive_answer(request) == next(
                p["command"] for p in pages if p["id"] == result["citation"])
        except Refused as error:
            result = {"refused": str(error)}
        print(json.dumps({"case": case["id"], **result}, sort_keys=True))
