"""Inbox triage by a local model, sampled: the system the benchmark repeats.

Each trial sends one message to a local Ollama model at temperature 1 with a
seed that depends only on the trial number, and asks for JSON that matches the
triage task's output fields. Input is checked before any model call, so blank
or missing text raises the same rejections as the keyword rules in the harness
build. A reply cut off at the token limit raises TruncatedReply, and a reply
that is not JSON raises json.JSONDecodeError: both become incomplete trials.
Python standard library only.
"""
import hashlib
import json
import urllib.request

from harness import Answer
from triage_task import CATEGORIES

OLLAMA = "http://127.0.0.1:11434"
# Tag -> first 12 hex digits of the digest the recordings were made with.
MODELS = {"gemma4:e2b": "b37049369adf", "qwen3.5:0.8b": "de63045f2975"}
TEMPERATURE = 1.0
NUM_PREDICT = 64
SEED_BASE = 1000  # Trial t uses seed 1000 + t, the same for every case and model.
PROMPT = (
    "Classify one customer message for an online shop's support inbox. Reply with JSON only.\n"
    "category: billing (charges, refunds, payments), delivery (orders on their way, tracking, arrival), "
    "account (signing in, passwords, account access), or other (anything else).\n"
    "needs_human: true when the message suggests that someone else used or changed the customer's account; "
    "otherwise false.")
SCHEMA = {"type": "object", "required": ["category", "needs_human"],
          "properties": {"category": {"type": "string", "enum": list(CATEGORIES)},
                         "needs_human": {"type": "boolean"}}}


class TruncatedReply(RuntimeError):
    """The model stopped at the token limit, so its reply is incomplete."""


def post(path, body, timeout=120):
    request = urllib.request.Request(f"{OLLAMA}{path}", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def get(path):
    with urllib.request.urlopen(f"{OLLAMA}{path}", timeout=10) as response:
        return json.loads(response.read())


class ModelTriage:
    """A harness system: name, version, mode, model, prompt and tools, plus respond(case, trial)."""

    mode = "live"
    tools = None

    def __init__(self, tag):
        self.tag, self.name, self.version = tag, f"model-triage-{tag.split(':')[0]}", "1"
        self.model = f"{tag}@{MODELS[tag]}"
        self.prompt = f"triage-v1 sha256:{hashlib.sha256(PROMPT.encode()).hexdigest()[:16]}"
        self.server = None

    def check_model(self):
        """Refuse to run if the installed weights differ from the pinned digest."""
        digests = {m["name"]: m["digest"] for m in get("/api/tags")["models"]}
        if not digests.get(self.tag, "").startswith(MODELS[self.tag]):
            raise RuntimeError(f"{self.tag} is not installed with digest {MODELS[self.tag]}")
        self.server = get("/api/version")["version"]

    def seed_for(self, trial):
        return SEED_BASE + trial

    def chat(self, message, seed):
        return post("/api/chat", {
            "model": self.tag, "stream": False, "think": False, "format": SCHEMA,
            "options": {"temperature": TEMPERATURE, "seed": seed, "num_predict": NUM_PREDICT},
            "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": message}]})

    def respond(self, case, trial):
        message = case["input"]
        if not isinstance(message, str):
            raise ValueError("message is not text")
        if not message.strip():
            raise ValueError("message is blank")
        if self.server is None:
            self.check_model()
        seed = self.seed_for(trial)
        result = self.chat(message, seed)
        metadata = {"seed": seed, "temperature": TEMPERATURE, "ollama": self.server,
                    "eval_count": result.get("eval_count"), "done_reason": result.get("done_reason")}
        if result.get("done_reason") == "length":
            raise TruncatedReply(f"reply stopped at {NUM_PREDICT} tokens")
        return Answer(json.loads(result["message"]["content"]), metadata)


gemma = ModelTriage("gemma4:e2b")
qwen = ModelTriage("qwen3.5:0.8b")
