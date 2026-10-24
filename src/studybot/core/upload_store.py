"""StudyBot-owned storage for directly uploaded files (``<data dir>/library_files``).

An uploaded PDF is copied here once and named by a random UUID, never by the user's
filename. The original file is only ever read. This module deletes only files it
created in this directory, never anything in a user's folder.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

_STORED_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.pdf$")


def is_stored_name(name: str) -> bool:
    return bool(_STORED_NAME.match(name))


class UploadStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def ensure(self) -> Path:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self._root

    def path_for(self, stored_name: str) -> Path:
        """The private file for a stored name; the name must be one this store generates."""
        if not is_stored_name(stored_name):
            raise ValueError("not a stored upload name")
        return self._root / stored_name

    def store(self, source: Path, stored_name: str) -> Path:
        """Copy ``source`` to its private name, atomically and read-only to others (0600)."""
        destination = self.path_for(stored_name)
        self.ensure()
        partial = destination.with_suffix(".pdf.part")
        try:
            shutil.copyfile(source, partial)
            os.chmod(partial, 0o600)
            os.replace(partial, destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return destination

    def discard(self, stored_name: str) -> None:
        """Delete one private file, if it is a regular file with a valid stored name."""
        try:
            path = self.path_for(stored_name)
            if stat.S_ISREG(path.lstat().st_mode):
                path.unlink()
        except (ValueError, OSError):
            pass

    def cleanup_orphans(self, known_names: set[str]) -> int:
        """Remove stored files (and abandoned partial copies) that no database row refers to."""
        if not self._root.is_dir():
            return 0
        removed = 0
        for entry in self._root.iterdir():
            name = entry.name
            partial = name.endswith(".part") and is_stored_name(name[: -len(".part")])
            if not (partial or (is_stored_name(name) and name not in known_names)):
                continue
            try:
                if stat.S_ISREG(entry.lstat().st_mode):
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
        if removed:
            logger.debug("Removed %d orphaned uploaded files", removed)
        return removed
