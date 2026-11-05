"""The docs assistant answers questions about docs traffic from BigQuery through BigQueryToolset."""
import asyncio
import os
import sys

import google.auth
from google.auth.transport.requests import Request
from google.adk import Agent, Runner
from google.adk.integrations.bigquery import BigQueryCredentialsConfig, BigQueryToolset
from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode
from google.adk.sessions import InMemorySessionService
from google.genai import types

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
DATASET = os.environ.get("DOCS_ANALYTICS_DATASET", "aiml_docs_analytics")
MODEL = os.environ.get("DOCS_MODEL", "gemini-3.8-flash")
READ_TOOLS = ["list_table_ids", "get_table_info", "execute_sql"]


def tool_config(**overrides) -> BigQueryToolConfig:
    """The limits ADK enforces on every query, whatever the model writes."""
    settings = dict(
        write_mode=WriteMode.BLOCKED,          # dry-run first; only SELECT statements run
        maximum_bytes_billed=10 * 1024 * 1024,  # 10 MiB, the minimum accepted by this ADK config
        max_query_result_rows=50,
        compute_project_id=PROJECT,             # jobs run and bill only in this project
        default_project_id=PROJECT,
        default_dataset_id=DATASET,
        location="US",
        job_labels={"aiml-lesson": "query-bigquery-with-bigquerytoolset"},
    )
    settings.update(overrides)
    return BigQueryToolConfig(**settings)


def bigquery(config: BigQueryToolConfig | None = None, tool_filter: list[str] | None = READ_TOOLS,
             credentials=None) -> BigQueryToolset:
    # Application Default Credentials: `gcloud auth application-default login` locally,
    # the attached service account on Cloud Run or Agent Runtime.
    if credentials is None:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/bigquery"])
        # Fresh ADC can have neither a token nor expiry; refresh before ADK checks validity.
        if not credentials.valid:
            credentials.refresh(Request())
    return BigQueryToolset(
        credentials_config=BigQueryCredentialsConfig(credentials=credentials),
        bigquery_tool_config=config or tool_config(),
        tool_filter=tool_filter,
    )


def build_agent(model=None, toolset: BigQueryToolset | None = None) -> Agent:
    return Agent(
        name="docs_analyst",
        model=model or MODEL,
        instruction=f"""You answer questions about how developers use the docuctl docs.
The data is in the BigQuery dataset {DATASET}: page views per page per day, and weekly site searches
with how many results each returned. Look at the table schema before you write SQL, and select
only the columns you need. Report the numbers the query returned; do not estimate.""",
        tools=[toolset or bigquery()],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, thinking_config=types.ThinkingConfig(thinking_level="low")),
    )


async def ask(text: str, agent: Agent | None = None) -> list:
    sessions = InMemorySessionService()
    runner = Runner(app_name="docs", agent=agent or build_agent(), session_service=sessions)
    try:
        session = await sessions.create_session(app_name="docs", user_id="dev")
        message = types.Content(role="user", parts=[types.Part(text=text)])
        return [e async for e in runner.run_async(user_id="dev", session_id=session.id, new_message=message)]
    finally:
        await runner.close()


def show(events: list) -> str:
    lines = []
    for event in events:
        for call in event.get_function_calls():
            lines.append(f"call   {call.name} {call.args}")
        for result in event.get_function_responses():
            text = str(result.response)
            lines.append(f"result {result.name} {text if len(text) <= 400 else text[:400] + ' ...'}")
        if event.is_final_response() and event.author != "user" and event.content:
            lines.append("answer " + "".join(p.text or "" for p in event.content.parts if not p.thought).strip())
    return "\n".join(lines)


async def list_tools(tool_filter: list[str] | None = READ_TOOLS, credentials=None) -> list[str]:
    return [tool.name for tool in await bigquery(tool_filter=tool_filter, credentials=credentials).get_tools()]


if __name__ == "__main__":
    if sys.argv[1:] == ["--tools"]:
        print(asyncio.run(list_tools()))
    else:
        print(show(asyncio.run(ask(" ".join(sys.argv[1:])))))
