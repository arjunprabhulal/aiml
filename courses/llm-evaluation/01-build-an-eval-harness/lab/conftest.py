"""Fixtures for the triage eval: the dataset, the cassette and the judge model."""
import hashlib
import os
from functools import cache
from pathlib import Path

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
from deepeval.models import GeminiModel, OllamaModel  # noqa: E402

from harness import Cassette, load_dataset  # noqa: E402
from triage import MODEL, PROMPT, PROMPT_VERSION, Triage, triage  # noqa: E402

DATASET = load_dataset()
JUDGE_MODEL = MODEL
KEY = {
    "dataset": f"{DATASET.name}@{DATASET.version}",
    "dataset_sha": DATASET.sha,
    "model": MODEL,
    "prompt_version": PROMPT_VERSION,
    "prompt_sha": hashlib.sha256(PROMPT.encode()).hexdigest()[:12],
    "judge_model": JUDGE_MODEL,
}


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="call the model and rewrite the recording")


@pytest.fixture(scope="session")
def cassette(request):
    live = request.config.getoption("--live")
    name = f"{MODEL.replace(':', '-')}-{PROMPT_VERSION}.json"
    tape = Cassette(Path(__file__).with_name("recordings") / name, KEY, live)
    yield tape
    if live:
        tape.save()


@pytest.fixture
def raw_output(case, cassette):
    return cassette.get(f"triage/{case.id}", lambda: triage(case.issue))


@pytest.fixture
def output(raw_output):
    return Triage.model_validate_json(raw_output)


def make_judge(name: str):
    """DeepEval's judge wrapper for the model name: Gemini through the API, anything else through Ollama."""
    if name.startswith("gemini"):
        return GeminiModel(model=name)
    return OllamaModel(model=name, base_url="http://localhost:11434", temperature=0)


@pytest.fixture(scope="session")
def judge():
    """Builds the judge on first use, so a replay needs no API key."""
    return cache(lambda: make_judge(JUDGE_MODEL))


@pytest.hookimpl(optionalhook=True)
def pytest_json_modifyreport(json_report):
    # Keep the run record about the eval, not about the machine that ran it.
    for field in ("environment", "root"):
        json_report.pop(field, None)
    json_report["eval"] = KEY
