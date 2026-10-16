"""Study library business logic: sources, files, content identity and processing state.

Deterministic metadata management only. It never reads or deletes files, scans
directories, parses documents or calls a model; the repository is a plain data
layer. Hashing and processing are done by callers, which report results here.

Rules for ``register_or_update_file`` (content identity wins over metadata):

* new ``(source, relative_path)``: a ``pending`` record with a new id
* same path, same hash, or no hash supplied: state unchanged (a changed
  modification time alone never invalidates processed content)
* same path, a different known hash: a ``ready`` file becomes ``stale``; any
  other state is left as it is
* the id never changes
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from studybot.core.exceptions import (
    CourseNotFoundError,
    LibraryAuthorizationNotFoundError,
    LibraryConflictError,
    LibraryFileNotFoundError,
    LibrarySourceNotFoundError,
    LibraryStateError,
    SessionError,
)
from studybot.core.library import (
    LibraryFileState,
    LibrarySourceKind,
    can_transition,
    file_extension,
    normalize_content_hash,
    normalize_display_name,
    normalize_locator,
    normalize_relative_path,
    validate_authorization,
    validate_failure_code,
)
from studybot.storage.base import (
    UNSET,
    CourseRepository,
    LibraryFile,
    LibraryRepository,
    LibrarySource,
    LibrarySourceAuthorization,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LibraryService:
    """Create and organize library sources, track their files and enforce state rules."""

    def __init__(self, repository: LibraryRepository, course_repository: CourseRepository) -> None:
        self._library = repository
        self._courses = course_repository

    # --- sources -------------------------------------------------------------------

    def create_source(
        self,
        kind: LibrarySourceKind | str,
        display_name: str,
        locator: str,
        course_id: str | None = None,
    ) -> LibrarySource:
        try:
            kind = LibrarySourceKind(kind)
        except ValueError:
            raise SessionError("Unsupported source kind.") from None
        display_name = normalize_display_name(display_name)
        locator = normalize_locator(locator)
        self._require_course(course_id)
        if self._library.find_source(kind, locator) is not None:
            raise LibraryConflictError("That source is already in the library.")
        source = self._library.create_source(str(uuid.uuid4()), course_id, kind, display_name, locator)
        logger.debug("Created library source %s (%s)", source.id, kind.value)
        return source

    def get_source(self, source_id: str) -> LibrarySource | None:
        return self._library.get_source(source_id)

    def list_sources(self, *, course_id: str | None = UNSET) -> list[LibrarySource]:  # type: ignore[assignment]
        """Sources, optionally only those of one course (``None`` selects general material)."""
        return self._library.list_sources(course_id=course_id)

    def assign_source_to_course(self, source_id: str, course_id: str) -> LibrarySource:
        self._require_source(source_id)
        self._require_course(course_id)
        return self._library.update_source(source_id, course_id=course_id)

    def unassign_source_from_course(self, source_id: str) -> LibrarySource:
        self._require_source(source_id)
        return self._library.update_source(source_id, course_id=None)

    def delete_source(self, source_id: str) -> LibrarySource:
        """Delete a source and its file records. Never touches the real files."""
        source = self._require_source(source_id)
        self._library.delete_source(source_id)
        logger.debug("Deleted library source %s", source_id)
        return source

    # --- authorization -------------------------------------------------------------
    #
    # The payload is an opaque grant produced and read only by the platform's native
    # layer; a stored locator is never proof of access.

    def authorize_local_folder(
        self, display_name: str, locator: str, platform: str, authorization_kind: str, payload: bytes
    ) -> tuple[LibrarySource, bool]:
        """Create a folder source with its authorization, or refresh an existing one's.

        Returns ``(source, created)``. An already-known folder keeps its id, name,
        course and files; only its authorization is replaced, and a failed
        replacement leaves the previous one in place.
        """
        validate_authorization(platform, authorization_kind, payload)
        display_name = normalize_display_name(display_name)
        locator = normalize_locator(locator)
        existing = self._library.find_source(LibrarySourceKind.LOCAL_FOLDER, locator)
        if existing is not None:
            self._library.save_authorization(existing.id, platform, authorization_kind, payload)
            return existing, False
        source = self._library.create_source_with_authorization(
            str(uuid.uuid4()), None, LibrarySourceKind.LOCAL_FOLDER, display_name, locator,
            platform, authorization_kind, payload,
        )
        logger.debug("Created authorized library source %s", source.id)
        return source, True

    def set_authorization(
        self, source_id: str, platform: str, authorization_kind: str, payload: bytes
    ) -> LibrarySource:
        """Replace a source's authorization (reauthorization or bookmark refresh)."""
        source = self._require_source(source_id)
        validate_authorization(platform, authorization_kind, payload)
        self._library.save_authorization(source_id, platform, authorization_kind, payload)
        return source

    def get_authorization(self, source_id: str) -> LibrarySourceAuthorization:
        self._require_source(source_id)
        authorization = self._library.get_authorization(source_id)
        if authorization is None:
            raise LibraryAuthorizationNotFoundError("This source has no stored authorization.")
        return authorization

    def authorized_source_ids(self) -> set[str]:
        return self._library.authorized_source_ids()

    # --- files ---------------------------------------------------------------------

    def register_or_update_file(
        self,
        source_id: str,
        relative_path: str,
        *,
        display_name: str | None = None,
        size_bytes: int | None = None,
        modified_at: str | None = None,
        content_hash: str | None = None,
    ) -> LibraryFile:
        """Record a file, or update its metadata in place (see the module docstring)."""
        self._require_source(source_id)
        relative_path = normalize_relative_path(relative_path)
        if size_bytes is not None and (isinstance(size_bytes, bool) or size_bytes < 0):
            raise SessionError("A file size cannot be negative.")
        if modified_at is not None and not modified_at.strip():
            raise SessionError("A modification time cannot be empty.")
        name = normalize_display_name(display_name) if display_name is not None else None
        digest = normalize_content_hash(content_hash) if content_hash is not None else None

        existing = self._library.find_file(source_id, relative_path)
        if existing is None:
            file = self._library.create_file(
                str(uuid.uuid4()),
                source_id,
                relative_path,
                name or relative_path.rsplit("/", 1)[-1],
                file_extension(relative_path),
                size_bytes,
                modified_at,
                digest,
            )
            logger.debug("Registered library file %s", file.id)
            return file

        updated = LibraryFile(**{slot: getattr(existing, slot) for slot in LibraryFile.__slots__})
        if name is not None:
            updated.display_name = name
        if size_bytes is not None:
            updated.size_bytes = size_bytes
        if modified_at is not None:
            updated.modified_at = modified_at
        if digest is not None:
            content_changed = existing.content_hash is not None and existing.content_hash != digest
            updated.content_hash = digest
            if content_changed and existing.processing_state is LibraryFileState.READY:
                updated.processing_state = LibraryFileState.STALE
        if updated == existing:
            return existing
        return self._library.save_file(updated)

    def get_file(self, file_id: str) -> LibraryFile | None:
        return self._library.get_file(file_id)

    def list_files(
        self, *, source_id: str | None = None, state: LibraryFileState | None = None
    ) -> list[LibraryFile]:
        return self._library.list_files(source_id=source_id, state=state)

    def delete_file(self, file_id: str) -> LibraryFile:
        """Delete a file record. Never touches the real file."""
        file = self._require_file(file_id)
        self._library.delete_file(file_id)
        return file

    # --- processing state ----------------------------------------------------------

    def begin_indexing(self, file_id: str) -> LibraryFile:
        """``pending`` or ``stale`` to ``indexing``."""
        file = self._require_file(file_id)
        self._check_transition(file, LibraryFileState.INDEXING)
        file.processing_state = LibraryFileState.INDEXING
        return self._library.save_file(file)

    def mark_ready(self, file_id: str, content_hash: str) -> LibraryFile:
        """``indexing`` to ``ready`` for the content with ``content_hash``.

        The hash must equal the file's current hash, so a result computed for older
        content can never be recorded as current.
        """
        file = self._require_file(file_id)
        digest = normalize_content_hash(content_hash)
        self._check_transition(file, LibraryFileState.READY)
        if file.content_hash is None or file.content_hash != digest:
            raise LibraryStateError("The processed content no longer matches the file.")
        file.processing_state = LibraryFileState.READY
        file.failure_code = None
        file.indexed_at = _now()
        return self._library.save_file(file)

    def mark_failed(self, file_id: str, failure_code: str) -> LibraryFile:
        """``indexing`` to ``failed`` with a short machine-readable code."""
        file = self._require_file(file_id)
        code = validate_failure_code(failure_code)
        self._check_transition(file, LibraryFileState.FAILED)
        file.processing_state = LibraryFileState.FAILED
        file.failure_code = code
        return self._library.save_file(file)

    def mark_stale(self, file_id: str) -> LibraryFile:
        """``ready`` to ``stale``."""
        file = self._require_file(file_id)
        self._check_transition(file, LibraryFileState.STALE)
        file.processing_state = LibraryFileState.STALE
        return self._library.save_file(file)

    def retry_file(self, file_id: str) -> LibraryFile:
        """``failed`` to ``pending``, clearing the failure code."""
        file = self._require_file(file_id)
        self._check_transition(file, LibraryFileState.PENDING)
        file.processing_state = LibraryFileState.PENDING
        file.failure_code = None
        return self._library.save_file(file)

    # --- helpers -------------------------------------------------------------------

    def _require_source(self, source_id: str) -> LibrarySource:
        source = self._library.get_source(source_id)
        if source is None:
            raise LibrarySourceNotFoundError("No library source found.")
        return source

    def _require_file(self, file_id: str) -> LibraryFile:
        file = self._library.get_file(file_id)
        if file is None:
            raise LibraryFileNotFoundError("No library file found.")
        return file

    def _require_course(self, course_id: str | None) -> None:
        if course_id is not None and self._courses.get_course(course_id) is None:
            raise CourseNotFoundError(f"No course found matching '{course_id}'.")

    @staticmethod
    def _check_transition(file: LibraryFile, target: LibraryFileState) -> None:
        if not can_transition(file.processing_state, target):
            raise LibraryStateError(
                f"A {file.processing_state.value} file cannot become {target.value}."
            )
