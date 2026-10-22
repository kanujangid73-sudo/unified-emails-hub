"""Small but real files for the demo mailboxes' attachments, generated on the fly.

The PDFs open in any viewer and the PNGs are proper images, so downloading an attachment in
the demo works end to end without shipping binary files in the repository.
"""

import hashlib
import struct
import zlib


def _pdf_text(value: str) -> str:
    safe = value.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(title: str, lines: list[str]) -> bytes:
    """A one-page A4 PDF with a title and some lines of text."""
    text = [f"BT /F1 22 Tf 72 770 Td ({_pdf_text(title)}) Tj ET"]
    for i, line in enumerate(lines):
        text.append(f"BT /F1 12 Tf 72 {730 - i * 20} Td ({_pdf_text(line)}) Tj ET")
    stream = "\n".join(text).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_png(seed: str, width: int = 320, height: int = 200) -> bytes:
    """A gradient picture, different for each seed (a stand-in for a photo)."""
    h = hashlib.sha256(seed.encode()).digest()
    top, bottom = h[:3], h[3:6]
    rows = bytearray()
    for y in range(height):
        t = y / (height - 1)
        color = bytes(int(top[c] * (1 - t) + bottom[c] * t) for c in range(3))
        rows += b"\x00" + color * width  # filter type 0, then RGB pixels

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")


def demo_file(filename: str, mime_type: str, lines: tuple[str, ...] = ()) -> bytes:
    if mime_type == "application/pdf":
        return make_pdf(filename.rsplit(".", 1)[0].replace("-", " "), list(lines))
    if mime_type == "image/png":
        return make_png(filename)
    return "\n".join(lines or (filename,)).encode()
