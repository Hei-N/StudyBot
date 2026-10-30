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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

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
    FAILURE_INTERRUPTED,
    LibraryFileState,
    LibrarySourceKind,
    UPLOADS_DISPLAY_NAME,
    UPLOADS_LOCATOR,
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


@dataclass(frozen=True, slots=True)
class PdfImportPlan:
    """What an import must do next: ``file`` is ``indexing`` when ``needs_extraction``."""

    file: LibraryFile
    needs_extraction: bool


#: Most files that can be attached to one chat message.
MAX_CHAT_ATTACHMENTS = 5
#: How long an unsent chat upload may sit unreferenced before startup cleanup removes it.
ABANDONED_UPLOAD_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class UploadPlan:
    """The next step for an uploaded PDF.

    ``duplicate``: ``file`` is the existing, current copy and nothing more is needed.
    Otherwise ``file`` is ``indexing`` and the private copy must be stored as ``stored_name``.
    ``replaced_names`` are private files of superseded records for the caller to delete.
    """

    file: LibraryFile
    stored_name: str
    duplicate: bool
    replaced_names: tuple[str, ...] = ()
    promoted: bool = False  # an existing chat-only copy was added to the library


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
        """User-visible sources (not the internal uploads source), optionally of one course
        (``None`` selects general material)."""
        sources = self._library.list_sources(course_id=course_id)
        return [s for s in sources if s.kind is not LibrarySourceKind.UPLOADS]

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
        if source.kind is LibrarySourceKind.UPLOADS:
            raise SessionError("The uploaded files source cannot be removed; remove its files instead.")
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

    def mark_ready(
        self,
        file_id: str,
        content_hash: str,
        *,
        page_count: int,
        text_page_count: int,
        processing_version: str,
        pages: Sequence[tuple[int, str]] | None = None,
    ) -> LibraryFile:
        """``indexing`` to ``ready`` for the content with ``content_hash``.

        The hash must equal the file's current hash, so a result computed for older
        content can never be recorded as current. When ``pages`` is given they
        replace the file's stored pages in the same transaction.
        """
        file = self._require_file(file_id)
        digest = normalize_content_hash(content_hash)
        if page_count < 0 or not 0 <= text_page_count <= page_count or not processing_version:
            raise SessionError("The processing result is not valid.")
        if pages is not None and [number for number, _ in pages] != list(range(1, page_count + 1)):
            raise SessionError("The extracted pages are not numbered 1 to the page count.")
        self._check_transition(file, LibraryFileState.READY)
        if file.content_hash is None or file.content_hash != digest:
            raise LibraryStateError("The processed content no longer matches the file.")
        file.processing_state = LibraryFileState.READY
        file.failure_code = None
        file.indexed_at = _now()
        file.page_count = page_count
        file.text_page_count = text_page_count
        file.processing_version = processing_version
        if pages is None:
            return self._library.save_file(file)
        return self._library.save_file_with_pages(file, pages)

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

    # --- direct uploads ------------------------------------------------------------
    #
    # Uploaded PDFs belong to one app-owned source of kind ``uploads``. A file's
    # ``relative_path`` is its private stored name (a UUID) and ``display_name`` is the
    # user's original filename; identity is the content hash, never the filename.

    def uploads_source(self) -> LibrarySource:
        existing = self._library.find_source(LibrarySourceKind.UPLOADS, UPLOADS_LOCATOR)
        if existing is not None:
            return existing
        return self._library.create_source(
            str(uuid.uuid4()), None, LibrarySourceKind.UPLOADS, UPLOADS_DISPLAY_NAME, UPLOADS_LOCATOR
        )

    def prepare_upload(
        self,
        display_name: str,
        *,
        size_bytes: int,
        content_hash: str,
        processing_version: str,
        in_library: bool = True,
    ) -> UploadPlan:
        """Decide what an upload needs: nothing (duplicate) or a new ``indexing`` record.

        The same bytes as a current upload are a duplicate. An older or unfinished copy
        of the same bytes is replaced by the new record. Another upload of those bytes
        that is still being processed is a conflict. ``in_library=False`` is a chat attachment
        that is not kept in the Study Library; a later library upload of the same bytes
        adds the existing copy to the library without extracting again.
        """
        name = normalize_display_name(display_name)
        digest = normalize_content_hash(content_hash)
        source = self.uploads_source()
        existing = self._library.find_file_by_hash(source.id, digest)
        replaced: list[str] = []
        if existing is not None:
            if existing.processing_state is LibraryFileState.INDEXING:
                raise LibraryStateError("This PDF is already being uploaded.")
            if existing.processing_state is LibraryFileState.READY and existing.processing_version == processing_version:
                if in_library and not existing.in_library:
                    existing.in_library = True
                    existing = self._library.save_file(existing)
                    return UploadPlan(existing, existing.relative_path, duplicate=True, promoted=True)
                return UploadPlan(existing, existing.relative_path, duplicate=True)
            self._library.delete_file(existing.id)
            replaced.append(existing.relative_path)
        stored_name = f"{uuid.uuid4()}.pdf"
        file = self.register_or_update_file(
            source.id, stored_name, display_name=name, size_bytes=size_bytes, content_hash=digest
        )
        if not in_library:
            file.in_library = False
            file = self._library.save_file(file)
        file = self.begin_indexing(file.id)
        return UploadPlan(file, stored_name, duplicate=False, replaced_names=tuple(replaced))

    def abort_upload(self, file_id: str) -> str | None:
        """Drop an upload's record and pages after a failure; returns its stored name."""
        file = self._library.get_file(file_id)
        if file is None:
            return None
        self._library.delete_file(file_id)
        return file.relative_path

    def list_uploaded_files(self, *, include_chat_only: bool = False) -> list[LibraryFile]:
        """Uploaded files kept in the Study Library (and, if asked, chat-only uploads too)."""
        source = self._library.find_source(LibrarySourceKind.UPLOADS, UPLOADS_LOCATOR)
        if source is None:
            return []
        files = self._library.list_files(source_id=source.id)
        return files if include_chat_only else [f for f in files if f.in_library]

    def delete_uploaded_file(self, file_id: str) -> tuple[LibraryFile, bool]:
        """Remove an uploaded file from the Study Library.

        A file still attached to a chat message is only taken out of the library (it stays
        as a chat attachment). Otherwise its record and pages are deleted. Returns
        ``(file, deleted)``; when ``deleted`` the caller removes the private copy.
        """
        file = self._require_upload(file_id)
        if self._library.count_attachment_references(file_id) > 0:
            file.in_library = False
            return self._library.save_file(file), False
        self._library.delete_file(file_id)
        return file, True

    def discard_chat_attachment(self, file_id: str) -> str | None:
        """Delete a chat-only upload that nothing references (a pending attachment removed
        before sending). Library files and referenced files are left alone. Returns the
        stored name when a record was deleted."""
        file = self._library.get_file(file_id)
        if file is None or file.in_library or not self._is_upload(file):
            return None
        if self._library.count_attachment_references(file_id) > 0:
            return None
        self._library.delete_file(file_id)
        return file.relative_path

    def release_chat_files(self, file_ids: Sequence[str]) -> list[str]:
        """After chat messages were deleted: drop chat-only uploads that lost their last
        reference. Returns the stored names to remove."""
        return [name for file_id in dict.fromkeys(file_ids) if (name := self.discard_chat_attachment(file_id))]

    def collect_abandoned_chat_uploads(self, older_than_seconds: float = ABANDONED_UPLOAD_SECONDS) -> list[str]:
        """Startup cleanup of chat-only uploads never sent (and so never referenced)."""
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_seconds
        stale = [
            f.id
            for f in self.list_uploaded_files(include_chat_only=True)
            if not f.in_library and datetime.fromisoformat(f.updated_at).timestamp() < cutoff
        ]
        return self.release_chat_files(stale)

    def resolve_chat_attachments(self, file_ids: Sequence[str]) -> list[LibraryFile]:
        """Validate files for attaching to a message: distinct, at most five, existing uploads
        that finished processing. Raises ``SessionError`` otherwise."""
        unique = list(dict.fromkeys(file_ids))
        if len(unique) > MAX_CHAT_ATTACHMENTS:
            raise SessionError(f"A message can have at most {MAX_CHAT_ATTACHMENTS} attachments.")
        files = []
        for file_id in unique:
            file = self._library.get_file(file_id) if isinstance(file_id, str) else None
            if file is None or not self._is_upload(file):
                raise LibraryFileNotFoundError("An attached file was not found.")
            if file.processing_state is not LibraryFileState.READY:
                raise LibraryStateError("An attached file is not ready yet.")
            files.append(file)
        return files

    def _is_upload(self, file: LibraryFile) -> bool:
        source = self._library.find_source(LibrarySourceKind.UPLOADS, UPLOADS_LOCATOR)
        return source is not None and file.source_id == source.id

    def _require_upload(self, file_id: str) -> LibraryFile:
        file = self._require_file(file_id)
        if not self._is_upload(file):
            raise LibraryFileNotFoundError("No uploaded file found.")
        return file

    def purge_failed_uploads(self) -> list[str]:
        """Delete uploads left ``failed`` (for example by a crash); returns their stored names."""
        names = []
        for file in self.list_uploaded_files(include_chat_only=True):
            if file.processing_state is LibraryFileState.FAILED:
                self._library.delete_file(file.id)
                names.append(file.relative_path)
        return names

    def uploaded_file_names(self) -> set[str]:
        return {file.relative_path for file in self.list_uploaded_files(include_chat_only=True)}

    # --- PDF import ----------------------------------------------------------------
    #
    # An import is three steps so the slow extraction runs outside the database
    # thread: ``prepare_pdf_import`` (short), extraction (caller), then
    # ``complete_pdf_import`` or ``fail_pdf_import`` (short, atomic).

    def prepare_pdf_import(
        self,
        source_id: str,
        relative_path: str,
        *,
        display_name: str | None,
        size_bytes: int,
        content_hash: str,
        processing_version: str,
    ) -> PdfImportPlan:
        """Register the file and decide whether it needs extracting.

        A ``ready`` file with the same hash and processing version is left alone
        (no extraction). Otherwise the file is moved to ``indexing``.
        """
        self._require_source(source_id)
        if self._library.get_authorization(source_id) is None:
            raise LibraryAuthorizationNotFoundError("This source has no stored authorization.")
        if file_extension(normalize_relative_path(relative_path)) != "pdf":
            raise SessionError("Only PDF files can be imported.")
        file = self.register_or_update_file(
            source_id, relative_path, display_name=display_name, size_bytes=size_bytes, content_hash=content_hash
        )
        if (
            file.processing_state is LibraryFileState.READY
            and file.content_hash == normalize_content_hash(content_hash)
            and file.processing_version == processing_version
        ):
            return PdfImportPlan(file, needs_extraction=False)
        if file.processing_state is LibraryFileState.INDEXING:
            raise LibraryStateError("This file is already being imported.")
        if file.processing_state is LibraryFileState.READY:
            file = self.mark_stale(file.id)  # same content, older processing version
        elif file.processing_state is LibraryFileState.FAILED:
            file = self.retry_file(file.id)
        return PdfImportPlan(self.begin_indexing(file.id), needs_extraction=True)

    def complete_pdf_import(
        self, file_id: str, content_hash: str, *, pages: Sequence[tuple[int, str]], processing_version: str
    ) -> LibraryFile:
        """Atomically store the pages and mark the file ``ready``."""
        text_pages = sum(1 for _, text in pages if text.strip())
        return self.mark_ready(
            file_id,
            content_hash,
            page_count=len(pages),
            text_page_count=text_pages,
            processing_version=processing_version,
            pages=pages,
        )

    def fail_pdf_import(self, file_id: str, failure_code: str) -> LibraryFile | None:
        """Record a failed import; does nothing if the file is gone or no longer ``indexing``."""
        file = self._library.get_file(file_id)
        if file is None or file.processing_state is not LibraryFileState.INDEXING:
            return file
        return self.mark_failed(file_id, failure_code)

    def recover_interrupted_imports(self) -> int:
        """Fail files left ``indexing`` by a previous process; no import survives a restart."""
        count = self._library.fail_indexing_files(FAILURE_INTERRUPTED)
        if count:
            logger.debug("Marked %d interrupted library files as failed", count)
        return count

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
