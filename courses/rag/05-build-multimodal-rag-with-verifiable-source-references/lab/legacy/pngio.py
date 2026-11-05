"""Write and read 8-bit grayscale PNG images. Python 3.11+, standard library.

Only one PNG form is supported: 8-bit grayscale (color type 0), no interlace.
That is the form `render_pages.py` writes. Anything else is refused with a
clear error instead of being decoded wrongly.
"""
import hashlib
import struct
import zlib

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
INK, PAPER = 0, 255


class Canvas:
    """A grayscale image held as one byte per pixel, row by row."""

    def __init__(self, width, height, value=PAPER, pixels=None):
        if type(width) is not int or type(height) is not int or width < 1 or height < 1:
            raise ValueError('Canvas width and height must be positive integers.')
        self.width, self.height = width, height
        self.pixels = bytearray(pixels) if pixels is not None else bytearray([value]) * (width * height)
        if len(self.pixels) != width * height:
            raise ValueError('Pixel data does not match the canvas size.')

    def fill(self, x, y, w, h, value=INK):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        for row in range(y0, y1):
            start = row * self.width
            self.pixels[start + x0:start + x1] = bytes([value]) * max(0, x1 - x0)

    def get(self, x, y):
        return self.pixels[y * self.width + x]

    def crop(self, box):
        """Return the pixels inside box = [x0, y0, x1, y1] (x1, y1 exclusive)."""
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= self.width and 0 <= y0 < y1 <= self.height):
            raise ValueError(f'Box {box} is outside the {self.width} x {self.height} page.')
        rows = (self.pixels[r * self.width + x0:r * self.width + x1] for r in range(y0, y1))
        return Canvas(x1 - x0, y1 - y0, pixels=b''.join(rows))

    def sha256(self):
        """Hash of the size and pixels, not of the PNG bytes.

        Two zlib builds may compress the same pixels into different bytes, so
        a hash of the pixels is the stable identity of an image.
        """
        return hashlib.sha256(f'{self.width}x{self.height}:'.encode() + bytes(self.pixels)).hexdigest()

    def pad(self, margin):
        """Return a copy with `margin` pixels of paper on every side."""
        out = Canvas(self.width + 2 * margin, self.height + 2 * margin)
        for row in range(self.height):
            start = (row + margin) * out.width + margin
            out.pixels[start:start + self.width] = self.pixels[row * self.width:(row + 1) * self.width]
        return out


def _chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def encode_png(canvas):
    """Encode a canvas. Every row uses filter 0, so the bytes are deterministic."""
    raw = b''.join(b'\x00' + bytes(canvas.pixels[r * canvas.width:(r + 1) * canvas.width])
                   for r in range(canvas.height))
    header = struct.pack('>IIBBBBB', canvas.width, canvas.height, 8, 0, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b'IHDR', header) + _chunk(b'IDAT', zlib.compress(raw, 9)) + _chunk(b'IEND', b'')


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(data):
    """Decode 8-bit grayscale PNG bytes into a Canvas. Other forms raise ValueError."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError('Not a PNG file.')
    pos, header, idat = len(PNG_SIGNATURE), None, []
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError('Truncated PNG chunk.')
        length, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        crc = data[pos + 8 + length:pos + 12 + length]
        if len(body) != length or len(crc) != 4 or struct.unpack('>I', crc)[0] != zlib.crc32(kind + body):
            raise ValueError(f'PNG chunk {kind!r} is damaged.')
        if kind == b'IHDR':
            header = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
        pos += 12 + length
    if header is None or not idat:
        raise ValueError('PNG has no header or no image data.')
    width, height, depth, color, _, _, interlace = header
    if (depth, color, interlace) != (8, 0, 0):
        raise ValueError('Only 8-bit grayscale, non-interlaced PNG is supported.')
    raw = zlib.decompress(b''.join(idat))
    if len(raw) != height * (width + 1):
        raise ValueError('PNG image data has the wrong length.')
    pixels, previous = bytearray(), bytearray(width)
    for r in range(height):
        kind = raw[r * (width + 1)]
        line = bytearray(raw[r * (width + 1) + 1:(r + 1) * (width + 1)])
        for i in range(width if kind else 0):
            left = line[i - 1] if i else 0
            up, corner = previous[i], previous[i - 1] if i else 0
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                line[i] = (line[i] + _paeth(left, up, corner)) & 255
            elif kind != 0:
                raise ValueError(f'Unknown PNG filter type {kind}.')
        pixels += line
        previous = line
    return Canvas(width, height, pixels=pixels)
