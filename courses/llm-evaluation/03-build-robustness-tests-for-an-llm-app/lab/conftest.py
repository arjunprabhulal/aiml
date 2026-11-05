"""Fixtures for the robustness suite: the datasets and one cassette for every model call."""
import hashlib
import os
from pathlib import Path

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
from harness import Cassette, load_dataset  # noqa: E402
from triage import MODEL, PROMPT, PROMPT_VERSION, Triage, triage  # noqa: E402

HERE = Path(__file__).parent
DATASET = load_dataset(HERE / "dataset.json")
ADVERSARIAL = load_dataset(HERE / "adversarial.json")
KEY = {"datasets": [DATASET.sha, ADVERSARIAL.sha], "model": MODEL, "prompt_version": PROMPT_VERSION,
       "prompt_sha": hashlib.sha256(PROMPT.encode()).hexdigest()[:12]}


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="call the model and rewrite the recording")


@pytest.fixture(scope="session")
def cassette(request):
    live = request.config.getoption("--live")
    tape = Cassette(HERE / "recordings" / f"{MODEL.replace(':', '-')}-{PROMPT_VERSION}.json", KEY, live)
    yield tape
    if live:
        tape.save()


@pytest.fixture
def run_triage(cassette):
    """Triage one text. The entry name includes a hash of the text, so a changed perturbation needs a new recording."""
    def call(name: str, text: str) -> Triage:
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        return Triage.model_validate_json(cassette.get(f"{name}/{digest}", lambda: triage(text)))
    return call


@pytest.hookimpl(optionalhook=True)
def pytest_json_modifyreport(json_report):
    for field in ("environment", "root"):
        json_report.pop(field, None)
    json_report["eval"] = KEY
