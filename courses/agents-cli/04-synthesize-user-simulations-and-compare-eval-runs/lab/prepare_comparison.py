"""Prepare local comparison examples from the preserved input dictionaries.
These are fixture examples, not evidence of a new prompt-improvement experiment.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

def main():
    supplied = json.loads((HERE / "recorded-eval-compare.json").read_text())
    for name in ("baseline", "candidate"):
        path = HERE / f"{name}.example.json"
        path.write_text(json.dumps(supplied[name], indent=2) + "\n")
        print(f"Wrote {path.name}: supplied example, not a new model result")

if __name__ == "__main__":
    main()
