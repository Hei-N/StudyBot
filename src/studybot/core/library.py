"""Study Library domain types: source kinds, file processing states and path rules.

A library source is a logical place study material comes from; a library file is
one file inside it. Records here are metadata only: a source being recorded
never grants permission to read its location, and nothing in this module
touches the filesystem.

Pure domain data with no I/O, like ``core.learning_memory``.
"""

from __future__ import annotations

import re
from enum import Enum

from studybot.core.exceptions import SessionError

MAX_DISPLAY_NAME_LENGTH = 255
MAX_LOCATOR_LENGTH = 4096
MAX_RELATIVE_PATH_LENGTH = 1024
MAX_FAILURE_CODE_LENGTH = 64


class LibrarySourceKind(str, Enum):
    """Where a source's material lives. A closed set; add kinds with real integrations."""

    LOCAL_FOLDER = "local_folder"
    LOCAL_FILE = "local_file"


class LibraryFileState(str, Enum):
    """Processing state of a library file relative to its current content.

    ``ready`` means the stored processing result matches the current content
    hash; ``stale`` means the content changed since it was last ready.
    """

    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"


#: The only allowed state changes. ``failed -> pending`` is the retry path.
ALLOWED_TRANSITIONS: dict[LibraryFileState, frozenset[LibraryFileState]] = {
    LibraryFileState.PENDING: frozenset({LibraryFileState.INDEXING}),
    LibraryFileState.INDEXING: frozenset({LibraryFileState.READY, LibraryFileState.FAILED}),
    LibraryFileState.READY: frozenset({LibraryFileState.STALE}),
    LibraryFileState.STALE: frozenset({LibraryFileState.INDEXING}),
    LibraryFileState.FAILED: frozenset({LibraryFileState.PENDING}),
}

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def can_transition(current: LibraryFileState, target: LibraryFileState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def normalize_display_name(name: str) -> str:
    normalized = " ".join(name.split())
    if not normalized:
        raise SessionError("A name cannot be empty.")
    if len(normalized) > MAX_DISPLAY_NAME_LENGTH:
        raise SessionError(f"Name is too long (max {MAX_DISPLAY_NAME_LENGTH} characters).")
    return normalized


def normalize_locator(locator: str) -> str:
    """Tidy a source locator without resolving or touching it.

    Collapses repeated separators and drops a trailing one. Aliases (symlinks,
    case differences) are deliberately not resolved.
    """
    value = locator.strip()
    if not value:
        raise SessionError("A source location cannot be empty.")
    if len(value) > MAX_LOCATOR_LENGTH or _CONTROL_PATTERN.search(value):
        raise SessionError("The source location is not valid.")
    leading = "/" if value.startswith("/") else ""
    collapsed = re.sub(r"/{2,}", "/", value.lstrip("/"))
    collapsed = collapsed.rstrip("/")
    return (leading + collapsed) or "/"


def normalize_relative_path(path: str) -> str:
    """Validate and normalize a path inside a source, using ``/`` separators.

    Rejects absolute paths, drive letters, empty values and ``..`` components;
    drops empty and ``.`` components.
    """
    value = path.strip().replace("\\", "/")
    if not value or len(value) > MAX_RELATIVE_PATH_LENGTH or _CONTROL_PATTERN.search(value):
        raise SessionError("The file path is not valid.")
    if value.startswith("/") or _DRIVE_PATTERN.match(value):
        raise SessionError("A file path inside a source must be relative.")
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        raise SessionError("A file path inside a source cannot leave the source.")
    return "/".join(parts)


def file_extension(relative_path: str) -> str | None:
    """Lowercase extension without the dot, or None."""
    name = relative_path.rsplit("/", 1)[-1]
    if "." not in name.lstrip("."):
        return None
    return name.rsplit(".", 1)[-1].lower() or None


def normalize_content_hash(value: str) -> str:
    """A lowercase hex SHA-256 digest."""
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.match(normalized):
        raise SessionError("A content hash must be a SHA-256 hex digest.")
    return normalized


def validate_failure_code(code: str) -> str:
    """A short machine-readable code such as ``read_failed``; never free text."""
    if not code or len(code) > MAX_FAILURE_CODE_LENGTH or not _FAILURE_CODE_PATTERN.match(code):
        raise SessionError("A failure code must be a short lowercase identifier.")
    return code
