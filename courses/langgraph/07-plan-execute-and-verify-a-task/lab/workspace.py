"""File tools confined to one workspace folder, and the checks that read the folder afterwards."""
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool


def make_tools(root: Path) -> list:
    def inside(path: str) -> Path | None:
        target = (root / path).resolve()
        return target if target.is_relative_to(root.resolve()) else None

    @tool
    def read_file(path: str) -> str:
        """Read a text file in the workspace, for example CHANGELOG.md."""
        target = inside(path)
        if target is None:
            return f"Refused: {path} is outside the workspace."
        return target.read_text() if target.is_file() else f"No file {path}."

    @tool
    def write_file(path: str, content: str) -> str:
        """Replace the whole content of a text file in the workspace, creating folders as needed."""
        target = inside(path)
        if target is None:
            return f"Refused: {path} is outside the workspace."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"Wrote {len(content)} characters to {path}."

    return [read_file, write_file]


def run_checks(root: Path, checks: list[dict], original: dict[str, str]) -> list[dict]:
    """Evaluate the task's own checks against the files on disk. Never asks the model."""
    results = []
    for check in checks:
        path = root / check["path"]
        text = path.read_text() if path.is_file() else None
        if check.get("pytest"):  # run the project's tests in the workspace
            done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", check["path"]],
                                  cwd=root, capture_output=True, text=True, timeout=60)
            ok, detail = done.returncode == 0, done.stdout.strip().splitlines()[-1:]
        elif check.get("unchanged"):
            ok, detail = text == original[check["path"]], []
        else:
            ok, detail = text is not None and check["contains"] in text, []
        results.append({**check, "passed": ok, **({"detail": detail[0]} if detail else {})})
    return results
