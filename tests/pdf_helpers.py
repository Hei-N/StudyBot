"""Builds small synthetic PDFs for tests (no private or copyrighted content, no PDF library needed)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path


def _escape(line: str) -> bytes:
    data = line.encode("cp1252")
    return data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _page_stream(text: str, image_only: bool) -> bytes:
    if image_only:
        return b"q 100 0 0 100 72 600 cm /Im1 Do Q"
    lines = text.split("\n") if text else []
    if not lines:
        return b""
    parts = [b"BT /F1 12 Tf 72 720 Td 14 TL"]
    for index, line in enumerate(lines):
        parts.append((b"(" + _escape(line) + b") Tj") if index == 0 else (b"T* (" + _escape(line) + b") Tj"))
    parts.append(b"ET")
    return b" ".join(parts)


def pdf_bytes(pages: list[str], *, image_only: bool = False) -> bytes:
    """A valid PDF with one Helvetica text page (or one image-only page) per entry."""
    objects: dict[int, bytes] = {
        1: b"<</Type/Catalog/Pages 2 0 R>>",
        3: b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>",
        4: b"<</Type/XObject/Subtype/Image/Width 2/Height 2/ColorSpace/DeviceRGB/BitsPerComponent 8/Length 12>>\n"
        b"stream\n" + bytes([200] * 12) + b"\nendstream",
    }
    kids = []
    for index, text in enumerate(pages):
        page_id, content_id = 5 + 2 * index, 6 + 2 * index
        kids.append(f"{page_id} 0 R")
        stream = _page_stream(text, image_only)
        objects[page_id] = (
            f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents {content_id} 0 R"
            f"/Resources<</Font<</F1 3 0 R>>/XObject<</Im1 4 0 R>>>>>>"
        ).encode()
        objects[content_id] = f"<</Length {len(stream)}>>\nstream\n".encode() + stream + b"\nendstream"
    objects[2] = f"<</Type/Pages/Kids[{' '.join(kids)}]/Count {len(pages)}>>".encode()

    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = out.tell()
        out.write(f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n")
    xref = out.tell()
    size = max(objects) + 1
    out.write(f"xref\n0 {size}\n0000000000 65535 f \n".encode())
    for number in range(1, size):
        out.write(f"{offsets[number]:010d} 00000 n \n".encode())
    out.write(f"trailer\n<</Size {size}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_pdf(path: Path, pages: list[str], *, password: str | None = None, image_only: bool = False) -> Path:
    data = pdf_bytes(pages, image_only=image_only)
    if password:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter(clone_from=PdfReader(BytesIO(data)))
        writer.encrypt(user_password=password, owner_password=password + "-owner", algorithm="RC4-128")
        buffer = BytesIO()
        writer.write(buffer)
        data = buffer.getvalue()
    path.write_bytes(data)
    return path
