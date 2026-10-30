"""PDF text extraction for the study library: page-by-page, no interpretation.

Knows nothing about courses, models, the database or macOS authorization. Input
is one StudyBot-owned PDF file; output is the text of each page (1-based) as the
PDF engine produced it. Image-only pages yield empty text; there is no OCR.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from studybot.core.exceptions import StudyBotError

#: Bump when extraction output changes so existing files are reprocessed.
PDF_PROCESSING_VERSION = "pdf_text_v2"  # v2: extracted with PDFium (v1 used another engine)

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


def load_pdfium():
    """Import pypdfium2 lazily; only PDF imports need the native PDFium library."""
    import pypdfium2

    return pypdfium2


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
    """Extracts page text with PDFium (``pypdfium2``).

    PDFium is not thread-safe; StudyBot runs extractions on a single worker thread.
    """

    processing_version = PDF_PROCESSING_VERSION

    def extract(self, path: Path) -> PdfExtractionResult:
        if path.stat().st_size > MAX_PDF_BYTES:
            raise PdfExtractionError(FILE_TOO_LARGE)
        pdfium = load_pdfium()
        try:
            document = pdfium.PdfDocument(str(path))
        except pdfium.PdfiumError as error:
            raise PdfExtractionError(
                PASSWORD_REQUIRED if error.err_code == pdfium.raw.FPDF_ERR_PASSWORD else INVALID_PDF
            ) from None
        except Exception:
            raise PdfExtractionError(INVALID_PDF) from None
        try:
            if len(document) > MAX_PDF_PAGES:
                raise PdfExtractionError(TOO_MANY_PAGES)
            return self._extract_pages(document)
        finally:
            document.close()

    @staticmethod
    def _extract_pages(document) -> PdfExtractionResult:
        pages: list[PdfPage] = []
        total_bytes = 0
        for index in range(len(document)):
            try:
                page = document[index]
                try:
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()
                    finally:
                        textpage.close()
                finally:
                    page.close()
            except Exception:
                raise PdfExtractionError(EXTRACTION_FAILED) from None
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            total_bytes += len(text.encode("utf-8"))
            if total_bytes > MAX_EXTRACTED_TEXT_BYTES:
                raise PdfExtractionError(TEXT_TOO_LARGE)
            pages.append(PdfPage(index + 1, text))
        return PdfExtractionResult(page_count=len(pages), pages=tuple(pages))
