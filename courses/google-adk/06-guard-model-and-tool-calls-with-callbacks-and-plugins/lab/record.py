"""Record the guarded docs assistant on Gemini: what the model receives and what the session stores.

Run from this folder with GOOGLE_API_KEY set: python record.py --record
Writes recorded-runs.json and run-output.txt. The tests replay the model turns offline.
"""
# This comparison makes multiple provider calls and replaces historical files.
# Refuse before importing the SDK or touching any existing record.
import sys
if __name__ == "__main__" and sys.argv[1:] != ["--record"]:
    raise SystemExit("recording is opt-in: use python record.py --record in a separate copy")

import asyncio
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import guarded  # noqa: E402

HERE = Path(__file__).resolve().parent
PASTED = (HERE / "workspace" / "docuctl.toml").read_text(encoding="utf-8")
QUESTIONS = {
    "pasted": f"Our staging deploy fails. Here is docuctl.toml:\n{PASTED}\nWhat is wrong with it?",
    "read": "Read docuctl.toml and check it against the config docs.",
    "outside": "Our previous config is in ../workspace-old/docuctl.toml. Read it and compare it with docuctl.toml.",
}


async def run(key: str, plugins=None) -> dict:
    turns, requests = [], []

    def keep_turn(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)

    def keep_request(callback_context, llm_request):
        requests.append([p.text or json.dumps(p.function_response.response if p.function_response else {})
                         for c in llm_request.contents for p in c.parts])

    agent = guarded.root_agent.clone(update={"after_model_callback": keep_turn, "before_model_callback": keep_request})
    plugin = guarded.RedactSecrets()
    events, stored = await guarded.ask(guarded.build_app(agent, [plugin] if plugins is None else plugins), QUESTIONS[key])
    stored_text = " ".join(p.text or json.dumps(p.function_response.response if p.function_response else {})
                           for e in stored if e.content for p in e.content.parts)
    return {"question": QUESTIONS[key], "transcript": guarded.show(events), "model_turns": turns,
            "redactions": plugin.redactions if plugins is None else None,
            "key_sent_to_model": any("AKIA" in t for r in requests for t in r),
            "key_in_session": "AKIA" in stored_text}


def transcript(record: dict) -> list[str]:
    out = []
    for name, r in record["runs"].items():
        app = "App without plugins" if name == "pasted-no-plugin" else "App with RedactSecrets"
        question = r["question"].replace(PASTED, "<the contents of workspace/docuctl.toml>\n")
        out.append(f"# {app}\n> {question}\n{r['transcript']}\n"
                   f"# redactions: {r['redactions']}, key sent to model: {r['key_sent_to_model']}, "
                   f"key in session: {r['key_in_session']}\n")
    return out


async def main() -> None:
    record = {"model": guarded.MODEL, "runs": {k: await run(k) for k in QUESTIONS}}
    record["runs"]["pasted-no-plugin"] = await run("pasted", plugins=[])
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out = transcript(record)
    (HERE / "run-output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    asyncio.run(main())
