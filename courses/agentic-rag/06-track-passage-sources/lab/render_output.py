"""Render the actual offline source-verification record as a static HTML report."""
from html import escape
import json
from pathlib import Path
import sys


def render(record: dict) -> str:
    if record.get("execution_mode") != "offline-source-verification" or record.get("model_called") is not False:
        raise ValueError("expected an offline source-verification record without model calls")
    passage = record["passage"]
    def field(label: str, value: object) -> str:
        return f"<div><dt>{escape(label)}</dt><dd>{escape(str(value))}</dd></div>"
    metadata = "".join(field(label, passage[key]) for label, key in [
        ("Source ID", "source_id"), ("Local source", "source_path"),
        ("API version", "version"), ("Documentation URL", "url"),
    ])
    span = f'{passage["start_line"]}–{passage["end_line"]} (1-based, inclusive)'
    metadata += field("Line span", span)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Track passage sources — actual run</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f7fb;color:#192136;font:18px/1.55 system-ui,sans-serif}}
main{{max-width:1100px;margin:auto;padding:40px 24px}}h1{{font-size:clamp(28px,4vw,44px);line-height:1.15;margin:8px 0 20px}}
h2{{font-size:23px;margin:0 0 16px}}p{{margin:8px 0}}.mode{{color:#274bc4;font-weight:700}}
section{{background:#fff;border:1.5px solid #192136;border-radius:10px;padding:24px;margin:24px 0}}
dl{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:0}}dt{{font-size:14px;color:#596375;font-weight:700}}dd{{margin:4px 0 0;overflow-wrap:anywhere}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;font:16px/1.6 ui-monospace,monospace;margin:0}}
.hash{{font-family:ui-monospace,monospace;font-size:15px;overflow-wrap:anywhere}}.note{{color:#596375}}
@media(max-width:500px){{main{{padding:24px 16px}}section{{padding:18px}}dl{{grid-template-columns:1fr}}}}
</style></head><body><main>
<p class="mode">Actual recorded run · Offline source verification · No model call</p>
<h1>Track passage sources</h1>
<p>The program reconstructs a passage from local file bytes and compares it with the stored record.</p>
<section><h2>Bound source</h2><dl>{metadata}</dl></section>
<section><h2>Verified passage text</h2><pre>{escape(record["verified_text"])}</pre>
<p class="note">Supplied original Python API summary. Metadata is carried through; this run does not authenticate the source author or check the API claim.</p></section>
<section><h2>Snapshot identity</h2><p>Whole-file SHA-256</p><p class="hash">{escape(passage["source_sha256"])}</p>
<p>Chunk ID</p><p class="hash">{escape(passage["chunk_id"])}</p></section>
<section><h2>Deliberate text change rejected</h2><pre>{escape(record["tampered_text_rejection"])}</pre>
<p class="note">The program changed the stored passage text before verification. The current local source did not match that altered record.</p></section>
<p class="note">Raw record: runs/2026-10-23-ingestion/run.json · Source and contract checks only; no generated answer or retrieval-quality measurement.</p>
</main></body></html>'''


if __name__ == "__main__":
    record_path = Path(__file__).parent / "runs/2026-10-23-ingestion/run.json"
    output_path = Path(sys.argv[1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render(json.loads(record_path.read_text(encoding="utf-8"))), encoding="utf-8")
    print(output_path)
