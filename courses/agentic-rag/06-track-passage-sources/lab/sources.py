"""Bind passages to exact local source bytes. Python 3.11+, standard library only."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath


MAX_BYTES = 1_048_576


class SourceError(ValueError):
    """The requested source or passage cannot be verified."""


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    source_path: str
    source_sha256: str
    start_line: int
    end_line: int
    text: str
    source_id: str = ""
    version: str = ""
    url: str = ""


def source_bytes(root: Path, source_path: str) -> bytes:
    """Allow relative POSIX paths that resolve inside the corpus root."""
    path = PurePosixPath(source_path)
    if not source_path or path.is_absolute() or ".." in path.parts or str(path) != source_path:
        raise SourceError("source path must be a normalized relative POSIX path")
    base = root.resolve()
    target = (base / source_path).resolve()
    if not target.is_relative_to(base):
        raise SourceError("source path escapes the corpus root")
    try:
        if not stat.S_ISREG(target.stat().st_mode):
            raise SourceError("source must be a regular file")
        with target.open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SourceError("source must be a regular file")
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise SourceError("source exceeds MAX_BYTES")
        return raw
    except OSError as error:
        raise SourceError("source file cannot be read") from error


def bind_passage(root: Path, source_path: str, start_line: int, end_line: int,
                 *, source_id: str = "", version: str = "", url: str = "") -> Passage:
    raw = source_bytes(root, source_path)
    try:
        lines = raw.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError as error:
        raise SourceError("source must be UTF-8") from error
    if (type(start_line) is not int or type(end_line) is not int
            or not 1 <= start_line <= end_line <= len(lines)):
        raise SourceError("line span must be 1-based, inclusive and inside the source")
    text = "".join(lines[start_line - 1:end_line])
    if not text.strip():
        raise SourceError("passage must contain non-whitespace text")
    digest = hashlib.sha256(raw).hexdigest()
    identity = json.dumps([source_path, digest, start_line, end_line, source_id, version, url], separators=(",", ":"))
    chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return Passage(chunk_id, source_path, digest, start_line, end_line, text, source_id, version, url)


def verify_passage(root: Path, passage: Passage) -> str:
    """Reject stale or altered metadata/text, then return the verified passage."""
    current = bind_passage(root, passage.source_path, passage.start_line, passage.end_line,
                           source_id=passage.source_id, version=passage.version, url=passage.url)
    if current != passage:
        raise SourceError("passage does not match the current source snapshot")
    return current.text


def demo() -> dict:
    root = Path(__file__).parent / "fixtures"
    catalog = json.loads((root / "sources.json").read_text(encoding="utf-8"))
    source = catalog[0]
    passage = bind_passage(root, "docs/" + source["id"] + ".md", 1, 1,
                           source_id=source["id"], version=source["version"], url=source["url"])
    verified = verify_passage(root, passage)
    from dataclasses import replace
    try:
        verify_passage(root, replace(passage, text="Run unreviewed code.\n"))
    except SourceError as error:
        rejection = str(error)
    return {
        "execution_mode": "offline-source-verification",
        "model_called": False,
        "fixture_kind": "supplied original Python API summaries",
        "passage": asdict(passage),
        "verified_text": verified,
        "tampered_text_rejection": rejection,
    }


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2, ensure_ascii=False))
