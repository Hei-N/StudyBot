# Study Bot (v0.1, Stage 3 — Persistent Chat Sessions)

A local-first personal study assistant. **Stage 3** adds persistent, local
SQLite-backed chat sessions on top of the real local LLM integration from
Stage 2: conversations survive restarts, and you can keep multiple separate
chats instead of one that resets every launch.

The product name is provisional; the internal Python package is `studybot`.

## What this is (and isn't) right now

- ✅ Multiple persisted chats, each with its own isolated history
- ✅ Chats survive restarting the app — the most recently updated chat
  resumes automatically
- ✅ Deterministic, local chat titles generated from the first message
  (no LLM call involved)
- ✅ A real local model backend (Ollama) or a deterministic `MockModel`,
  swappable behind a `ModelProvider` interface that knows nothing about
  Ollama — and, symmetrically, nothing in the model path knows SQLite exists
- ✅ Streaming responses; a completed stream is persisted as exactly one
  assistant message, a failed or abandoned one persists none
- ✅ `/status`: on-demand provider/server/model health check
- ✅ Centralized configuration and privacy-safe logging (prompts, responses,
  and chat titles are never written to logs)
- ❌ No cloud AI provider (OpenAI, Anthropic, etc.) — local-only
- ❌ No courses, RAG, embeddings, PDFs, OCR, screenshots, long-term memory,
  mastery tracking, quizzes, or agent/tool-use behavior — all later work
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
studybot` reports it as installed. This is an iCloud/filesystem quirk, not
a Study Bot bug — Study Bot's code does nothing to detect or work around it.

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

Example session (Ollama mode, resuming a prior chat):

```
Study Bot
Local study assistant

Provider: Ollama
Model: qwen3:4b
Chat: Explain vectors please

Type /help for commands.
You > What's the difference between speed and velocity?
Bot > Speed is how fast something moves; velocity is speed with a direction...
You > /quit
Goodbye.
```

If no chats exist yet, `Chat: Untitled` is shown, and nothing is written to
the database until you actually send a message — launching and quitting
without chatting leaves no empty chat behind.

### Commands

| Command           | Description                                              |
|--------------------|-----------------------------------------------------------|
| `/help`            | List available commands                                    |
| `/history`         | Show the active chat's conversation history                |
| `/status`          | Show provider/server connection and model availability     |
| `/new`             | Start a new chat and switch to it                           |
| `/chats`           | List saved chats (`*` marks the active one)                 |
| `/open <id>`       | Switch to an existing chat by id or unique id prefix         |
| `/rename <title>`  | Rename the active chat                                       |
| `/clear`           | Remove the active chat's messages — asks to confirm; keeps the chat itself |
| `/delete`          | Delete the active chat entirely — asks to confirm            |
| `/quit`            | Exit                                                          |

`Ctrl+C` and `Ctrl+D` (EOF) both exit cleanly with no stack trace, and
close the database connection on the way out.

**`/clear` vs `/delete`:** `/clear` empties a chat's messages but keeps its
title and id — use it to start a topic over without losing the chat slot.
`/delete` removes the chat (and its messages) entirely. Both destroy data,
so both ask `[y/N]` first, defaulting to No.

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

## Where chats are stored

Conversations live in a local SQLite database at
`STUDYBOT_DATA_DIR/studybot.db` (default:
`~/Library/Application Support/StudyBot/studybot.db`). The schema
(`chats`/`messages` tables, versioned via SQLite's `PRAGMA user_version`) is
created automatically the first time it's needed — there's nothing to run
by hand. You never need to open this file directly; use `/chats`, `/open`,
`/rename`, `/clear`, and `/delete` to manage chats through the app.

**Resetting local data:** to start over with a clean slate, quit Study Bot
and delete the database file:

```bash
rm ~/Library/Application Support/StudyBot/studybot.db
```

This only removes chats — do it only if you actually want to lose your
local chat history.

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
and inference runs entirely against your local Ollama server. Chat history
lives only in your local SQLite database. Application logs record message
*counts*, provider/model names, database *paths* (never contents), and
structural error details for debugging — never the actual content of
prompts, model responses, or chat titles. This matters more with each
stage: eventually Study Bot will read your course materials, screenshots,
and other personal files, so privacy-safe logging is the default from the
start, not an afterthought.

## Architecture

```
Interface (CLI today; desktop UI / macOS assistant later)
        ↓
StudyBotApp (src/studybot/app.py) — wires config, logging, model, repository
        ↓
SessionService (src/studybot/core/session_service.py)
        ↓                                   ↓
ChatService (history, streaming)     ChatRepository (persistence)
        ↓                                   ↓
ModelProvider (Mock / Ollama)        SQLiteChatRepository
```

Model inference and persistence are separate concerns that meet only in
`SessionService`: it calls `ChatService` for a response and, independently,
mirrors whatever new messages appear in `ChatService.history` into the
`ChatRepository`. Neither `ChatService`/`ModelProvider` knows persistence
exists, and neither `ChatRepository`/`SQLiteChatRepository` knows Ollama
exists.

Key modules:

- `src/studybot/__main__.py` — `python -m studybot` entry point
- `src/studybot/cli.py` — interactive terminal shell; no core logic, no raw
  SQL, no Ollama-specific code — only `StudyBotApp`/`SessionService`
- `src/studybot/app.py` — builds settings, logging, the model, the SQLite
  repository, and `SessionService` for a run of the app; closes the
  database connection on shutdown
- `src/studybot/config/settings.py` — typed, validated configuration,
  including `database_path` (derived from `data_dir`)
- `src/studybot/core/messages.py` — typed `Message`/`Role`
  (`system`/`user`/`assistant`)
- `src/studybot/core/prompts.py` — the shared baseline system prompt
- `src/studybot/core/titles.py` — deterministic, local chat-title
  generation from a chat's first message (no LLM call)
- `src/studybot/core/chat.py` — `ChatService`: in-memory history for the
  active chat, `send`/`send_streaming`, `clear`, `get_status`; can be
  seeded with restored history via its `history=` constructor argument
- `src/studybot/core/session_service.py` — `SessionService`: owns the
  active chat, creates/lists/opens/renames/deletes chats, and persists
  new messages after each successful `ChatService` call by diffing its
  history before/after — `ChatService` itself never learns persistence
  exists
- `src/studybot/core/exceptions.py` — `StudyBotError` and subclasses,
  including `SessionError` for chat-navigation problems (not found,
  ambiguous id prefix, empty title, ...)
- `src/studybot/models/` — unchanged from Stage 2 (`ModelProvider`,
  `MockModel`, `OllamaModel`, the provider factory)
- `src/studybot/storage/base.py` — `ChatRepository` protocol and the
  `ChatSession` domain type; nothing outside `storage/` sees a raw SQLite
  row
- `src/studybot/storage/sqlite_repository.py` — the **only** module
  allowed to contain SQL; `SQLiteChatRepository` implements the schema,
  its `PRAGMA user_version`-based version (currently `1`), and CRUD for
  chats/messages using parameterized queries only
- `src/studybot/logging_config.py` — console logging setup; quiet by
  default, verbosity controlled via `STUDYBOT_LOG_LEVEL`

A future backend — a different local model, hybrid routing, an encrypted
store, sync — can replace `OllamaModel` or `SQLiteChatRepository`
independently, without touching `SessionService`, the CLI, or a future GUI.
Choosing `mock` still runs with no Ollama installed, exactly as in Stage 2.

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
the CLI, not written into chat history.

## Next planned stage

Stage 4+ will add course-specific study spaces, persistent long-term
memory, RAG over PDFs/notes/slides, embeddings, image/screenshot
understanding, mastery tracking, quizzes, and eventually device/tool
access — none of which exists yet.
