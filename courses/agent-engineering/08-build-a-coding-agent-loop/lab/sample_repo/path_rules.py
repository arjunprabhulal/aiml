"""Select changed Python source files for a CI check."""
from pathlib import PurePosixPath


def python_sources(changed_paths):
    selected = []
    for name in changed_paths:
        path = PurePosixPath(name)
        if path.parts and path.parts[0] == "src" and path.suffix == ".py":
            selected.append(path.as_posix())
    return selected
