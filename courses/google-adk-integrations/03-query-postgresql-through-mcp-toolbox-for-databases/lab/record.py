"""Start the lab, run the docs assistant against MCP Toolbox on Gemini and save the runs.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes recorded-runs.json and run-output.txt. The tests replay the model turns against a fresh lab.
"""
import asyncio
import json
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.getLogger("root").setLevel(logging.ERROR)  # toolbox-core warns on each MCP protocol fallback

import agent  # noqa: E402
from lab import Lab, config_error, free_port  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = {
    "feedback": "Which pages got the most unhelpful feedback this month, and what did readers say?",
    "delete": "Delete the feedback on the rollback page.",
}


class Keep(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage().splitlines()[0])


async def run(question: str, toolset) -> dict:
    turns, declarations, keep = [], {}, Keep()

    def keep_turn(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)

    def keep_tools(callback_context, llm_request):
        for tool in llm_request.config.tools or []:
            for d in tool.function_declarations or []:
                declarations[d.name] = d.model_dump(mode="json", exclude_none=True)

    logging.getLogger().addHandler(keep)
    recording = agent.build_agent(toolset=toolset).clone(update={
        "after_model_callback": keep_turn, "before_model_callback": keep_tools})
    try:
        events = await agent.ask(question, recording)
    finally:
        logging.getLogger().removeHandler(keep)
    return {"question": question, "transcript": agent.show(events), "model_turns": turns,
            "declarations": declarations, "errors": [m for m in keep.messages if "will run without" in m]}


async def main() -> None:
    record = {"model": agent.MODEL, "toolbox": "0.21.0", "runs": {}, "failures": {}}
    with Lab() as lab:
        record["discovery"] = await agent.list_tools(lab.url)
        for key, question in QUESTIONS.items():
            record["runs"][key] = await run(question, agent.docs_db(lab.url))
        record["failures"]["unused_bound_param"] = await run(QUESTIONS["delete"], agent.docs_db(lab.url, "docs-admin"))
        record["failures"]["read_only_role"] = await run(
            QUESTIONS["delete"], agent.docs_db(lab.url, "docs-admin", bind_team=False))
        with lab.admin() as conn:
            record["feedback_rows_after"] = conn.execute("SELECT count(*) FROM feedback").fetchone()[0]
    record["config_error"] = config_error(HERE / "tools-v2-format.yaml")
    record["failures"]["server_down"] = await run(
        QUESTIONS["feedback"], agent.docs_db(f"http://127.0.0.1:{free_port()}"))
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out = [f"$ python agent.py --tools\n{record['discovery']}\n"]
    for key, r in [*record["runs"].items(), *record["failures"].items()]:
        errors = "".join(f"ERROR {m}\n" for m in r["errors"])
        out.append(f'$ python agent.py "{r["question"]}"   # run: {key}\n{errors}{r["transcript"]}\n')
    out.append(f"$ toolbox --tools-file tools-v2-format.yaml\nERROR {record['config_error']}\n")
    (HERE / "run-output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print("feedback rows after:", record["feedback_rows_after"])
    print(json.dumps(record["runs"]["feedback"]["declarations"], indent=1))


if __name__ == "__main__":
    asyncio.run(main())
