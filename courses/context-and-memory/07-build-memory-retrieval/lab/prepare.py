"""One-time download of the four pinned tokenizer files; no account, API key or weights."""
from huggingface_hub import snapshot_download
from tokenizer import MANIFEST, ROOT, counter

snapshot_download(MANIFEST['model'], revision=MANIFEST['revision'],
                  allow_patterns=list(MANIFEST['files']), local_dir=ROOT / '.tokenizer')
print(counter().profile())
