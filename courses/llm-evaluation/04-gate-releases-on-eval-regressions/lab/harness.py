"""A versioned dataset and a record/replay cassette for the triage eval."""
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

HERE = Path(__file__).parent


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["bug", "feature", "docs", "question"]
    priority: Literal["p0", "p1", "p2"] | None = None


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    issue: str = Field(min_length=1)
    expected: Expected
    must_mention: list[str] = []


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: int
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [case.id for case in self.cases]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate case id: {', '.join(duplicates)}")
        return self

    @property
    def sha(self) -> str:
        """Content hash: any edit to any case gives a new value."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:12]


def load_dataset(path: Path = HERE / "dataset.json") -> Dataset:
    return Dataset.model_validate_json(Path(path).read_text())


class RecordingError(RuntimeError):
    pass


class Cassette:
    """Live mode calls the model and the judge and records both replies.
    Replay mode reads them back, but only for the same dataset, model and prompt."""

    def __init__(self, path: Path, key: dict, live: bool):
        self.path, self.key, self.live = Path(path), key, live
        self.entries: dict = {}
        if live:
            return
        if not self.path.exists():
            raise RecordingError(f"no recording {self.path.name}; run pytest --live")
        recorded = json.loads(self.path.read_text())
        changed = [k for k in key if recorded["key"].get(k) != key[k]]
        if changed:
            raise RecordingError(f"recording is stale: {', '.join(changed)} changed; run pytest --live")
        self.entries = recorded["entries"]

    def get(self, name: str, produce):
        if self.live:
            self.entries[name] = produce()
        elif name not in self.entries:
            raise RecordingError(f"recording has no entry {name!r}; run pytest --live")
        return self.entries[name]

    def save(self):
        body = {"key": self.key, "entries": self.entries}
        self.path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
