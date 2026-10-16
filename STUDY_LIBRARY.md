# Study Library foundation

Foundation for managing study material (slides, notes, PDFs) as records StudyBot can
track. It stores **metadata only**. There is no folder picker, scanner, document
parsing, embedding or retrieval yet, and nothing here is available in the app.

```
Course
  ↓ optional association (course_id may be NULL)
LibrarySource      where material comes from (local_folder, local_file)
  ↓ 1..n
LibraryFile        one file: relative path, content hash, processing state
  ↓
future: pages / slides → chunks → embeddings → retrieval
```

Code lives in `core/library.py` (types and rules), `core/library_service.py`
(`LibraryService`), `core/content_hash.py` (SHA-256 helper) and
`storage/sqlite_library_repository.py` (the only SQL). The service is reached as
`StudyBotApp.library`; there are no API routes and no Flutter UI yet. The model
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
