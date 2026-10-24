"""PDF import orchestration for the API.

The slow work (hashing and text extraction) runs on a dedicated single-worker
executor, never on the engine's SQLite thread. The engine thread is used only
for the short database steps before and after, so chat and health stay responsive.
The importer reads only StudyBot-owned staged files; it is never given a path in
a user's folder.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from studybot.api.engine import Engine
from studybot.core.content_hash import sha256_file
from studybot.core.exceptions import LibraryFileNotFoundError, LibraryStateError, SessionError
from studybot.core.ingest_staging import StagingArea
from studybot.core.library import FAILURE_CONTENT_CHANGED
from studybot.core.pdf_extractor import EXTRACTION_FAILED, MAX_PDF_BYTES, PdfExtractionError, PdfExtractor
from studybot.core.upload_store import UploadStore
from studybot.storage.base import LibraryFile

logger = logging.getLogger(__name__)

UPLOADED = "uploaded"
DUPLICATE = "duplicate"
STORE_FAILED = "store_failed"
IMPORTED = "imported"
UNCHANGED = "unchanged"
FAILED = "failed"


class PdfImporter:
    def __init__(
        self,
        engine: Engine,
        staging: StagingArea,
        extractor: PdfExtractor,
        executor: ThreadPoolExecutor,
        uploads: UploadStore,
    ) -> None:
        self._engine = engine
        self._staging = staging
        self._extractor = extractor
        self._executor = executor
        self._uploads = uploads

    async def upload_pdf(self, staging_id: str, display_name: str) -> tuple[str, LibraryFile | None, str | None]:
        """Add a directly uploaded PDF to StudyBot's own storage and extract its pages.

        Returns ``(outcome, file, failure_code)``. A failed upload leaves no record and no
        private copy. The staged copy is always discarded.
        """
        loop = asyncio.get_running_loop()
        library = self._engine.app.library
        try:
            path = self._staging.resolve(staging_id)
            size = path.stat().st_size
            if size > MAX_PDF_BYTES:
                raise SessionError("That PDF is too large to import.")
            digest = await loop.run_in_executor(self._executor, sha256_file, path)
            plan = await self._engine.call(
                library.prepare_upload,
                display_name,
                size_bytes=size,
                content_hash=digest,
                processing_version=self._extractor.processing_version,
            )
            if plan.duplicate:
                logger.debug("Upload matched existing file %s", plan.file.id)
                return DUPLICATE, plan.file, None
            file = plan.file
            try:
                private = await loop.run_in_executor(self._executor, self._uploads.store, path, plan.stored_name)
                result = await loop.run_in_executor(self._executor, self._extractor.extract, private)
                done = await self._engine.call(
                    library.complete_pdf_import,
                    file.id,
                    digest,
                    pages=[(page.page_number, page.text) for page in result.pages],
                    processing_version=self._extractor.processing_version,
                )
            except PdfExtractionError as error:
                return FAILED, await self._abort_upload(file.id, plan.stored_name), error.code
            except Exception:
                logger.exception("Upload failed for file %s", file.id)
                return FAILED, await self._abort_upload(file.id, plan.stored_name), STORE_FAILED
            for old in plan.replaced_names:
                self._uploads.discard(old)
            logger.debug("Uploaded PDF file %s: %d pages", file.id, result.page_count)
            return UPLOADED, done, None
        finally:
            self._staging.discard(staging_id)

    async def _abort_upload(self, file_id: str, stored_name: str) -> None:
        await self._engine.call(self._engine.app.library.abort_upload, file_id)
        self._uploads.discard(stored_name)
        return None

    async def import_pdf(
        self, source_id: str, staging_id: str, relative_path: str, display_name: str | None
    ) -> tuple[str, LibraryFile]:
        """Import one staged PDF. The staged copy is always discarded afterwards."""
        loop = asyncio.get_running_loop()
        library = self._engine.app.library
        try:
            path = self._staging.resolve(staging_id)
            size = path.stat().st_size
            if size > MAX_PDF_BYTES:
                raise SessionError("That PDF is too large to import.")
            started = time.monotonic()
            digest = await loop.run_in_executor(self._executor, sha256_file, path)
            plan = await self._engine.call(
                library.prepare_pdf_import,
                source_id,
                relative_path,
                display_name=display_name,
                size_bytes=size,
                content_hash=digest,
                processing_version=self._extractor.processing_version,
            )
            if not plan.needs_extraction:
                logger.debug("PDF import unchanged for file %s", plan.file.id)
                return UNCHANGED, plan.file
            return await self._extract_and_finish(loop, plan.file, path, digest, started)
        finally:
            self._staging.discard(staging_id)

    async def _extract_and_finish(self, loop, file: LibraryFile, path, digest: str, started: float):
        library = self._engine.app.library
        try:
            result = await loop.run_in_executor(self._executor, self._extractor.extract, path)
        except PdfExtractionError as error:
            return FAILED, await self._fail(file.id, error.code)
        except Exception:
            logger.exception("Unexpected PDF extraction failure for file %s", file.id)
            return FAILED, await self._fail(file.id, EXTRACTION_FAILED)
        extracted = time.monotonic()
        try:
            done = await self._engine.call(
                library.complete_pdf_import,
                file.id,
                digest,
                pages=[(page.page_number, page.text) for page in result.pages],
                processing_version=self._extractor.processing_version,
            )
        except LibraryFileNotFoundError:
            raise
        except LibraryStateError:
            return FAILED, await self._fail(file.id, FAILURE_CONTENT_CHANGED)
        logger.debug(
            "Imported PDF file %s: %d pages, extract %.0f ms, save %.0f ms",
            file.id,
            result.page_count,
            (extracted - started) * 1000,
            (time.monotonic() - extracted) * 1000,
        )
        return IMPORTED, done

    async def _fail(self, file_id: str, code: str) -> LibraryFile:
        logger.debug("PDF import failed for file %s (%s)", file_id, code)
        return await self._engine.call(self._engine.app.library.fail_pdf_import, file_id, code)
