"""Check three proposed calls without a model. Run: python check_calls.py"""
from docs_tools import run_tool

if __name__ == "__main__":
    for name, args, offered in [
        ("read_page", {"page": "rollback.md"}, set()),
        ("read_page", {"page": "secrets.md"}, {"read_page"}),
        ("delete_page", {"page": "rollback.md"}, {"read_page"}),
    ]:
        print(name, args, "->", run_tool(name, args, offered))
