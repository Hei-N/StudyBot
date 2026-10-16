"""PDF text extraction for the study library: page-by-page, no interpretation.

Knows nothing about courses, models, the database or macOS authorization. Input
is one StudyBot-owned PDF file; output is the text of each page (1-based) as the
PDF engine produced it. Image-only pages yield empty text; there is no OCR.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

from studybot.core.exceptions import StudyBotError

#: Bump when extraction output changes so existing files are reprocessed.
PDF_PROCESSING_VERSION = "pdf_text_v1"

MAX_PDF_BYTES = 512 * 1024 * 1024
MAX_PDF_PAGES = 5000
MAX_EXTRACTED_TEXT_BYTES = 64 * 1024 * 1024

# Failure codes stored on a library file; never free text.
INVALID_PDF = "invalid_pdf"
PASSWORD_REQUIRED = "password_required"
FILE_TOO_LARGE = "file_too_large"
TOO_MANY_PAGES = "too_many_pages"
TEXT_TOO_LARGE = "text_too_large"
EXTRACTION_FAILED = "extraction_failed"


def load_pymupdf():
    """Import PyMuPDF lazily (only PDF imports need the native engine).

    Its generated bindings emit a DeprecationWarning on import under Python 3.14,
    which would abort the import when warnings are errors, so that one warning is ignored.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="builtin type .* has no __module__ attribute", category=DeprecationWarning)
        import pymupdf
    return pymupdf


class PdfExtractionError(StudyBotError):
    """Extraction failed for a reason described by ``code``. The message holds no document content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PdfPage:
    page_number: int  # 1-based
    text: str


@dataclass(frozen=True, slots=True)
class PdfExtractionResult:
    page_count: int
    pages: tuple[PdfPage, ...]

    @property
    def text_page_count(self) -> int:
        return sum(1 for page in self.pages if page.text.strip())


class PdfExtractor:
    """Extracts page text with PyMuPDF."""

    processing_version = PDF_PROCESSING_VERSION

    def extract(self, path: Path) -> PdfExtractionResult:
        if path.stat().st_size > MAX_PDF_BYTES:
            raise PdfExtractionError(FILE_TOO_LARGE)
        pymupdf = load_pymupdf()
        try:
            document = pymupdf.open(path, filetype="pdf")
        except Exception:
            raise PdfExtractionError(INVALID_PDF) from None
        with document:
            if not document.is_pdf:
                raise PdfExtractionError(INVALID_PDF)
            if document.needs_pass:
                raise PdfExtractionError(PASSWORD_REQUIRED)
            if document.page_count > MAX_PDF_PAGES:
                raise PdfExtractionError(TOO_MANY_PAGES)
            return self._extract_pages(document)

    @staticmethod
    def _extract_pages(document) -> PdfExtractionResult:
        pages: list[PdfPage] = []
        total_bytes = 0
        for index in range(document.page_count):
            try:
                text = document.load_page(index).get_text("text")
            except Exception:
                raise PdfExtractionError(EXTRACTION_FAILED) from None
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            total_bytes += len(text.encode("utf-8"))
            if total_bytes > MAX_EXTRACTED_TEXT_BYTES:
                raise PdfExtractionError(TEXT_TOO_LARGE)
            pages.append(PdfPage(index + 1, text))
        return PdfExtractionResult(page_count=len(pages), pages=tuple(pages))
