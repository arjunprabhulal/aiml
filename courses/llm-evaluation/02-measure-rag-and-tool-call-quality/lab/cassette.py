"""Record/replay for model, agent and judge calls, keyed to what produced them."""
import json
from pathlib import Path


class RecordingError(RuntimeError):
    pass


class Cassette:
    def __init__(self, path: Path, key: dict, live: bool):
        self.path, self.key, self.live = Path(path), key, live
        self.entries: dict = {}
        if live:
            return
        if not self.path.exists():
            raise RecordingError(f"no recording {self.path.name}; run with --live")
        recorded = json.loads(self.path.read_text())
        changed = sorted(k for k in key.keys() | recorded["key"].keys() if recorded["key"].get(k) != key.get(k))
        if changed:
            raise RecordingError(f"recording is stale: {', '.join(changed)} changed; run with --live")
        self.entries = recorded["entries"]

    def get(self, name: str, produce):
        if self.live:
            self.entries[name] = produce()
        elif name not in self.entries:
            raise RecordingError(f"recording has no entry {name!r}; run with --live")
        return self.entries[name]

    def save(self):
        body = {"key": self.key, "entries": self.entries}
        self.path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
