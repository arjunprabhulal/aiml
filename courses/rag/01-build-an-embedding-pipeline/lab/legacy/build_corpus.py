"""Build corpus.json from the published aiml lessons: one passage per lesson section.

Run from a checkout of the site repository:

    python build_corpus.py /path/to/aiml.sh > corpus.json

Each passage is one `##` section of a published lesson, with imports, code,
components and expressions removed. Long sections are split at paragraph
boundaries. Reference sections are left out: they are lists of links.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

SKIP_SECTIONS = {'references', 'sources', 'official references'}
MAX_WORDS = 220
MIN_WORDS = 25


def front_matter(text: str) -> tuple[dict, str]:
    match = re.match(r'\A---\n(.*?)\n---\n', text, re.S)
    fields = dict(re.findall(r'^(id|title|status|published):\s*["\']?([^\n"\']+)', match[1], re.M))
    return fields, text[match.end():]


def strip_braces(text: str) -> str:
    """Remove {...} expressions, including nested ones."""
    out, depth = [], 0
    for char in text:
        if char == '{':
            depth += 1
        elif char == '}' and depth:
            depth -= 1
        elif not depth:
            out.append(char)
    return ''.join(out)


def plain(text: str) -> str:
    text = re.sub(r'^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[ \t]*$', '', text, flags=re.M | re.S)
    text = re.sub(r'^(import|export) .*$', '', text, flags=re.M)
    # Keep inline code as text; protect it from the markup removal below.
    spans = re.findall(r'`([^`\n]+)`', text)
    text = re.sub(r'`([^`\n]+)`', lambda m: f'\x00{spans.index(m[1])}\x00', text)
    text = re.sub(r'<(details|table|figure|svg)\b.*?</\1>', '', text, flags=re.S)
    text = re.sub(r'<[A-Z]\w*\b(?:[^"\'{}>]|"[^"]*"|\'[^\']*\'|\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})*?/>', '', text, flags=re.S)
    text = strip_braces(text)
    text = re.sub(r'</?[A-Za-z][^>]*>', '', text)
    text = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'^\s*\|?\s*:?-{3,}.*$', '', text, flags=re.M)
    text = text.replace('|', ' ')
    text = re.sub(r'\*\*|(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)', '', text)
    text = re.sub(r'^#{3,6} ', '', text, flags=re.M)
    return re.sub(r'\x00(\d+)\x00', lambda m: spans[int(m[1])], text)


def paragraphs(body: str) -> list[str]:
    parts = [re.sub(r'\s+', ' ', p).strip() for p in re.split(r'\n\s*\n', plain(body))]
    return [p for p in parts if p]


def passages(lesson_id: str, title: str, body: str) -> list[dict]:
    result = []
    for heading, section in re.findall(r'^## ([^\n]+)\n(.*?)(?=^## |\Z)', body, re.M | re.S):
        heading = heading.strip()
        if heading.lower() in SKIP_SECTIONS:
            continue
        slug = re.sub(r'[^a-z0-9]+', '-', heading.lower()).strip('-')
        chunk, part = [], 1
        for paragraph in paragraphs(section) + [None]:
            words = sum(len(p.split()) for p in chunk)
            if paragraph is None or (chunk and words + len(paragraph.split()) > MAX_WORDS):
                text = ' '.join(chunk)
                if len(text.split()) >= MIN_WORDS:
                    result.append({'id': f'{lesson_id}#{slug}' + (f'-{part}' if part > 1 else ''),
                                   'lesson': lesson_id, 'title': f'{title}: {heading}', 'text': text})
                    part += 1
                chunk = []
            if paragraph is not None:
                chunk.append(paragraph)
    return result


def build(repo: Path) -> dict:
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True).stdout.strip()
    items = []
    for folder in ('foundations', 'deep-dives'):
        for path in sorted((repo / 'src/content' / folder).glob('*.mdx')):
            fields, body = front_matter(path.read_text())
            if fields.get('status') != 'published':
                continue
            items += passages(fields['id'], fields['title'], body)
    return {'source': 'published aiml.sh lessons', 'source_commit': commit, 'max_words': MAX_WORDS,
            'min_words': MIN_WORDS, 'passages': items}


if __name__ == '__main__':
    print(json.dumps(build(Path(sys.argv[1])), indent=2, ensure_ascii=False))
