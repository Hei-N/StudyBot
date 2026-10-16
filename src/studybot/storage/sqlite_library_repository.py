"""SQLite-backed ``LibraryRepository``.

One of the modules that contain SQL; see ``sqlite_repository.py``. Records are
metadata only and no method touches the filesystem.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from studybot.core.exceptions import LibraryConflictError
from studybot.core.library import LibraryFileState, LibrarySourceKind
from typing import Sequence

from studybot.storage.base import UNSET, LibraryFile, LibraryPage, LibrarySource, LibrarySourceAuthorization


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_source(row: sqlite3.Row) -> LibrarySource:
    return LibrarySource(
        id=row["id"],
        course_id=row["course_id"],
        kind=LibrarySourceKind(row["kind"]),
        display_name=row["display_name"],
        locator=row["locator"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_file(row: sqlite3.Row) -> LibraryFile:
    return LibraryFile(
        id=row["id"],
        source_id=row["source_id"],
        relative_path=row["relative_path"],
        display_name=row["display_name"],
        extension=row["extension"],
        size_bytes=row["size_bytes"],
        modified_at=row["modified_at"],
        content_hash=row["content_hash"],
        processing_state=LibraryFileState(row["processing_state"]),
        failure_code=row["failure_code"],
        indexed_at=row["indexed_at"],
        page_count=row["page_count"],
        text_page_count=row["text_page_count"],
        processing_version=row["processing_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SQLiteLibraryRepository:
    """``LibraryRepository`` over a shared SQLite connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def create_source(
        self, source_id: str, course_id: str | None, kind: LibrarySourceKind, display_name: str, locator: str
    ) -> LibrarySource:
        now = _now()
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO library_sources (id, course_id, kind, display_name, locator, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (source_id, course_id, kind.value, display_name, locator, now, now),
                )
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error):
                raise LibraryConflictError("That source is already in the library.") from None
            raise
        return LibrarySource(source_id, course_id, kind, display_name, locator, now, now)

    def get_source(self, source_id: str) -> LibrarySource | None:
        row = self._conn.execute("SELECT * FROM library_sources WHERE id = ?", (source_id,)).fetchone()
        return _row_to_source(row) if row is not None else None

    def find_source(self, kind: LibrarySourceKind, locator: str) -> LibrarySource | None:
        row = self._conn.execute(
            "SELECT * FROM library_sources WHERE kind = ? AND locator = ?", (kind.value, locator)
        ).fetchone()
        return _row_to_source(row) if row is not None else None

    def list_sources(self, *, course_id: str | None = UNSET) -> list[LibrarySource]:  # type: ignore[assignment]
        query = "SELECT * FROM library_sources"
        params: tuple = ()
        if course_id is None:
            query += " WHERE course_id IS NULL"
        elif course_id is not UNSET:
            query += " WHERE course_id = ?"
            params = (course_id,)
        rows = self._conn.execute(query + " ORDER BY updated_at DESC, created_at DESC, id", params).fetchall()
        return [_row_to_source(row) for row in rows]

    def update_source(
        self, source_id: str, *, course_id: str | None = UNSET, display_name: str | None = None  # type: ignore[assignment]
    ) -> LibrarySource:
        assignments = ["updated_at = ?"]
        params: list = [_now()]
        if course_id is not UNSET:
            assignments.append("course_id = ?")
            params.append(course_id)
        if display_name is not None:
            assignments.append("display_name = ?")
            params.append(display_name)
        with self._conn:
            self._conn.execute(
                f"UPDATE library_sources SET {', '.join(assignments)} WHERE id = ?", (*params, source_id)
            )
        return self.get_source(source_id)

    def delete_source(self, source_id: str) -> None:
        # ON DELETE CASCADE removes the source's file records in the same statement.
        with self._conn:
            self._conn.execute("DELETE FROM library_sources WHERE id = ?", (source_id,))

    def create_file(
        self,
        file_id: str,
        source_id: str,
        relative_path: str,
        display_name: str,
        extension: str | None,
        size_bytes: int | None,
        modified_at: str | None,
        content_hash: str | None,
    ) -> LibraryFile:
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO library_files (id, source_id, relative_path, display_name, extension, size_bytes, "
                "modified_at, content_hash, processing_state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_id, source_id, relative_path, display_name, extension, size_bytes,
                    modified_at, content_hash, LibraryFileState.PENDING.value, now, now,
                ),
            )
        return self.get_file(file_id)

    def get_file(self, file_id: str) -> LibraryFile | None:
        row = self._conn.execute("SELECT * FROM library_files WHERE id = ?", (file_id,)).fetchone()
        return _row_to_file(row) if row is not None else None

    def find_file(self, source_id: str, relative_path: str) -> LibraryFile | None:
        row = self._conn.execute(
            "SELECT * FROM library_files WHERE source_id = ? AND relative_path = ?", (source_id, relative_path)
        ).fetchone()
        return _row_to_file(row) if row is not None else None

    def list_files(
        self, *, source_id: str | None = None, state: LibraryFileState | None = None
    ) -> list[LibraryFile]:
        clauses: list[str] = []
        params: list = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if state is not None:
            clauses.append("processing_state = ?")
            params.append(state.value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM library_files{where} ORDER BY source_id, relative_path", params
        ).fetchall()
        return [_row_to_file(row) for row in rows]

    def save_file(self, file: LibraryFile) -> LibraryFile:
        with self._conn:
            self._update_file(file)
        return self.get_file(file.id)

    def save_file_with_pages(self, file: LibraryFile, pages: Sequence[tuple[int, str]]) -> LibraryFile:
        now = _now()
        with self._conn:
            self._conn.execute("DELETE FROM library_pages WHERE file_id = ?", (file.id,))
            self._conn.executemany(
                "INSERT INTO library_pages (file_id, page_number, text_content, char_count, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(file.id, number, text, len(text), now, now) for number, text in pages],
            )
            self._update_file(file)
        return self.get_file(file.id)

    def _update_file(self, file: LibraryFile) -> None:
        self._conn.execute(
            "UPDATE library_files SET display_name = ?, extension = ?, size_bytes = ?, modified_at = ?, "
            "content_hash = ?, processing_state = ?, failure_code = ?, indexed_at = ?, page_count = ?, "
            "text_page_count = ?, processing_version = ?, updated_at = ? WHERE id = ?",
            (
                file.display_name, file.extension, file.size_bytes, file.modified_at, file.content_hash,
                file.processing_state.value, file.failure_code, file.indexed_at, file.page_count,
                file.text_page_count, file.processing_version, _now(), file.id,
            ),
        )

    def list_pages(self, file_id: str) -> list[LibraryPage]:
        rows = self._conn.execute(
            "SELECT * FROM library_pages WHERE file_id = ? ORDER BY page_number", (file_id,)
        ).fetchall()
        return [LibraryPage(r["file_id"], r["page_number"], r["text_content"], r["char_count"]) for r in rows]

    def fail_indexing_files(self, failure_code: str) -> int:
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE library_files SET processing_state = ?, failure_code = ?, updated_at = ? "
                "WHERE processing_state = ?",
                (LibraryFileState.FAILED.value, failure_code, _now(), LibraryFileState.INDEXING.value),
            )
        return cursor.rowcount

    def delete_file(self, file_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM library_files WHERE id = ?", (file_id,))

    def create_source_with_authorization(
        self,
        source_id: str,
        course_id: str | None,
        kind: LibrarySourceKind,
        display_name: str,
        locator: str,
        platform: str,
        authorization_kind: str,
        payload: bytes,
    ) -> LibrarySource:
        now = _now()
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO library_sources (id, course_id, kind, display_name, locator, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (source_id, course_id, kind.value, display_name, locator, now, now),
                )
                self._conn.execute(
                    "INSERT INTO library_source_authorizations "
                    "(source_id, platform, authorization_kind, authorization_data, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (source_id, platform, authorization_kind, payload, now, now),
                )
        except sqlite3.IntegrityError as error:
            if "UNIQUE" in str(error):
                raise LibraryConflictError("That source is already in the library.") from None
            raise
        return LibrarySource(source_id, course_id, kind, display_name, locator, now, now)

    def save_authorization(
        self, source_id: str, platform: str, authorization_kind: str, payload: bytes
    ) -> LibrarySourceAuthorization:
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO library_source_authorizations "
                "(source_id, platform, authorization_kind, authorization_data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_id) DO UPDATE SET platform = excluded.platform, "
                "authorization_kind = excluded.authorization_kind, "
                "authorization_data = excluded.authorization_data, updated_at = excluded.updated_at",
                (source_id, platform, authorization_kind, payload, now, now),
            )
        return self.get_authorization(source_id)

    def get_authorization(self, source_id: str) -> LibrarySourceAuthorization | None:
        row = self._conn.execute(
            "SELECT * FROM library_source_authorizations WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        return LibrarySourceAuthorization(
            source_id=row["source_id"],
            platform=row["platform"],
            kind=row["authorization_kind"],
            payload=bytes(row["authorization_data"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def authorized_source_ids(self) -> set[str]:
        rows = self._conn.execute("SELECT source_id FROM library_source_authorizations").fetchall()
        return {row["source_id"] for row in rows}
