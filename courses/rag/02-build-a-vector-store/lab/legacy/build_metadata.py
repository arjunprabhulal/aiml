"""Build lesson-metadata.json from the published aiml lessons.

Run from a checkout of the site repository at the commit recorded in corpus.json:

    python build_metadata.py /path/to/aiml.sh > lesson-metadata.json

Each published lesson gets the fields the store can filter on: its kind
(a foundation lesson or a build), its topic and its reading time in minutes.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

KINDS = {'foundations': 'foundation', 'deep-dives': 'build'}


def fields(text: str) -> dict:
    head = re.match(r'\A---\n(.*?)\n---\n', text, re.S)[1]
    return dict(re.findall(r'^(id|status|topic|minutes):\s*["\']?([^\n"\']+)', head, re.M))


def build(repo: Path) -> dict:
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True).stdout.strip()
    lessons = {}
    for folder, kind in KINDS.items():
        for path in sorted((repo / 'src/content' / folder).glob('*.mdx')):
            f = fields(path.read_text())
            if f.get('status') == 'published':
                lessons[f['id']] = {'kind': kind, 'topic': f['topic'], 'minutes': int(f['minutes'])}
    return {'source': 'published aiml.sh lessons', 'source_commit': commit, 'lessons': lessons}


if __name__ == '__main__':
    print(json.dumps(build(Path(sys.argv[1])), indent=2, ensure_ascii=False))
