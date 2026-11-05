from path_rules import python_sources


def test_selects_only_python_under_src():
    assert python_sources(["src/app.py", "docs/setup.md", "tests/test_app.py"]) == ["src/app.py"]


def test_preserves_nested_modules():
    assert python_sources(["src/api/routes.py"]) == ["src/api/routes.py"]


def test_accepts_windows_separators_from_change_lists():
    assert python_sources([r"src\api\routes.py"]) == ["src/api/routes.py"]


def test_empty_changes_select_nothing():
    assert python_sources([]) == []
