"""Ask the pinned model which tool calls to make, live through Ollama or replayed from a recording.

The model only proposes calls. Nothing here runs a tool; boundary.py decides.
A replayed answer is looked up by the SHA-256 of the exact request, so a changed
prompt, tool list or setting cannot reuse an old recording.
"""
import hashlib
import json
from pathlib import Path
from urllib import request as urlrequest

HERE = Path(__file__).resolve().parent
MODEL = json.loads((HERE / "model.json").read_text(encoding="utf-8"))
INSTRUCTIONS = ("You are a support agent for an online shop. Use the tools to answer or act on the "
                "customer's request. Call a tool for every order the request names.")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_for(message, tools):
    return {"model": MODEL["ollama_tag"], "stream": False, "think": MODEL["think"],
            "messages": [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": message}],
            "tools": [{"type": "function", "function": {"name": name, "description": rule["description"],
                                                        "parameters": rule["input_schema"]}}
                      for name, rule in sorted(tools.items())],
            "options": {**MODEL["options"], "seed": MODEL["seed"]}}


def proposals(raw):
    """The tool calls in a chat reply, as {"name", "arguments"} objects."""
    return [{"name": call["function"]["name"], "arguments": call["function"]["arguments"]}
            for call in (raw.get("message", {}).get("tool_calls") or [])]


class OllamaModel:
    def __init__(self, base_url="http://127.0.0.1:11434"):
        self.base_url, self.recorded = base_url, {}
        with urlrequest.urlopen(base_url + "/api/tags", timeout=30) as response:
            installed = {m["name"]: m["digest"] for m in json.load(response)["models"]}
        if installed.get(MODEL["ollama_tag"]) != MODEL["ollama_digest"]:
            raise RuntimeError(f"{MODEL['ollama_tag']} is missing or not the pinned digest")

    def propose(self, payload):
        req = urlrequest.Request(self.base_url + "/api/chat", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
        with urlrequest.urlopen(req, timeout=600) as response:
            raw = json.load(response)
        kept = {"content": raw["message"].get("content", ""), "tool_calls": proposals(raw),
                "done_reason": raw.get("done_reason"), "prompt_eval_count": raw.get("prompt_eval_count"),
                "eval_count": raw.get("eval_count")}
        self.recorded[hashlib.sha256(canonical(payload).encode()).hexdigest()] = kept
        return kept


class ReplayModel:
    def __init__(self, path):
        recording = json.loads(Path(path).read_text(encoding="utf-8"))
        if recording["model"] != MODEL:
            raise RuntimeError("recording was made with a different model pin")
        self.calls = recording["calls"]

    def propose(self, payload):
        try:
            return self.calls[hashlib.sha256(canonical(payload).encode()).hexdigest()]
        except KeyError:
            raise LookupError("no recorded response for this exact request") from None
