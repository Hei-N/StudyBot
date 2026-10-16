"""Content hashing for library files: streamed SHA-256 of one explicit path."""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


def sha256_file(path: str | Path, *, chunk_size: int = CHUNK_SIZE) -> str:
    """Lowercase hex SHA-256 of the file at ``path``, read in ``chunk_size`` pieces.

    Reads only the given file; it never lists or walks directories.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
