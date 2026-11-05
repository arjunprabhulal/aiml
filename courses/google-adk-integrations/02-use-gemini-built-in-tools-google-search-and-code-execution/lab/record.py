"""Run the docs assistant with Gemini's built-in tools and save the runs.

Run from this folder with GOOGLE_API_KEY set: python record.py
Writes recorded-runs.json and run-output.txt. The tests replay the model responses offline.
"""
import asyncio
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import agent  # noqa: E402
from google.adk.models.lite_llm import LiteLlm  # noqa: E402
from google.adk.tools.google_search_tool import GoogleSearchTool  # noqa: E402

HERE = Path(__file__).resolve().parent
QUESTIONS = {
    "pin": "Is the google-adk pin on the dependencies page current?",
    "slo": "Do the deploy timings meet the SLO?",
}


async def run(question: str, assistant=None) -> dict:
    responses, requests = [], []

    def keep_response(callback_context, llm_response):
        responses.append(llm_response.model_dump(
            mode="json", exclude_none=True, include={"content", "grounding_metadata"}))

    def keep_request(callback_context, llm_request):
        config = llm_request.config
        requests.append({
            "tools": [sorted(k for k, v in t.model_dump(exclude_none=True).items() if v is not None) for t in config.tools or []],
            "tool_config": config.tool_config.model_dump(mode="json", exclude_none=True) if config.tool_config else None,
        })

    recording = (assistant or agent.build_agent()).clone(update={
        "after_model_callback": keep_response, "before_model_callback": keep_request})
    events = await agent.ask(question, recording)
    for r in responses:  # thought signatures are opaque and change per call
        for part in r.get("content", {}).get("parts", []):
            part.pop("thought_signature", None)
    entry = [r["grounding_metadata"] for r in responses if r.get("grounding_metadata", {}).get("search_entry_point")]
    return {"question": question, "transcript": agent.show(events), "sources": agent.sources(events),
            "citations": agent.citations(events),
            "requests": requests, "responses": responses,
            "rendered_content_chars": len(entry[-1]["search_entry_point"].get("rendered_content", "")) if entry else 0}


async def failure(assistant, question: str) -> str:
    try:
        await agent.ask(question, assistant)
    except Exception as error:  # noqa: BLE001 - the recording keeps whatever the API or ADK raised
        return f"{type(error).__name__}: {error}"
    return "no error"


async def main() -> None:
    record = {"model": agent.MODEL, "runs": {}}
    for key, question in QUESTIONS.items():
        record["runs"][key] = await run(question)
    bypass = agent.build_agent(combine=False, code=False,
                               tools=[agent.read_page, GoogleSearchTool(bypass_multi_tools_limit=True)])
    record["runs"]["bypass"] = await run(QUESTIONS["pin"], bypass)
    record["failures"] = {
        "no_flag": await failure(agent.build_agent(combine=False), QUESTIONS["pin"]),
        "gemma": await failure(agent.build_agent(LiteLlm(model="ollama_chat/gemma4:e2b"), code=False), QUESTIONS["pin"]),
    }
    (HERE / "recorded-runs.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out = []
    for key, r in record["runs"].items():
        out.append(f'$ python agent.py "{r["question"]}"   # run: {key}\n{r["transcript"]}\n')
    for key, message in record["failures"].items():
        out.append(f"# failure: {key}\n{message}\n")
    (HERE / "run-output.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print(json.dumps({k: r["requests"] for k, r in record["runs"].items()}, indent=1))


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=180))
