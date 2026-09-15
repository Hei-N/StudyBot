# Study Bot (v0.2, Stage 5 — Teaching Modes)

A local-first personal study assistant. **Stage 5** adds five explicit
teaching modes — Teach, Homework, Quick Answer, Practice, and Exam — that
change how the assistant behaves in a given chat, on top of the course
organization and persistent chat foundation from earlier stages. This is a
first generation of mode *behavior* (prompt-based, per chat); there is
still no mastery tracking, scoring, or a real exam engine.

The product name is provisional; the internal Python package is `studybot`.

## What this is (and isn't) right now

- ✅ Five teaching modes, one active per chat: **Teach** (step-by-step
  tutoring), **Homework** (guided help, full solution on request),
  **Quick Answer** (direct and concise), **Practice** (one question at a
  time with feedback), **Exam** (no hints until you answer)
- ✅ Mode is per-chat, not global or per-course — the same course can have
  a Teach chat, a Homework chat, and an Exam chat side by side, each
  keeping its own mode independently
- ✅ New chats always start in Teach mode — a chat never inherits whatever
  mode was active elsewhere
- ✅ Changing mode persists immediately, applies starting with the next
  message, and never touches messages, title, or course; it's never
  recorded as a chat message
- ✅ Courses: create, list, open, edit, delete — each with an optional
  code/term/description, full Unicode support (including Burmese, Chinese,
  emoji)
- ✅ Chats can belong to one course, or none ("General") — course membership
  is purely organizational and **never merges conversation history** between
  chats, even chats in the same course
- ✅ The model is told the active course (name, code, term, description)
  and the active teaching mode via small, independently-composed pieces of
  context — it never sees database ids or timestamps
- ✅ Multiple persisted chats, each with its own isolated history, surviving
  restarts — the most recently updated chat resumes automatically, with
  its course and teaching mode reconstructed with it
- ✅ Deterministic, local chat titles generated from the first message
  (no LLM call involved)
- ✅ A real local model backend (Ollama) or a deterministic `MockModel`,
  swappable behind a `ModelProvider` interface that knows nothing about
  Ollama, courses, or teaching modes
- ✅ Streaming responses; a completed stream is persisted as exactly one
  assistant message, a failed or abandoned one persists none
- ✅ `/status`: on-demand provider/server/model health check
- ✅ Centralized configuration and privacy-safe logging (prompts, responses,
  chat titles, and course names/descriptions are never written to logs)
- ❌ No cloud AI provider (OpenAI, Anthropic, etc.) — local-only
- ❌ No mastery tracking, skill model, scoring, or spaced repetition — mode
  adaptation (e.g. Practice's difficulty) only ever uses the current
  conversation, nothing persisted
- ❌ No formal exam engine, timers, or grading database — Exam mode is a
  prompt-based behavior, not a real assessment system
- ❌ No RAG, embeddings, PDFs, file uploads, OCR, screenshots, vision, or
  long-term learning memory
- ❌ No desktop GUI, filesystem/browser/calendar agent access, or cloud sync
- ❌ No automatic model downloading — you always run `ollama pull` yourself

## Prerequisites

- macOS
- Python 3.12 or newer
- [Ollama](https://ollama.com) — only required if you want real model
  responses; `mock` mode needs nothing beyond Python

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Installing Ollama and a model (optional, for real responses)

```bash
brew install ollama      # or download from https://ollama.com
ollama serve              # start the local server (or use the Ollama app)
ollama pull qwen3:4b       # download the default development model (~2.5GB)
```

Study Bot never downloads a model on your behalf — if the configured model
isn't present locally, it tells you the exact `ollama pull` command to run.

### Development-environment note: iCloud Desktop sync

If this project lives under `~/Desktop` (or anywhere else covered by
iCloud's "Desktop & Documents" sync), macOS can intermittently evict and
re-fetch small files in `.venv`, which occasionally makes the editable
install briefly unreadable and `python -m studybot` fail with
`ModuleNotFoundError: No module named 'studybot'` even though `pip show
studybot` reports it as installed. **This is an iCloud/filesystem quirk of
this development machine, not a Study Bot bug or feature — the application
itself contains no code that detects or works around it.**

A reliable workaround for a shell session:

```bash
export PYTHONPATH="$PWD/src"
```

Run this once per new terminal (after `source .venv/bin/activate`) if you
hit that error. The permanent fix is either excluding `.venv` from iCloud
sync or moving the project outside `~/Desktop`.

## Running the chatbot

```bash
python -m studybot
```

or, if installed as a script (via the venv above):

```bash
studybot
```

By default the app uses `mock` (no server needed). To talk to a real local
model via Ollama:

```bash
STUDYBOT_MODEL_PROVIDER=ollama python -m studybot
```

Example session (Ollama mode, resuming a Homework-mode course chat):

```
Study Bot
Local study assistant

Provider: Ollama
Model: qwen3:4b
Course: University Physics I
Chat: Vectors homework
Mode: Homework

Type /help for commands.
You > A car starts from rest and accelerates at 3 m/s^2 for 4 seconds. Help me solve it.
Bot > Let's identify what we know first: initial velocity is 0...
You > /quit
Goodbye.
```

If no chats exist yet, `Chat: Untitled`, `Course: General`, and `Mode:
Teach` are shown, and nothing is written to the database until you
actually send a message — launching and quitting without chatting (or
just opening a course to look at it) leaves no empty row behind.

### Commands

| Command             | Description                                              |
|----------------------|-------------------------------------------------------------|
| `/help`              | List available commands                                     |
| `/history`           | Show the active chat's conversation history                 |
| `/status`            | Show model provider connection/availability status          |
| `/new`               | Start a new chat (in the active course, if any; always Teach mode) |
| `/chats`             | List chats in the active course, or General if none is active |
| `/chats all`         | List every chat regardless of course                          |
| `/open <id>`         | Switch to an existing chat by id or unique id prefix          |
| `/rename <title>`    | Rename the active chat                                        |
| `/clear`             | Remove the active chat's messages — asks to confirm; keeps the chat itself |
| `/delete`            | Delete the active chat entirely — asks to confirm             |
| `/mode`              | Show the active chat's teaching mode and all available modes  |
| `/mode <name>`       | Change the active chat's teaching mode                        |
| `/course new`        | Create a course (interactive) and activate it                 |
| `/course list`       | List courses (`*` marks the active one)                        |
| `/course open <id>`  | Activate a course by id or unique id prefix                    |
| `/course info`       | Show the active course's details and chat count                |
| `/course edit`       | Edit the active course's fields (interactive; see below)       |
| `/course delete`     | Delete the active course — asks to confirm; its chats survive  |
| `/course leave`      | Leave the active course, back to General                       |
| `/chat course <id>`  | Move the active chat into a course                              |
| `/chat course none`  | Remove the active chat from its course (back to General)        |
| `/quit`              | Exit                                                            |

`Ctrl+C` and `Ctrl+D` (EOF) both exit cleanly with no stack trace, and
close the database connection on the way out. The same applies mid-prompt
in `/course new`/`/course edit`/any `[y/N]` confirmation — it cancels that
one action rather than exiting the whole app.

**`/clear` vs `/delete`:** `/clear` empties a chat's messages but keeps its
title, id, course, and teaching mode — use it to start a topic over
without losing the chat slot. `/delete` removes the chat (and its
messages) entirely. Both destroy data, so both ask `[y/N]` first,
defaulting to No.

**`/course edit`** shows each field's current value and lets you type a new
one, leave it blank to keep the current value, or type `-` to clear an
optional field (code/term/description — the name itself can't be cleared,
only changed).

**`/course delete`** never deletes chats or messages — they become
"General" (unassigned). Deleting the *active* course keeps you on the same
chat; it just stops showing course context to the model.

### Teaching modes

| Mode       | `/mode` name | What it does |
|------------|--------------|--------------|
| Teach      | `teach`      | Acts as a tutor: explains clearly, adapts depth, breaks ideas into steps, corrects misconceptions. Doesn't force a question after every reply or pad answers. **Default for every new chat.** |
| Homework   | `homework` (alias `hw`) | Guides you through solving your own homework — identifies what's asked, relevant formulas, and walks step-by-step — but gives the full solution immediately if you explicitly ask for it (e.g. "just solve it"). |
| Quick Answer | `quick` (alias `qa`) | Answers directly and concisely, with only the essential reasoning. Does not turn into a tutoring session unless you ask. |
| Practice   | `practice`   | Presents one practice question at a time, waits for your answer, evaluates it, explains mistakes, and adjusts difficulty based on the conversation so far. |
| Exam       | `exam`       | Simulates exam conditions: presents a question with no hints and gives no feedback until you submit an answer. |

```
You > /mode
Teaching mode: Teach

Available:
  teach      Step-by-step tutoring that builds understanding.
  homework   Guided homework help; full solutions on request.
  quick      Direct, concise answers with minimal explanation.
  practice   One practice question at a time, with feedback.
  exam       Exam-style questions with no hints until you answer.

You > /mode homework
Teaching mode changed to Homework.
```

Mode is entirely prompt-based behavior guidance for this stage — there is
no scoring, no mastery model, and no formal exam engine behind it yet.
Expect the wording of each mode's instructions to be refined after more
real-world use; it lives in one place (`core/mode_prompts.py`) specifically
so that's easy to do without hunting through the codebase.

## Configuration

Configuration is centralized in `studybot.config.settings.Settings` and read
from environment variables (all optional, sensible defaults apply):

| Variable                     | Default                                    | Purpose                                   |
|-------------------------------|---------------------------------------------|--------------------------------------------|
| `STUDYBOT_ENV`                 | `development`                               | Environment name                          |
| `STUDYBOT_LOG_LEVEL`           | `INFO`                                       | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `STUDYBOT_MODEL_PROVIDER`      | `mock`                                       | `mock` or `ollama`                        |
| `STUDYBOT_DATA_DIR`            | `~/Library/Application Support/StudyBot`     | Where the chat database (and future data) lives |
| `STUDYBOT_SYSTEM_PROMPT`       | *(see `core/prompts.py`)*                    | Overrides the baseline system prompt      |
| `STUDYBOT_OLLAMA_HOST`         | `http://localhost:11434`                     | Ollama server URL                         |
| `STUDYBOT_OLLAMA_MODEL`        | `qwen3:4b`                                   | Ollama model name/tag to use              |
| `STUDYBOT_OLLAMA_TIMEOUT`      | `120`                                        | Request timeout in seconds                |
| `STUDYBOT_OLLAMA_KEEP_ALIVE`   | *(Ollama's own default, currently `5m`)*     | How long Ollama keeps the model loaded    |

Examples:

```bash
STUDYBOT_LOG_LEVEL=DEBUG python -m studybot
STUDYBOT_MODEL_PROVIDER=ollama STUDYBOT_OLLAMA_MODEL=qwen3:8b python -m studybot
```

The model name is entirely configuration-driven — swapping in `qwen3:8b`,
`qwen3:14b`, a Gemma or Llama model, or any other model already pulled into
Ollama is just an environment variable change; nothing in the code is tied
to Qwen specifically.

## Where chats and courses are stored

Everything lives in one local SQLite database at
`STUDYBOT_DATA_DIR/studybot.db` (default:
`~/Library/Application Support/StudyBot/studybot.db`). The schema is
created and upgraded automatically — there's nothing to run by hand. A
database from any earlier version is upgraded the first time this version
opens it, in one atomic step per version bump: it either fully succeeds or
leaves your existing database completely untouched, chained as needed
(e.g. a Version 0.1 database goes v1 → v2 → v3 in one open). Existing
chats keep their ids, titles, timestamps, course assignments, and
messages exactly; they simply default to Teach mode until you change it.
You never need to open this database file directly; manage everything
through the app's commands.

**Resetting local data:** to start over with a clean slate, quit Study Bot
and delete the database file:

```bash
rm ~/Library/Application Support/StudyBot/studybot.db
```

This removes all chats, courses, and mode assignments — do it only if you
actually want to lose your local history.

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

All tests are deterministic and self-contained: they fake the `ollama`
client boundary (`tests/fake_ollama.py`) rather than requiring a running
Ollama server or a downloaded model, and every persistence test opens its
own SQLite database under pytest's `tmp_path` — no test reads or writes
`~/Library/Application Support/StudyBot` or any other real user data.

## Troubleshooting

**"Could not connect to the local Ollama service."** — Ollama isn't
running. Start it with `ollama serve` (or open the Ollama app), then check
`STUDYBOT_OLLAMA_HOST` matches where it's listening (default
`http://localhost:11434`). Run `/status` in the chat to confirm.

**"Model 'x' is not available locally. Run: ollama pull x"** — the
configured model hasn't been downloaded. Run the suggested `ollama pull`
command yourself; Study Bot deliberately never downloads models
automatically.

**`ModuleNotFoundError: No module named 'studybot'`** — see the iCloud
Desktop sync note above.

## Privacy

This is a local-first project. There is no analytics, telemetry, cloud
logging, cloud backup, or remote error reporting anywhere in the codebase,
and inference runs entirely against your local Ollama server. Chat, course,
and mode data live only in your local SQLite database. Application logs
record message *counts*, provider/model names, database *paths* (never
contents), and structural error details for debugging — never the actual
content of prompts, model responses, chat titles, or course names/codes/
descriptions. A teaching-mode identifier (e.g. `mode=homework`) may appear
in a debug log; that's fine, it carries no personal content. Course and
mode context is sent to the configured model provider only when needed to
answer within that chat — under the default Ollama configuration, that
stays entirely on your machine. This matters more with each stage:
eventually Study Bot will read your course materials, screenshots, and
other personal files, so privacy-safe logging is the default from the
start, not an afterthought.

## Architecture

```
Interface (CLI today; desktop UI / macOS assistant later)
        ↓
StudyBotApp (src/studybot/app.py)
        ├── CourseService ─────────────┐
        └── SessionService             │
              ↓              ↓         │
        ChatService   ChatRepository   │
              ↓              ↓         │
        ModelProvider  SQLiteChatRepo  │
                              ↓        ↓
                        (shared SQLite connection)
                              ↑
                     SQLiteCourseRepository
                              ↑
                       CourseRepository
```

Model inference, persistence, course organization, and teaching mode are
four separate concerns. `SessionService` calls `ChatService` for a
response and, independently, mirrors whatever new messages appear in
`ChatService.history` into `ChatRepository` — neither `ChatService` nor
`ModelProvider` knows persistence, courses, or teaching modes exist.
`SessionService` reads (but never writes) `CourseRepository` only to build
the minimal course context fed into the system prompt; all course business
rules (validation, create/edit/delete) live in `CourseService`. Teaching
mode is simpler still: a plain field on `ChatSession`, fed into the same
prompt-composition function as another independent section — there is no
separate mode "service" because there's no mode-specific business logic to
own beyond get/set, which live directly on `SessionService`.

This design is explicitly UI-independent: nothing in `core/`, `models/`,
or `storage/` imports or assumes anything about the CLI, a future desktop
UI, or any transport/IPC layer. A future UI can construct its own
`StudyBotApp` and call `session_service.get_teaching_mode()` /
`set_teaching_mode()` / `studybot.core.teaching_mode.all_modes()` directly
to build a native mode picker, exactly the way the CLI's `/mode` command
does.

Key modules:

- `src/studybot/__main__.py` — `python -m studybot` entry point
- `src/studybot/cli.py` — interactive terminal shell; no core logic, no raw
  SQL, no Ollama-specific code — only `StudyBotApp`/`SessionService`/
  `CourseService`/`core.teaching_mode`
- `src/studybot/app.py` — builds settings, logging, the model, the shared
  SQLite connection, both repositories, and both services for a run of the
  app; closes the database connection on shutdown
- `src/studybot/config/settings.py` — typed, validated configuration,
  including `database_path` (derived from `data_dir`)
- `src/studybot/core/messages.py` — typed `Message`/`Role`
  (`system`/`user`/`assistant`)
- `src/studybot/core/prompts.py` — the shared baseline system prompt
- `src/studybot/core/teaching_mode.py` — the `TeachingMode` enum (pure
  domain data, no I/O), `TeachingModeInfo` display metadata, `all_modes()`
  (the catalog a mode picker renders), and `parse_teaching_mode()` for
  turning user/UI input into a `TeachingMode`
- `src/studybot/core/mode_prompts.py` — the concise instruction text for
  each mode, kept in one small module so it's easy to revise after
  real-world testing
- `src/studybot/core/context.py` — `CourseContext` and `build_system_prompt`,
  the single place baseline instructions, course context, and teaching-mode
  instructions are composed into one system prompt — kept separate from
  both `core/prompts.py`/`core/mode_prompts.py` and any model provider so
  there's no scattered string concatenation elsewhere
- `src/studybot/core/titles.py` — deterministic, local chat-title
  generation from a chat's first message (no LLM call)
- `src/studybot/core/chat.py` — `ChatService`: in-memory history for the
  active chat, `send`/`send_streaming`, `clear`, `get_status`; can be
  seeded with restored history via its `history=` constructor argument
- `src/studybot/core/session_service.py` — `SessionService`: owns the
  active chat (and, implicitly, its course and teaching-mode context,
  both derived from fields on `active_session` — there is no separate
  "active course"/"active mode" state to fall out of sync),
  creates/lists/opens/renames/deletes/moves chats, exposes
  `get_teaching_mode()`/`set_teaching_mode()`, and persists new messages
  after each successful `ChatService` call by diffing its history
  before/after
- `src/studybot/core/course_service.py` — `CourseService`: course
  validation (name required and length-limited; optional fields trimmed;
  full Unicode support) and CRUD, independent of `SessionService`
- `src/studybot/core/exceptions.py` — `StudyBotError` and subclasses,
  including `SessionError` for chat/course navigation or validation
  problems (not found, ambiguous id prefix, empty name, ...)
- `src/studybot/models/` — unchanged since Stage 2 (`ModelProvider`,
  `MockModel`, `OllamaModel`, the provider factory); `OllamaModel` has no
  awareness of courses, teaching modes, or SQLite
- `src/studybot/storage/base.py` — `ChatRepository`/`CourseRepository`
  protocols and the `ChatSession`/`Course` domain types (`ChatSession`
  carries a typed `teaching_mode: TeachingMode`); nothing outside
  `storage/` sees a raw SQLite row
- `src/studybot/storage/database.py` — opens the one shared
  `sqlite3.Connection` both repositories use and applies schema migrations,
  versioned via SQLite's own `PRAGMA user_version` (currently `3`); each
  migration step runs in one explicit, all-or-nothing transaction, chained
  as needed (v1 → v2 → v3)
- `src/studybot/storage/sqlite_repository.py` / `sqlite_course_repository.py`
  — the **only** two modules allowed to contain SQL; parameterized queries
  only, for chats/messages and courses respectively. `sqlite_repository.py`
  converts the stored `teaching_mode` string to a `TeachingMode` at the
  repository boundary, falling back to the default mode (with a warning
  log containing only the invalid identifier, never chat content) if the
  stored value is ever unrecognized
- `src/studybot/logging_config.py` — console logging setup; quiet by
  default, verbosity controlled via `STUDYBOT_LOG_LEVEL`

A future backend — a different local model, hybrid routing, an encrypted
store, sync — can replace `OllamaModel` or either SQLite repository
independently, without touching `SessionService`, `CourseService`, the CLI,
or a future GUI. Choosing `mock` still runs with no Ollama installed,
exactly as in Stage 2.

### Streaming + persistence

`ModelProvider.stream()` yields content incrementally; `ChatService`
accumulates it and adds exactly one complete assistant message to its
in-memory history, but only once the stream finishes successfully — never
on failure or early abandonment (unchanged from Stage 2). `SessionService`
persists by comparing `ChatService.history` before and after each call, so
this guarantee carries through to storage automatically: a successful
exchange writes one user row and one assistant row; a failed or abandoned
one writes only the user row. No database row is ever written per token.

If the model fails after the user's message was already recorded, that
user message is deliberately left in the database (so the user can retry)
— Study Bot never inserts a synthetic assistant message like "Error:
model unavailable" into the conversation itself; errors are surfaced by
the CLI, not written into chat history. The same principle applies to
mode changes: `/mode homework` never inserts a "Mode changed to Homework"
message into the conversation either — the CLI prints a confirmation to
the terminal, but it's never part of what the model sees as history.

### Schema migrations (v1 → v2 → v3)

- **v1 → v2** (Stage 4): adds a `courses` table and a nullable
  `chats.course_id` referencing it with `ON DELETE SET NULL` — deleting a
  course never touches its chats or their messages.
- **v2 → v3** (Stage 5): adds `chats.teaching_mode` (`NOT NULL DEFAULT
  'teach'`) — every existing chat becomes Teach mode; nothing else changes.

Each step is one explicit SQL transaction (`BEGIN` ...
`commit()`/`rollback()` — plain DDL statements are *not* automatically
transactional in Python's `sqlite3` module, so this is done by hand): if
anything in a step fails, the database is left exactly as it was before
that step, not partially upgraded. Steps chain automatically (a v1
database run against this version goes straight to v3 in one `open`), a
brand-new database skips migration entirely and is created directly at the
current schema, and re-opening an already-current database is a no-op.

### Course organization semantics

A chat belongs to at most one course (or none — "General"); a course never
aggregates or shares chat history — it's purely an organizational label.
`/new` while a course is active creates the new chat inside that course
(always in Teach mode, regardless of what mode was active elsewhere);
`/new` in General creates an unassigned chat. Opening a course
(`/course open`) resumes its most recently updated chat, or starts a fresh
empty one scoped to that course if it has none yet — no database row is
written just from looking at a course. The model receives the active
course's name/code/term/description as a short block of context appended
after the baseline system prompt — never a database id or a timestamp, and
never persisted as a chat message.

### Teaching-mode semantics

Mode lives on the chat, not the course or the app: two chats in the same
course (or the same chat's own history) can be in completely different
modes, and switching one chat's mode never touches any other chat. A new
chat always starts in Teach mode regardless of what mode was active when
`/new` was run — modes are not inherited. Changing mode persists
immediately, takes effect starting with the next model request, and never
clears messages, creates a new chat, or alters the chat's course or title.

## Next planned stage

Stage 6+ will add persistent long-term learning memory, mastery tracking,
RAG over PDFs/notes/slides, embeddings, image/screenshot understanding,
quizzes, and eventually device/tool access — none of which exists yet.
