# Study Library foundation

Foundation for managing study material (slides, notes, PDFs) as records StudyBot can
track. It stores **metadata, access grants and page-level text of imported PDFs**. On macOS a user can
authorize a folder (see [Folder authorization](#folder-authorization)) and import PDFs
from it one at a time (see [PDF import](#pdf-import)), or upload a PDF directly without a folder (see
[Direct upload](#direct-upload)). There is no scanner, OCR,
chunking, embedding or retrieval yet.

```
Course
  ↓ optional association (course_id may be NULL)
LibrarySource      where material comes from (local_folder, local_file)
  ↓ 1..n
LibraryFile        one file: relative path, content hash, processing state
  ↓
LibraryPage        text of one PDF page (file id + 1-based page number)
  ↓
future: chunks → embeddings → retrieval
```

Code lives in `core/library.py` (types and rules), `core/library_service.py`
(`LibraryService`), `core/content_hash.py` (SHA-256 helper) and
`storage/sqlite_library_repository.py` (the only SQL). The service is reached as
`StudyBotApp.library`, and a few source endpoints (see [API_CONTRACT.md](API_CONTRACT.md)) back
a minimal Study Library screen. The model
provider knows nothing about the library.

## Records

- **LibrarySource**: `id`, `course_id` (nullable), `kind`, `display_name`, `locator`, timestamps.
  `(kind, locator)` is unique after light normalization (separators only; no
  symlink or case resolution).
- **LibraryFile**: `id`, `source_id`, `relative_path`, `display_name`, `extension`,
  `size_bytes`, `modified_at`, `content_hash`, `processing_state`, `failure_code`,
  `indexed_at`, timestamps. `(source_id, relative_path)` is unique. No file
  contents, extracted text or embeddings are stored.
- IDs are UUID strings, like courses and memories, and never change when metadata
  changes. Timestamps are ISO-8601 UTC strings.

## Rules

- **A locator is metadata, not permission.** Recording a source never reads its
  location. Authorizing access to a user-selected folder is a separate, later step.
- **Relative paths** use `/`, and absolute paths, drive letters and `..` are rejected.
- **Course deletion** sets `library_sources.course_id` to NULL; sources and files stay.
- **Source deletion** removes that source's file records (cascade). StudyBot never
  deletes real files; no code in the library deletes anything on disk.
- **Hashing** is lowercase hex SHA-256, streamed in 1 MiB chunks, computed only
  when a caller passes an explicit path. Creating or listing records reads no files.
- **Failure codes** are short identifiers such as `read_failed`, never tracebacks or text.

## Processing states

`pending → indexing → ready | failed`, `ready → stale → indexing`, `failed → pending`
(retry). Nothing else is allowed, and callers cannot set a state directly. `ready`
requires a content hash, and `mark_ready` must be given the hash that was
processed, which has to match the file's current hash.

## Content identity

Content is identified by hash, not by modification time or app launch:

| Update to an existing file | Result |
|---|---|
| same hash | stays `ready`, `indexed_at` kept |
| only modified time or size changed | stays `ready` |
| no hash supplied | state unchanged |
| a different known hash, file was `ready` | becomes `stale` |
| a different known hash, any other state | state unchanged |

The id is the same in every case. Future processing reuses results for an unchanged
hash and reprocesses only changed material.

## Direction

- Processing will consume `LibraryFile` records, and retrieval will consume what
  processing produces. Pages, slides and chunks will reference the file id.
- Requests like "PHY215 week 2 slide 3" should resolve structure first (course →
  source/file → slide) before any semantic search.
- Generated study artifacts (flashcards, practice questions, summaries) should keep
  provenance: course, source, file and page/slide/chunk. Today's records carry the
  source id, file id, relative path and course association that this needs.

## Folder authorization

A source's `locator` is metadata, never permission. Access comes from a macOS
**security-scoped bookmark** created when the user picks a folder in the native open
panel, and nothing is inferred from a path string.

```
user → NSOpenPanel (folders only, one) → security-scoped bookmark (read-only)
     → Flutter authorization service → API → LibrarySource + opaque authorization
```

- **Who owns what.** The native Swift layer (`macos/Runner/LibraryAuthorization.swift`,
  channel `studybot/library_authorization`) creates and resolves bookmarks and starts and
  stops access. Flutter owns the access lifecycle (one lease per source, released on
  removal and exit). Python stores the bookmark as opaque bytes in
  `library_source_authorizations` and never interprets it.
- **Read-only.** The release app has `files.user-selected.read-only` and
  `files.bookmarks.app-scope`, stays sandboxed, and has no Full Disk Access or
  read-write entitlement. StudyBot never modifies a user's folder.
- **Restoring access.** When the Study Library screen opens, each stored bookmark is
  resolved (no folder contents are read). A stale bookmark is refreshed and saved. If
  resolution fails the source shows **Needs access** and the user must reauthorize; the
  stored path is never used as a fallback. Reauthorizing keeps the source id, and
  choosing a different folder is refused.
- **Duplicates.** Selecting a known folder again reuses its source and replaces only the
  authorization.
- **Removal** releases access and deletes the source, its authorization and its file
  records. The real folder is never touched. Deleting a course does not revoke access.
- **Sandbox boundary.** Holding access in the app process does **not** give the Python
  engine the same rights; that has not been proven and is not assumed. Python receives
  no paths to read. Future ingestion must be fed through an authorization-aware broker
  (bytes or streams from the native layer) or another mechanism proven to work in the
  sandbox, never a path used as proof of permission.
- **Probe.** The native `probeRead` call reads at most 16 bytes of one relative path inside
  an active lease and rejects absolute paths, `..` and symlinks that leave the folder. It
  is for verification only. Full symlink policy is left to the future scanner.
- **Future scanner.** It may only enumerate inside a currently authorized source. No
  authorization or an expired bookmark means no scan, never a fallback to the raw path.
- **Cross-platform.** Records and the API are platform-neutral (`platform`, `kind`,
  opaque payload); another OS can supply its own authorization without changing sources.

Nothing scans, hashes or indexes the selected folder yet.

## PDF import

Import is explicit and one file at a time: the user picks a PDF inside an authorized
source. There is no folder scan or watcher.

```
Import PDF → native picker (PDF only) → must be inside the authorized folder
  → private copy in <data dir>/ingest_staging/<uuid>.pdf → staging id
  → engine: SHA-256 → LibraryFile → PdfExtractor (PDFium) → library_pages
```

- **File-access broker.** The native layer, which holds the security-scoped access, checks
  the selection after the user picks it (it does not trust the panel's start folder): it
  must resolve to a regular PDF inside the authorized folder, so files outside, symlinks
  that escape, directories and non-PDFs are rejected. It then copies the file, read-only,
  into StudyBot's private staging folder. The engine receives only the staging id, never a
  path in the user's folder, and never treats a locator as permission.
- **Staging.** Ids are UUIDs; the engine resolves them only inside the staging root and
  rejects anything else (separators, `..`, symlinks, directories, missing files). The staged
  copy is deleted after every import outcome. Only old files with the exact staging name
  are cleaned up at engine start (24 hours), and nothing in a source is ever touched.
- **Extraction.** `PdfExtractor` returns the text of each page as PDFium (`pypdfium2`, BSD-3-Clause
  or Apache-2.0) produced it (line endings normalized, nothing rewritten, headers and footers
  kept). PDFium is not thread-safe, so extraction runs on one worker thread. Pages are
  1-based and every page has a row, including empty ones. A valid image-only PDF becomes
  `ready` with `text_page_count = 0`; there is no OCR. A password-protected PDF fails with
  `password_required`, a bad file with `invalid_pdf`. Limits (512 MiB file, 5000 pages,
  64 MiB of text) fail with a code.
- **Incremental.** Content identity is the hash plus `processing_version` (`pdf_text_v2`).
  Importing the same bytes again with the current version is skipped: no extraction, same
  file id, pages and `indexed_at`. A modification time alone changes nothing. Changed bytes
  or an older processing version re-extract into the same `LibraryFile`.
- **Atomic.** Pages, page counts, version and the `ready` state are written in one
  transaction, so a failure never leaves a partly replaced or half-ready file. Old pages
  stay until the new ones replace them.
- **Responsiveness.** Hashing and extraction run on a separate single-worker thread, never
  on the engine's SQLite thread. A file left `indexing` by a previous process is marked
  `failed` (`interrupted`) at startup and can be imported again.
- **Provenance.** A page is identified by `file_id + page_number`; the file gives the
  source, relative path and (through the source) the course.

**Rule for future retrieval:** page text is current evidence only when its file is `ready`
for the current content hash and processing version. Pages of `pending`, `indexing`,
`stale` or `failed` files must not be used.

Chunking, embeddings and retrieval will build on `library_pages` later. Not implemented:
OCR, PowerPoint, Word, folder scanning, citations.

## Direct upload

The simplest way to add a PDF: **Upload File** picks one PDF from anywhere on the Mac.
No folder authorization is needed, and the Authorized Folder flow is unchanged.

```
Upload File → native picker (PDF only) → private staged copy → staging id
  → engine: SHA-256 → extract → <data dir>/library_files/<uuid>.pdf + library_pages
```

- **StudyBot owns its copy.** The PDF is copied once into `<data dir>/library_files/` under a
  random UUID name (mode 0600), never under the user's filename. The user can delete or move
  the original and the library entry keeps working. The original is only read, never
  modified, renamed, moved or deleted. The API never returns private names or paths: an
  uploaded file's `relativePath` is its original filename.
- **Ownership model.** Uploads belong to one app-owned source of kind `uploads` (schema v9),
  created on first use. It has no locator on disk and no authorization, and it is hidden
  from the folder list and cannot be removed. Each upload is a normal `LibraryFile` with
  `relative_path = <uuid>.pdf` (its private name) and `display_name` = the original filename,
  so pages, states, cascades and extraction are exactly the same as for folder files.
  The alternative, a nullable `source_id`, would have meant rebuilding the file table.
- **Identity is the content hash.** The same bytes as a current upload is a duplicate:
  "This PDF is already in your library.", the existing record is reused and nothing is
  re-extracted. The same filename with different bytes is a separate file. An older or
  unfinished copy of the same bytes (for example after a parser upgrade) is replaced by the
  fresh upload.
- **Failure policy.** A failed upload (invalid or password-protected PDF, too large, storage
  or database error) leaves nothing: no record, no pages, no private copy, no staged copy.
  The user is told why and uploads again. Rows left failed or indexing by a crash, and private
  files with no row, are removed at engine start.
- **Delete.** Removing an upload deletes its record, its pages and StudyBot's private copy.
  The original is never touched. Removing a folder source does not affect uploads.
- **Same pipeline.** Hashing, `PdfExtractor`, limits, `processing_version`, the atomic page
  transaction and the `ready` rules are shared with the folder import; only how the file is
  acquired differs. Extraction runs off the SQLite thread.

## Chat attachments

A PDF attached in a chat uses the direct-upload pipeline above (staging, private copy, hashing,
`PdfExtractor`, pages); the only difference is `library_files.in_library = 0`, so it is not shown
in the Study Library and is assigned to no course. A message links to its files through
`message_attachments`; the row is written in the same transaction as the message.

- **Limits.** At most 5 distinct, ready PDFs per message.
- **Ownership.** A chat-only file is deleted when the user removes it before sending, and when the
  last chat that references it is cleared or deleted. Chat-only files never sent are removed at
  engine start after 24 hours. A file attached to a message cannot be deleted from under it: removing
  it from the Study Library only sets `in_library = 0`. Uploading the same bytes to the library promotes a chat-only copy.
- **Not used in answers.** The text is not added to prompts. Using attachments in answers is a later retrieval stage.

## Extraction engine and licensing

Extraction uses `pypdfium2` (PDFium), which is BSD-3-Clause / Apache-2.0 licensed, so it places no
copyleft obligation on StudyBot. An earlier version used PyMuPDF, which is AGPL-3.0 (or a paid
commercial license), and was replaced for that reason. Switching engines bumped
`processing_version` from `pdf_text_v1` to `pdf_text_v2`. Files already stored as `v1` keep
their pages (still valid evidence) and are re-extracted if the same file is uploaded or
imported again. Test PDFs are built in `tests/pdf_helpers.py` without any PDF library.
