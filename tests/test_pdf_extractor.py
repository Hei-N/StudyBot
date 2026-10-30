import pytest

from studybot.core import pdf_extractor
from studybot.core.pdf_extractor import PDF_PROCESSING_VERSION, PdfExtractionError, PdfExtractor
from tests.pdf_helpers import make_pdf


def extract(path):
    return PdfExtractor().extract(path)


def test_single_page_text(tmp_path):
    result = extract(make_pdf(tmp_path / "a.pdf", ["Density formula: rho = m / V"]))

    assert result.page_count == 1 and result.text_page_count == 1
    assert result.pages[0].page_number == 1
    assert "Density formula: rho = m / V" in result.pages[0].text


def test_pages_are_numbered_from_one_in_order(tmp_path):
    result = extract(make_pdf(tmp_path / "a.pdf", ["first page", "second page", "third page"]))

    assert [p.page_number for p in result.pages] == [1, 2, 3]
    assert [p.text.split()[0] for p in result.pages] == ["first", "second", "third"]


def test_an_empty_page_keeps_its_row_with_empty_text(tmp_path):
    result = extract(make_pdf(tmp_path / "a.pdf", ["text", "", "more text"]))

    assert result.page_count == 3 and result.text_page_count == 2
    assert result.pages[1].page_number == 2 and result.pages[1].text.strip() == ""


def test_image_only_pdf_is_valid_with_no_text(tmp_path):
    result = extract(make_pdf(tmp_path / "scan.pdf", ["", "", ""], image_only=True))

    assert result.page_count == 3 and result.text_page_count == 0
    assert all(p.text.strip() == "" for p in result.pages)


def test_unicode_text_is_kept(tmp_path):
    # The synthetic PDF uses a built-in font, so stick to characters it can draw.
    result = extract(make_pdf(tmp_path / "u.pdf", ["½ at² · café ñ ü"]))

    assert "café" in result.pages[0].text and "½" in result.pages[0].text and "ñ" in result.pages[0].text


def test_text_is_not_rewritten_or_collapsed(tmp_path):
    result = extract(make_pdf(tmp_path / "a.pdf", ["Line one\nLine two   spaced"]))

    assert "Line one\nLine two" in result.pages[0].text and "\r" not in result.pages[0].text


def test_password_protected_pdf_fails_with_a_code(tmp_path):
    path = make_pdf(tmp_path / "locked.pdf", ["secret"], password="pw")

    with pytest.raises(PdfExtractionError) as error:
        extract(path)

    assert error.value.code == "password_required"
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("content", [b"", b"not a pdf at all", b"%PDF-1.4 garbage", b"\x89PNG\r\n\x1a\n"])
def test_invalid_pdf_fails_with_a_code(tmp_path, content):
    path = tmp_path / "bad.pdf"
    path.write_bytes(content)

    with pytest.raises(PdfExtractionError) as error:
        extract(path)

    assert error.value.code == "invalid_pdf"


def test_a_png_renamed_to_pdf_is_rejected(tmp_path):
    path = tmp_path / "image.pdf"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))

    with pytest.raises(PdfExtractionError) as error:
        extract(path)
    assert error.value.code == "invalid_pdf"


def test_a_larger_multi_page_pdf(tmp_path):
    pages = [f"Page {n} " + "word " * 200 for n in range(1, 81)]

    result = extract(make_pdf(tmp_path / "long.pdf", pages))

    assert result.page_count == 80 and result.pages[79].page_number == 80
    assert "Page 80" in result.pages[79].text


def test_limits_fail_with_codes(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "a.pdf", ["a", "b", "c"])

    monkeypatch.setattr(pdf_extractor, "MAX_PDF_PAGES", 2)
    with pytest.raises(PdfExtractionError) as pages:
        extract(path)
    monkeypatch.setattr(pdf_extractor, "MAX_PDF_PAGES", 5000)
    monkeypatch.setattr(pdf_extractor, "MAX_EXTRACTED_TEXT_BYTES", 2)
    with pytest.raises(PdfExtractionError) as text:
        extract(path)
    monkeypatch.setattr(pdf_extractor, "MAX_EXTRACTED_TEXT_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(pdf_extractor, "MAX_PDF_BYTES", 10)
    with pytest.raises(PdfExtractionError) as size:
        extract(path)

    assert (pages.value.code, text.value.code, size.value.code) == ("too_many_pages", "text_too_large", "file_too_large")


def test_extractor_reads_only_the_given_file_and_has_a_version(tmp_path):
    assert PdfExtractor.processing_version == PDF_PROCESSING_VERSION == "pdf_text_v2"
    import inspect

    source = inspect.getsource(pdf_extractor)
    for forbidden in ["sqlite", "ollama", "os.walk", "iterdir", "glob", "bookmark"]:
        assert forbidden not in source.lower()
