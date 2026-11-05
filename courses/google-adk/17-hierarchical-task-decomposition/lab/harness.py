"""Run an ADK workflow, keep the events a reader sees, and record or replay model replies."""
import hashlib
import json
import time
from importlib.metadata import version

from google.adk.models import BaseLlm, Gemini, LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

MODEL = "gemini-3.8-flash"
# Local alternative: from google.adk.models.lite_llm import LiteLlm; LiteLlm(model="ollama_chat/gemma4:e2b")


def summarize(event) -> dict:
    """The fields of an event this course prints. Thought parts are dropped."""
    row = {"author": event.author}
    if event.node_info and event.node_info.path:
        row["node_info"] = event.node_info.model_dump(mode="json", exclude_none=True)
    if event.output is not None:
        output = event.output
        row["output"] = output.model_dump() if hasattr(output, "model_dump") else output
    if event.actions and event.actions.route is not None:
        row["route"] = event.actions.route
    if event.actions and event.actions.state_delta:
        row["state"] = dict(event.actions.state_delta)
    for part in (event.content.parts or []) if event.content else []:
        if part.thought:
            continue
        if part.text:
            row["message"] = row.get("message", "") + part.text
        if part.function_call:
            row.setdefault("calls", []).append(
                {"id": part.function_call.id, "name": part.function_call.name,
                 "args": part.function_call.args})
        if part.function_response:
            row.setdefault("responses", []).append(
                {"id": part.function_response.id, "name": part.function_response.name,
                 "response": part.function_response.response})
    return row


async def run(root, message, runner=None, session_id=None, state=None, plugins=None):
    """Send one message (text or Content) and return (rows, session_id)."""
    runner = runner or InMemoryRunner(agent=root, app_name="docs_assistant", plugins=plugins)
    if session_id is None:
        session = await runner.session_service.create_session(
            app_name=runner.app_name, user_id="dev", state=state)
        session_id = session.id
    if isinstance(message, str):
        message = types.Content(role="user", parts=[types.Part(text=message)])
    rows = []
    async for event in runner.run_async(user_id="dev", session_id=session_id, new_message=message):
        rows.append(summarize(event))
    return rows, session_id


def reply_to(call_id: str, response: dict) -> types.Content:
    """The resume message: a function response to the paused adk_request_input call."""
    return types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=call_id, name="adk_request_input", response=response))])


def environment() -> dict:
    return {"google-adk": version("google-adk"), "google-genai": version("google-genai"),
            "model": MODEL}


def last_user_text(llm_request) -> str:
    """The newest turn's text, plus a marker for each function response it carries."""
    parts = (llm_request.contents[-1].parts or []) if llm_request.contents else []
    return "".join(part.text or (f"[response {part.function_response.name}]"
                                 if part.function_response else "") for part in parts)


def history_key(llm_request) -> str:
    """A short hash of the whole conversation without call ids, which change every run.
    In an agent tree, many requests share their newest turn; the history tells them apart."""
    turns = []
    for content in llm_request.contents or []:
        for part in content.parts or []:
            if part.thought:
                continue
            if part.function_call:
                turns.append(["call", part.function_call.name, part.function_call.args])
            elif part.function_response:
                turns.append(["response", part.function_response.name,
                              part.function_response.response])
            elif part.text:
                turns.append([content.role, part.text])
    return hashlib.sha256(json.dumps(turns, sort_keys=True, default=str).encode()).hexdigest()[:12]


def system_key(llm_request) -> str:
    """A short hash of the system instruction: it tells apart agents sent the same text."""
    instruction = str(llm_request.config.system_instruction or "")
    return hashlib.sha256(instruction.encode()).hexdigest()[:12]


class RecordingLlm(BaseLlm):
    """Wraps a real model and keeps each request's newest text and the reply."""

    inner: BaseLlm
    calls: list = []

    @property
    def capabilities(self):
        return self.inner.capabilities

    async def generate_content_async(self, llm_request, stream=False):
        started = time.perf_counter()
        async for response in self.inner.generate_content_async(llm_request, stream):
            reply = response.model_dump(mode="json", exclude_none=True)
            for part in reply.get("content", {}).get("parts", []):
                part.pop("thought_signature", None)  # opaque bytes, not needed to replay
            self.calls.append({
                "system": system_key(llm_request),
                "request": last_user_text(llm_request),
                "history": history_key(llm_request),
                "reply": reply,
                "latency_s": round(time.perf_counter() - started, 2),
            })
            yield response


class ReplayLlm(BaseLlm):
    """Returns the recorded reply for each request; refuses a request it has no reply for.

    Replies are matched by system instruction and conversation history, not by order,
    because sibling sub-agents can reach the model in a different order on each run.
    Each reply is used once.
    """

    calls: list

    @property
    def capabilities(self):
        return Gemini(model=MODEL).capabilities

    async def generate_content_async(self, llm_request, stream=False):
        key = (system_key(llm_request), history_key(llm_request))
        call = next((c for c in self.calls if (c["system"], c["history"]) == key), None)
        if call is None:
            raise LookupError("no recorded reply for this request")
        self.calls.remove(call)
        yield LlmResponse.model_validate(call["reply"])


def gemini():
    return RecordingLlm(model=MODEL, inner=Gemini(model=MODEL), calls=[])
