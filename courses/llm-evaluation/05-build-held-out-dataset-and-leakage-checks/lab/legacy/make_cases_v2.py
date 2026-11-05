"""Write cases-v2.json: cases.json with three edits of the kind that break a held-out split.

1. The held-out case cannot-log-in is reworded ("can't" becomes "cannot").
2. A new development case copies the held-out case stranger-buying with one word changed.
3. The held-out case shop-hours is moved to development.
The edits are written for this lesson; cases.json itself is unchanged.
Run: python3 make_cases_v2.py
"""
import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def make(cases):
    data = copy.deepcopy(cases)
    by_id = {case["id"]: case for case in data["cases"]}
    by_id["cannot-log-in"]["input"] = "I cannot log in since yesterday."
    by_id["shop-hours"]["split"] = "development"
    stranger = by_id["stranger-buying"]
    data["cases"].append(dict(stranger, id="stranger-keeps-buying", split="development",
                              input="A stranger keeps buying things with my account."))
    data["name"] = data["name"] + "-v2"
    return data


if __name__ == "__main__":
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    (HERE / "cases-v2.json").write_text(json.dumps(make(cases), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote cases-v2.json")
