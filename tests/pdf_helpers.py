"""Builds small synthetic PDFs for tests (no private or copyrighted content)."""

from __future__ import annotations

from pathlib import Path

from studybot.core.pdf_extractor import load_pymupdf


def make_pdf(path: Path, pages: list[str], *, password: str | None = None, image_only: bool = False) -> Path:
    pymupdf = load_pymupdf()
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if image_only:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
            pixmap.clear_with(200)
            page.insert_image(pymupdf.Rect(72, 72, 172, 172), pixmap=pixmap)
        elif text:
            page.insert_text((72, 72), text)
    if password:
        document.save(
            path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password + "-owner"
        )
    else:
        document.save(path)
    document.close()
    return path
