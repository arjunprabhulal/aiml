"""Group pull request titles by Conventional Commits type and print JSON."""
import json
import re
import sys

SECTIONS = {"feat": "features", "fix": "fixes", "docs": "docs"}
groups = {"breaking": [], "features": [], "fixes": [], "docs": [], "skipped": []}
for title in sys.argv[1:]:
    match = re.match(r"^(\w+)(\([^)]*\))?(!)?:\s*(.+)$", title)
    if not match:
        groups["skipped"].append(title)
    elif match[3]:
        groups["breaking"].append(match[4])
    else:
        groups[SECTIONS.get(match[1], "skipped")].append(match[4])
print(json.dumps(groups))
