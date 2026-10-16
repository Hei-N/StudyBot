import hashlib

import pytest

from studybot.core import content_hash
from studybot.core.exceptions import SessionError
from studybot.core.library import (
    ALLOWED_TRANSITIONS,
    LibraryFileState,
    can_transition,
    file_extension,
    normalize_content_hash,
    normalize_locator,
    normalize_relative_path,
    validate_failure_code,
)

# --- relative paths ------------------------------------------------------------------


@pytest.mark.parametrize("path", ["../secret.pdf", "../../file.pdf", "a/../../b.pdf", "a/..", "..", "/absolute/file.pdf",
                                  "C:/Windows/file.pdf", "C:\\Users\\x\\file.pdf", "\\\\server\\share\\f.pdf", "", "   ",
                                  ".", "./", "bad\x00name.pdf"])
def test_invalid_relative_paths_are_rejected(path):
    with pytest.raises(SessionError):
        normalize_relative_path(path)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Week 2/Lecture.pdf", "Week 2/Lecture.pdf"),
        ("Notes/chapter-1.txt", "Notes/chapter-1.txt"),
        ("./Notes//chapter-1.txt", "Notes/chapter-1.txt"),
        ("Notes\\chapter-1.txt", "Notes/chapter-1.txt"),
        ("single.pdf", "single.pdf"),
    ],
)
def test_valid_relative_paths_are_normalized(raw, expected):
    assert normalize_relative_path(raw) == expected


def test_file_extension():
    assert file_extension("Week 2/Lecture.PDF") == "pdf"
    assert file_extension("archive.tar.gz") == "gz"
    assert file_extension("README") is None
    assert file_extension(".hidden") is None


# --- locators ------------------------------------------------------------------------


def test_locator_is_tidied_but_not_resolved():
    assert normalize_locator("  /tmp//school/PHY215/  ") == "/tmp/school/PHY215"
    assert normalize_locator("/") == "/"
    assert normalize_locator("relative/../x") == "relative/../x"  # no filesystem or alias resolution


@pytest.mark.parametrize("value", ["", "   ", "bad\x00path", "x" * 5000])
def test_invalid_locators_are_rejected(value):
    with pytest.raises(SessionError):
        normalize_locator(value)


# --- hash and failure code -----------------------------------------------------------


def test_content_hash_must_be_sha256_hex():
    digest = hashlib.sha256(b"x").hexdigest()
    assert normalize_content_hash(digest.upper()) == digest
    for bad in ["", "abc", "g" * 64, digest + "0"]:
        with pytest.raises(SessionError):
            normalize_content_hash(bad)


def test_failure_code_must_be_a_short_identifier():
    assert validate_failure_code("read_failed") == "read_failed"
    for bad in ["", "Traceback (most recent call last)", "Has Space", "x" * 100, "../etc"]:
        with pytest.raises(SessionError):
            validate_failure_code(bad)


# --- state machine -------------------------------------------------------------------


def test_the_allowed_transitions_are_exactly_the_documented_ones():
    S = LibraryFileState
    allowed = {(a, b) for a, targets in ALLOWED_TRANSITIONS.items() for b in targets}
    assert allowed == {
        (S.PENDING, S.INDEXING),
        (S.INDEXING, S.READY),
        (S.INDEXING, S.FAILED),
        (S.READY, S.STALE),
        (S.STALE, S.INDEXING),
        (S.FAILED, S.PENDING),
    }
    assert not can_transition(S.PENDING, S.READY)
    assert not can_transition(S.READY, S.FAILED)
    assert not can_transition(S.FAILED, S.READY)


# --- SHA-256 helper ------------------------------------------------------------------


def _write(tmp_path, data: bytes):
    path = tmp_path / "file.bin"
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("data", [b"", b"hello study library\n", bytes(range(256)) * 40, b"\x00\xff\x00" * 5])
def test_sha256_matches_hashlib(tmp_path, data):
    assert content_hash.sha256_file(_write(tmp_path, data)) == hashlib.sha256(data).hexdigest()


def test_sha256_handles_a_file_larger_than_one_chunk(tmp_path):
    data = b"a" * (content_hash.CHUNK_SIZE * 2 + 123)
    assert content_hash.sha256_file(_write(tmp_path, data)) == hashlib.sha256(data).hexdigest()


def test_sha256_reads_in_bounded_chunks(tmp_path, monkeypatch):
    data = bytes(range(256)) * 20
    path = _write(tmp_path, data)
    reads = []
    real_open = open

    class Spy:
        def __init__(self, handle):
            self._handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._handle.close()

        def read(self, size=-1):
            reads.append(size)
            return self._handle.read(size)

    monkeypatch.setattr(content_hash, "open", lambda *a, **k: Spy(real_open(*a, **k)), raising=False)

    assert content_hash.sha256_file(path, chunk_size=64) == hashlib.sha256(data).hexdigest()
    assert reads and all(size == 64 for size in reads)
    assert len(reads) > len(data) // 64


def test_sha256_rejects_a_non_positive_chunk_size(tmp_path):
    with pytest.raises(ValueError):
        content_hash.sha256_file(_write(tmp_path, b"x"), chunk_size=0)


def test_sha256_does_not_scan_directories(tmp_path):
    with pytest.raises((IsADirectoryError, PermissionError)):
        content_hash.sha256_file(tmp_path)
