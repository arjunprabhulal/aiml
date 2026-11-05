"""One list of sources from two earlier builds, each with a way back to its pixels. Python 3.11+.

A page source is a chunk from document.json (the document-understanding
build): its text, and the page boxes and crop hashes of its lines. A figure
source is a figure from figure-index.json (the visual search build): its
description, its printed words and the pixel hash of its image.

resolve() checks a source against the image files before anyone relies on it.
"""
import hashlib
import json
from pathlib import Path

from pngio import decode_png

ROOT = Path(__file__).resolve().parent
CROP_MARGIN = 8   # the margin the document pipeline added around each line crop


class SourceError(ValueError):
    pass


def load_sources(root=ROOT):
    root = Path(root)
    document = json.loads((root / 'document.json').read_text())
    figures = json.loads((root / 'figure-index.json').read_text())
    pages = {(p['doc'], p['page']): p for p in document['pages']}
    blocks = {b['id']: b for p in document['pages'] for b in p['blocks']}
    sources = []
    for chunk in document['chunks']:
        sources.append({'id': chunk['id'], 'kind': 'page', 'text': chunk['text'],
                        'pages': sorted({b['page'] for b in chunk['blocks']}),
                        'refs': [{'block': b['id'], 'image': pages[(chunk['doc'], b['page'])]['image'],
                                  'page_sha256': pages[(chunk['doc'], b['page'])]['sha256'],
                                  'lines': [{'bbox': line['bbox'], 'crop_sha256': line['crop_sha256']}
                                            for line in blocks[b['id']]['lines']]}
                                 for b in chunk['blocks']]})
    for figure in figures['figures']:
        sources.append({'id': figure['id'], 'kind': 'figure', 'image': figure['image'],
                        'pixel_sha256': figure['pixel_sha256'],
                        'text': f'{figure["description"]}\nText in the figure: {figure["printed_text"]}',
                        'printed_text': figure['printed_text'], 'description': figure['description']})
    return sources


def search_text(source):
    """The text each source is embedded by. Figures use the visual search build's 'both' field."""
    return source['text']


def resolve(source, root=ROOT):
    """Check that the source's pixels are the ones its text was made from. Returns the pixel hashes checked."""
    root = Path(root)
    if source['kind'] == 'figure':
        canvas = decode_png((root / source['image']).read_bytes())
        if canvas.sha256() != source['pixel_sha256']:
            raise SourceError(f'{source["id"]}: {source["image"]} changed after it was described.')
        return [source['pixel_sha256']]
    checked = []
    for ref in source['refs']:
        png = (root / ref['image']).read_bytes()
        if hashlib.sha256(png).hexdigest() != ref['page_sha256']:
            raise SourceError(f'{source["id"]}: {ref["image"]} changed after it was read.')
        canvas = decode_png(png)
        for line in ref['lines']:
            try:
                crop = canvas.crop(line['bbox']).pad(CROP_MARGIN)
            except ValueError as error:
                raise SourceError(f'{source["id"]}: {error}') from error
            if crop.sha256() != line['crop_sha256']:
                raise SourceError(f'{source["id"]}: box {line["bbox"]} in {ref["block"]} no longer gives its crop.')
            checked.append(line['crop_sha256'])
    return checked
