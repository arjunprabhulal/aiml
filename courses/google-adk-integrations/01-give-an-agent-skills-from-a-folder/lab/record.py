"""Run the docs assistant with its skills on Gemini and save the runs.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes recorded-runs.json and run-output.txt. The tests replay the model turns offline.
"""
import asyncio
import json
import shutil
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import agent  # noqa: E402
from google.adk.skills import load_skill_from_dir  # noqa: E402
from google.adk.tools.skill_toolset import SkillDiscoveryMode, SkillToolset  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = {
    "release": "Write the release notes for docuctl 2.4.0.",
    "unknown-version": "Write the release notes for docuctl 9.9.0.",
    "no-executor": "Write the release notes for docuctl 2.4.0.",
}


async def run(question: str, toolset=None) -> dict:
    turns, offered, instructions = [], [], []

    def keep_turn(callback_context, llm_response):
        if llm_response.content:
            content = llm_response.content.model_dump(mode="json", exclude_none=True)
            for part in content.get("parts", []):
                part.pop("thought_signature", None)
            turns.append(content)

    def keep_request(callback_context, llm_request):
        offered.append(sorted(d.name for t in llm_request.config.tools or [] for d in t.function_declarations or []))
        instructions.append(llm_request.config.system_instruction)

    recording = agent.build_agent(toolset=toolset).clone(update={
        "after_model_callback": keep_turn, "before_model_callback": keep_request})
    events = await agent.ask(question, recording)
    return {"question": question, "transcript": agent.show(events), "model_turns": turns,
            "offered_per_request": offered, "system_instruction": instructions[0]}


def failure_name_mismatch() -> str:
    """A skill folder whose name differs from the name in its SKILL.md frontmatter."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "release_notes"
        shutil.copytree(HERE / "skills" / "release-notes", target)
        try:
            load_skill_from_dir(target)
        except ValueError as error:
            return f"{type(error).__name__}: {error}"
    return "loaded"


async def main() -> None:
    record = {"model": agent.MODEL, "skills": [s.name for s in agent.load_skills_from_dir(HERE / "skills")], "runs": {}}
    record["runs"]["release"] = await run(QUESTIONS["release"])
    eager = SkillToolset(skills=agent.load_skills_from_dir(HERE / "skills"),
                         code_executor=agent.UnsafeLocalCodeExecutor(), script_timeout=30,
                         additional_tools=[agent.list_merged_prs], discovery_mode=SkillDiscoveryMode.EAGER)
    record["runs"]["eager"] = await run(QUESTIONS["release"], eager)
    record["runs"]["unknown-version"] = await run(QUESTIONS["unknown-version"])
    record["runs"]["no-executor"] = await run(QUESTIONS["no-executor"], agent.skills_toolset(run_scripts=False))
    record["failures"] = {"name_mismatch": failure_name_mismatch()}
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out = []
    for key, r in record["runs"].items():
        out.append(f'$ python agent.py "{r["question"]}"   # run: {key}\n{r["transcript"]}\n')
    out.append(f"$ load_skill_from_dir(skills copied to release_notes/)\n{record['failures']['name_mismatch']}\n")
    (HERE / "run-output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    for key, r in record["runs"].items():
        print(key, r["offered_per_request"])


if __name__ == "__main__":
    asyncio.run(main())
