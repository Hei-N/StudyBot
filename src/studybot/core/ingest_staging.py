"""StudyBot's private staging area for files handed to the engine for import.

The native layer copies a user-selected file here and gives the engine only an
opaque staging id. The engine resolves ids inside this one directory; it never
receives, and never opens, a path inside a user's folder. This module deletes
only files in the staging directory, never anything in a library source.
"""

from __future__ import annotations

import logging
import re
import stat
import time
import uuid
from pathlib import Path

from studybot.core.exceptions import SessionError

logger = logging.getLogger(__name__)

ORPHAN_MAX_AGE_SECONDS = 24 * 60 * 60
_STAGED_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.pdf$")


class StagingError(SessionError):
    """A staging id is malformed or does not name a usable staged file."""


class StagingNotFoundError(StagingError):
    """No staged file exists for the id."""


class StagingArea:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def ensure(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self._root

    def resolve(self, staging_id: str) -> Path:
        """The staged file for ``staging_id``: a regular, non-symlink file directly inside the root."""
        name = f"{staging_id}.pdf" if isinstance(staging_id, str) else ""
        if not _STAGED_NAME.match(name):
            raise StagingError("The staging id is not valid.")
        path = self._root / name
        try:
            mode = path.lstat().st_mode
        except OSError:
            raise StagingNotFoundError("The staged file was not found.") from None
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise StagingError("The staged file is not usable.")
        return path

    def discard(self, staging_id: str) -> None:
        """Delete one staged file, if it is a valid staged regular file."""
        try:
            self.resolve(staging_id).unlink()
        except (StagingError, OSError):
            pass

    def cleanup_orphans(self, max_age_seconds: float = ORPHAN_MAX_AGE_SECONDS, now: float | None = None) -> int:
        """Remove old leftover staged files. Only exact staging names in the root are touched."""
        if not self._root.is_dir():
            return 0
        cutoff = (time.time() if now is None else now) - max_age_seconds
        removed = 0
        for entry in self._root.iterdir():
            if not _STAGED_NAME.match(entry.name):
                continue
            try:
                info = entry.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_mtime < cutoff:
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
        if removed:
            logger.debug("Removed %d orphaned staged files", removed)
        return removed


def new_staging_id() -> str:
    return str(uuid.uuid4())
