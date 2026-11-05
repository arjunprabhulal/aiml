"""Three narrow tools for the supplied trusted sample; this is not a sandbox."""
import os
from pathlib import Path
import subprocess
import sys


def schema(name, description, fields):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": {
                key: {"type": "string"} for key in fields}, "required": fields,
                "additionalProperties": False}}}


class RepoTools:
    schemas = [
        schema("read_file", "Read path_rules.py or tests/test_path_rules.py in the sample repository.", ["path"]),
        schema("replace_text", "Replace one exact occurrence in path_rules.py. Read it first.", ["old", "new"]),
        schema("run_tests", "Run the sample repository's existing pytest tests and return exit_code and output.", []),
    ]

    def __init__(self, root):
        self.root = Path(root)

    def read_file(self, path):
        if path not in {"path_rules.py", "tests/test_path_rules.py"}:
            raise ValueError("read_file accepts only the two sample files")
        return {"path": path, "text": (self.root / path).read_text()}

    def replace_text(self, old, new):
        path = self.root / "path_rules.py"
        text = path.read_text()
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ValueError("old must be nonempty text and new must be text")
        if text.count(old) != 1:
            raise ValueError("old must match exactly once; read the current file again")
        path.write_text(text.replace(old, new, 1))
        return {"path": "path_rules.py", "replaced": 1}

    def run_tests(self):
        # Do not inherit API keys into this trusted sample's child process.
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "LANG") if key in os.environ}
        env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
        try:
            run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                 cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            return {"exit_code": None, "error": "sample tests exceeded 15 seconds"}
        return {"exit_code": run.returncode, "output": (run.stdout + run.stderr)[-4000:]}

    def invoke(self, name, arguments):
        if name not in {"read_file", "replace_text", "run_tests"}:
            raise ValueError(f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        return getattr(self, name)(**arguments)
