# StudyBot

A local-first personal study assistant. It runs a local model through
[Ollama](https://ollama.com), organizes work into courses and chats, and offers
five teaching modes (Teach, Homework, Quick Answer, Practice, Exam) and two
reasoning modes (Fast, Deep Think). It has a terminal interface and a
Flutter desktop app, both built on the same Python engine. Nothing leaves your
machine.

The product name is provisional; the Python package is `studybot`.

## Features

- **Courses and chats.** Courses are an organizational label with an optional
  code, term and description (full Unicode). A chat belongs to one course or to
  none ("General"). Course membership never merges chat history.
- **Teaching modes**, set per chat: **Teach** (step-by-step tutoring),
  **Homework** (guided help, full solution on request), **Quick Answer**
  (direct and concise), **Practice** (one question at a time, with feedback),
  **Exam** (no hints until you answer). New chats start in Teach mode.
- **Reasoning modes**, set per chat and independent of teaching mode: **Fast**
  (default) and **Deep Think**. Hidden model reasoning is never shown or stored.
- **Learning memory.** Durable, course-scoped facts ("needs review: vector
  components") you keep deliberately, separate from chat history, and fed back
  to the model as soft context.
- **Streaming replies.** A completed stream is stored as one assistant message;
  a failed or abandoned one stores none.
- **Local API.** An authenticated HTTP and WebSocket server bound to
  `127.0.0.1`, documented in [API_CONTRACT.md](API_CONTRACT.md).
- **Swappable model backend.** `ModelProvider` hides the backend; Ollama and a
  deterministic mock are included. See [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md).
- **Privacy-safe logging.** Prompts, replies, titles and course names are never
  logged.

Not implemented: cloud providers, mastery tracking or scoring, a formal exam
engine, RAG over documents, embeddings, OCR, vision, tool use, cloud sync and
accounts. The API is a local bridge for one desktop app, not a network service.

## Requirements

- macOS
- Python 3.12 or newer
- [Ollama](https://ollama.com), only for real model responses (the `mock`
  provider needs nothing)
- Flutter, only for the desktop app

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

To use a real model:

```bash
brew install ollama      # or download from https://ollama.com
ollama serve             # or open the Ollama app
ollama pull qwen3:4b     # the default model, about 2.5 GB
```

StudyBot never downloads models for you; if the configured model is missing it
prints the exact `ollama pull` command to run.

## Usage

### Terminal

```bash
python -m studybot          # or: studybot
```

The default provider is `mock`. For a real model:

```bash
STUDYBOT_MODEL_PROVIDER=ollama python -m studybot
```

```
Study Bot
Local study assistant

Provider: Ollama
Model: qwen3:4b
Course: University Physics I
Chat: Vectors homework
Mode: Homework
Reasoning: Fast

Type /help for commands.
You > A car starts from rest and accelerates at 3 m/s^2 for 4 seconds. Help me solve it.
Bot > Let's identify what we know first: initial velocity is 0...
You > /quit
Goodbye.
```

With no chats yet, `Chat: Untitled`, `Course: General` and `Mode: Teach` are
shown, and nothing is written to the database until you send a message.

| Command | Description |
|---|---|
| `/help` | List commands |
| `/history` | Show the active chat's history |
| `/status` | Show provider and model availability |
| `/new` | New chat in the active course (always Teach mode) |
| `/chats` | List chats in the active course, or General |
| `/chats all` | List every chat |
| `/open <id>` | Switch to a chat by id or unique id prefix |
| `/rename <title>` | Rename the active chat |
| `/clear` | Remove the active chat's messages (asks to confirm; keeps the chat) |
| `/delete` | Delete the active chat (asks to confirm) |
| `/mode [name]` | Show or change the teaching mode |
| `/reasoning [name]` | Show or change the reasoning mode (`fast` or `deep`) |
| `/course new` | Create a course (interactive) and activate it |
| `/course list` | List courses (`*` marks the active one) |
| `/course open <id>` | Activate a course by id or unique id prefix |
| `/course info` | Show the active course and its chat count |
| `/course edit` | Edit the active course (blank keeps a value, `-` clears an optional one) |
| `/course delete` | Delete the active course (asks to confirm; its chats are kept) |
| `/course leave` | Back to General |
| `/chat course <id>` | Move the active chat into a course |
| `/chat course none` | Move the active chat to General |
| `/quit` | Exit |

`Ctrl+C` and `Ctrl+D` exit cleanly. Inside an interactive prompt or a `[y/N]`
confirmation they cancel that one action instead. Deleting a course never
deletes its chats; they become General.

### API server

```bash
python -m studybot.api      # or: studybot-server
```

It prints one JSON line with the port and bearer token to use:

```json
{"event": "studybot_api_ready", "host": "127.0.0.1", "port": 8765, "token": "..."}
```

```bash
curl http://127.0.0.1:8765/api/v1/health -H "Authorization: Bearer <token>"
```

The server and the CLI can run at the same time against the same database. See
[API_CONTRACT.md](API_CONTRACT.md) for endpoints, the WebSocket protocol and
error codes.

### Flutter app

```bash
cd frontend/studybot_app
flutter pub get
flutter run -d macos
```

A debug run starts the engine itself from this repository's `.venv` and
connects automatically; closing the app stops it. This needs the macOS App
Sandbox disabled for Debug/Profile builds (Release stays sandboxed). To use a
hand-started API server instead, pass `--dart-define=STUDYBOT_AUTOSTART=false`
and enter its URL and token on first launch. See
[frontend/studybot_app/README.md](frontend/studybot_app/README.md).

## Teaching modes

| Mode | `/mode` name | Behavior |
|---|---|---|
| Teach | `teach` | Tutors: explains clearly, adapts depth, breaks ideas into steps, corrects misconceptions. Default. |
| Homework | `homework` (`hw`) | Guides you through your own problem, but gives the full solution immediately if you ask for it. |
| Quick Answer | `quick` (`qa`) | Answers directly and concisely, with only the essential reasoning. |
| Practice | `practice` | Asks one question at a time, waits for your answer, evaluates it and adjusts difficulty. |
| Exam | `exam` | Asks a question with no hints and gives no feedback until you answer. |

A mode belongs to the chat, not the course or the app. Changing it applies from
the next message, never touches messages, title or course, and is never recorded
as a message. Modes are prompt-based guidance (`core/mode_prompts.py`), not a
scoring or assessment engine.

## Reasoning modes

Reasoning mode controls inference-time "thinking" and is independent of teaching
mode.

| Mode | `/reasoning` name | Behavior |
|---|---|---|
| Fast | `fast` | Answers without extended reasoning, if the model allows reasoning to be turned off. Default. |
| Deep Think | `deep` | Reasons through the problem first; slower, for harder questions. |

**With the default `qwen3:4b`, Fast and Deep behave the same.** That tag is a
thinking-only model: it always reasons, and asking it not to only stops Ollama
from separating the reasoning from the answer. StudyBot reads the model's
capabilities from Ollama and always requests separated reasoning from such a
model, so Fast gives a real speed-up only with a model whose thinking can be
switched off. See [API_CONTRACT.md](API_CONTRACT.md#reasoning-modes) for the
mapping.

Whatever the mode, reasoning is never displayed or stored. Every reply passes
one filter at the model-provider boundary that removes a leading
`<think>...</think>` span, and **fails closed**: if reasoning cannot be
separated from the answer with confidence, the reply is discarded with an error
and only your message is saved. Tags inside code blocks are left alone.

Replies saved by an older version may still contain leaked reasoning. They are
kept out of new model requests automatically without being modified. To see
which chats are affected (read-only; prints ids and counts, never content):

```bash
python3 scripts/audit_reasoning_contamination.py
```

Rewriting the stored text is optional. Stop `studybot-server` first; a full
backup is written before anything changes, and ambiguous replies are never
touched:

```bash
python3 scripts/audit_reasoning_contamination.py --apply --backup-dir ~/studybot-backups --yes
# undo:
python3 scripts/audit_reasoning_contamination.py --rollback ~/studybot-backups/<name>.manifest.json --yes
```

## Learning memory

Chat history answers "what was said?"; learning memory answers "what should
StudyBot remember about how I'm learning?" It is a small set of facts you
record deliberately. Clearing or deleting a chat never deletes the memories it
produced. It is not a mastery or scoring system: there are no percentages or
weights.

Each memory has one of five kinds:

| Kind | Shown as | Meaning |
|---|---|---|
| `understands` | Understands | You have shown you understand this. |
| `needs_review` | Needs review | Revisit this before moving on. |
| `misconception` | Misconception | A recurring mistaken belief worth correcting. |
| `learning_goal` | Goal | Something you want to work toward. |
| `useful_strategy` | Helpful approach | An explanation or strategy that worked. |

- **Course-scoped by default.** A course's memories never appear in another
  course's chats. A memory can be global (`courseId: null`), which is the
  exception.
- **Provenance only.** A memory may record the chat it came from. If that chat
  is deleted the memory is unaffected.
- **Archive, don't delete.** Archived memories stay visible and can be restored;
  a separate hard delete exists.
- **Course deletion archives memories.** Deleting a course archives its active
  memories in the same SQLite transaction. Otherwise they would turn into global
  memories and leak into every other course. Restoring one makes it global;
  reassigning it to another course is a separate choice.
- **Duplicates and conflicts.** Topics are compared case-insensitively with
  whitespace collapsed. An exact duplicate (same topic and kind) is rejected;
  creating `understands` for a topic archives an active `needs_review` or
  `misconception` memory for it, and vice versa.
- **User controlled.** Memories are created, edited, archived, restored and
  deleted from the Flutter app (Study Panel and management view). Nothing is
  created automatically: no extra model call extracts memories from replies.
- **Used as a soft hint.** Each request includes a compact, size-limited block
  (at most 12 entries, about 1200 characters, newest first) of the chat's
  course memories plus global ones. The model is told to treat it as possibly
  outdated, never to treat it as proof of understanding, never to mention it,
  and to follow the current question and teaching mode when they conflict.
  It is prompt guidance only; replies are not post-processed.

## Configuration

Configuration is validated in `studybot.config.settings.Settings` and read from
environment variables. All are optional.

| Variable | Default | Purpose |
|---|---|---|
| `STUDYBOT_ENV` | `development` | Environment name |
| `STUDYBOT_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `STUDYBOT_MODEL_PROVIDER` | `mock` | `mock` or `ollama` |
| `STUDYBOT_DATA_DIR` | `~/Library/Application Support/StudyBot` | Where the database lives |
| `STUDYBOT_SYSTEM_PROMPT` | see `core/prompts.py` | Override the baseline system prompt |
| `STUDYBOT_OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `STUDYBOT_OLLAMA_MODEL` | `qwen3:4b` | Ollama model tag |
| `STUDYBOT_OLLAMA_TIMEOUT` | `120` | HTTP timeout in seconds |
| `STUDYBOT_OLLAMA_KEEP_ALIVE` | Ollama's default | How long Ollama keeps the model loaded |
| `STUDYBOT_FAST_MAX_GENERATED_TOKENS` | `4096` | Token cap for a Fast reply (hidden reasoning counts) |
| `STUDYBOT_DEEP_MAX_GENERATED_TOKENS` | `6144` | Token cap for a Deep reply |
| `STUDYBOT_FAST_GENERATION_DEADLINE_SECONDS` | `120` | Total time limit for a Fast reply |
| `STUDYBOT_DEEP_GENERATION_DEADLINE_SECONDS` | `300` | Total time limit for a Deep reply |

```bash
STUDYBOT_LOG_LEVEL=DEBUG python -m studybot
STUDYBOT_MODEL_PROVIDER=ollama STUDYBOT_OLLAMA_MODEL=qwen3:8b python -m studybot
```

Invalid values (for example a negative token cap or `nan`) stop startup instead
of being silently corrected.

### Choosing a model

The model is just a tag, so any model already pulled into Ollama works with no
code changes. What a model supports (vision, tools, thinking, whether Fast and
Deep differ, advertised context length) is discovered at runtime from Ollama's
`/api/show` rather than guessed from its name. A model may report vision or tool
support that StudyBot does not use yet: messages are text-only and there is no
tool loop.

`qwen3:4b` is the default. It was benchmarked on an 8 GB M3 Mac against
`qwen3.5:4b` and `gemma3:4b` using identical prompts through the full stack, and
neither beat it: `qwen3.5:4b` sometimes spent its whole context reasoning in
Deep mode and revealed answers in Practice; `gemma3:4b` revealed Practice
answers and marked wrong answers correct.

To compare models yourself (a development tool that uses a throwaway database per
model, refuses to touch your real data, and prints answers only with
`--show-answers`):

```bash
python scripts/benchmark_local_models.py --models qwen3:4b qwen3.5:4b --output results.json
python scripts/benchmark_local_models.py --score-from results.json --grades grades.json
```

Saved results contain scenario ids, timings, lengths and capability values,
never prompts or answers.

### Generation limits

Every reply is bounded by a token cap and a total time limit, each larger for
Deep than for Fast, so one runaway generation cannot occupy the engine
indefinitely. A reply that hits either limit is discarded, you see an error, only
your message is kept, and the chat is usable again immediately.

These are safety limits, not quality settings. Reasoning models count hidden
reasoning toward the token cap, so a long multi-step problem can exhaust the
defaults; if you see token-limit errors, raising the relevant cap is the fix.
The time limit is checked whenever the model produces output; if the model
server stops responding entirely, `STUDYBOT_OLLAMA_TIMEOUT` applies.

On an 8 GB machine, be careful raising Ollama's context length (`num_ctx` or
`OLLAMA_CONTEXT_LENGTH`). A model's advertised context (often 128K or more) is
not what Ollama uses (check `ollama ps`), and a longer one costs memory.

## Data

Everything is stored in one SQLite database at
`$STUDYBOT_DATA_DIR/studybot.db`, by default
`~/Library/Application Support/StudyBot/studybot.db`. The schema is created and
upgraded automatically on open. Each upgrade step is one all-or-nothing
transaction, so a failed upgrade leaves your database as it was, and existing
chats keep their ids, titles, timestamps, courses and messages.

| Version | Change |
|---|---|
| v1 to v2 | Adds `courses` and a nullable `chats.course_id` (`ON DELETE SET NULL`). |
| v2 to v3 | Adds `chats.teaching_mode` (default `teach`). |
| v3 to v4 | Adds `chats.reasoning_mode` (default `fast`). |
| v4 to v5 | Adds `learning_memories` (`course_id` and `source_chat_id` both `ON DELETE SET NULL`). |

A fresh database is created directly at the current version (v5).

```bash
# Reset (quit StudyBot first). This deletes all chats, courses and memories:
rm ~/Library/Application\ Support/StudyBot/studybot.db

# Inspect read-only:
sqlite3 -readonly "$HOME/Library/Application Support/StudyBot/studybot.db" \
  "SELECT id, name FROM courses; SELECT COUNT(*) FROM chats;"

# Back up (with StudyBot not running):
db="$HOME/Library/Application Support/StudyBot/studybot.db"
cp "$db" "$db.bak-$(date +%Y%m%d-%H%M%S)"
```

### Verifying against a real model

A script that starts a real `studybot-server` must use a disposable database,
never your real one. `STUDYBOT_DATA_DIR` is the only variable that selects the
database; an unrecognized one such as `STUDYBOT_DB_PATH` is silently ignored and
falls back to your real data. Use this pattern:

```bash
export STUDYBOT_DATA_DIR="$(mktemp -d -t studybot_verify)"
python3 scripts/check_verification_env.py || exit 1   # refuses the real default directory
STUDYBOT_MODEL_PROVIDER=ollama studybot-server &
```

`scripts/check_verification_env.py` exits 0 and prints the resolved path when it
is safe, and exits 1 if the directory is, contains or is contained by the real
default (including when `STUDYBOT_DATA_DIR` is unset). In-process scripts can
call `studybot.config.verification_guard.assert_safe_for_verification(settings)`.
The guard only refuses; nothing in the codebase deletes or modifies the real
database.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

Tests are deterministic and need no Ollama, network or real data: the Ollama
client boundary is faked (`tests/fake_ollama.py`), every persistence test uses
its own database under pytest's `tmp_path`, and API tests use FastAPI's
in-process `TestClient`. For the Flutter app run `flutter analyze` and
`flutter test` in `frontend/studybot_app`.

## Troubleshooting

**"Could not connect to the local Ollama service."** Ollama is not running. Start
it with `ollama serve` (or open the app) and check that `STUDYBOT_OLLAMA_HOST`
matches. `/status` in the CLI shows the current state.

**"Model 'x' is not available locally. Run: ollama pull x"** The configured model
is not downloaded. Run the suggested command.

**`ModuleNotFoundError: No module named 'studybot'`** after installing. This can
happen when the project lives in an iCloud-synced folder such as `~/Desktop`,
which may intermittently evict files in `.venv`. Export `PYTHONPATH="$PWD/src"`
for the session, exclude `.venv` from sync, or move the project out of the
synced folder.

## Privacy

There is no analytics, telemetry, cloud logging, backup or error reporting, and
inference runs against your local Ollama server. Chats, courses, modes and
memories live only in your local database. Logs record counts, provider and model
names, database paths and structural error details, never prompts, replies,
titles, course names or memory text. Course and mode context is sent only to the
configured model provider, which under the default setup runs on your machine.

The API server binds to `127.0.0.1`, never logs request bodies or the token, and
disables per-request access logging. See [API_CONTRACT.md](API_CONTRACT.md#privacy).

## Architecture

```
CLI (python -m studybot)     Flutter app ──► studybot.api (FastAPI: HTTP + WebSocket)
          │                                          │
          └──────────────► StudyBotApp ◄─────────────┘
                              ├── SessionService ──► ChatService ──► ModelProvider (Ollama | Mock)
                              ├── CourseService
                              └── LearningMemoryService
                                        │
                  SQLite repositories (chats, courses, learning memories)
                  sharing one connection
```

The CLI and the API are equally thin: they translate their transport (terminal
I/O, HTTP/WebSocket JSON) into calls on the services and back, and contain no
course, chat or mode logic. Nothing in `core/`, `models/` or `storage/` imports
or knows about either interface.

Inference, persistence, courses, teaching mode and memory are separate concerns.
`SessionService` asks `ChatService` for a reply and mirrors whatever new messages
appear in `ChatService.history` into the repository, so neither `ChatService`
nor `ModelProvider` knows about persistence, courses or modes. Teaching mode is a
plain field on the chat, fed into the same prompt-composition function as the
course and memory context. A different model, an encrypted store or another UI
can replace one piece without touching the others.

| Module | Responsibility |
|---|---|
| `studybot/app.py` | Composition root: settings, logging, model, shared connection, repositories and services |
| `studybot/cli.py` | Terminal shell; no core logic, no SQL, nothing Ollama-specific |
| `studybot/config/` | Typed, validated `Settings`; `verification_guard` for safe real-model testing |
| `studybot/core/session_service.py` | Chat orchestration: an active-chat layer for the CLI and an explicit by-id layer for the API, with a per-chat lock against concurrent generations |
| `studybot/core/chat.py` | `ChatService`: in-memory history, `send`/`send_streaming`, restored-history sanitizing |
| `studybot/core/course_service.py` | Course validation and CRUD; archives memories when deleting a course |
| `studybot/core/memory_service.py` | Learning-memory validation, conflict policy, CRUD and the prompt context block |
| `studybot/core/context.py` | Builds the system prompt from baseline, course, memory and mode sections |
| `studybot/core/teaching_mode.py`, `mode_prompts.py` | Teaching-mode enum and catalog; per-mode instruction text |
| `studybot/core/reasoning_mode.py` | Reasoning-mode enum and catalog |
| `studybot/core/output_integrity.py` | The reasoning filter and stored-reply classifier |
| `studybot/models/` | `ModelProvider` interface, `MockModel`, `OllamaModel` (the only module that knows Ollama), generation budgets, factory |
| `studybot/storage/` | Repository protocols and domain types, SQLite repositories, schema migrations via `PRAGMA user_version`, and the reasoning audit; all SQL lives in this package |
| `studybot/api/` | FastAPI app: routes, auth, schemas, WebSocket, and the single worker thread that owns the SQLite connection |

### Streaming and persistence

`ModelProvider.stream()` yields content incrementally and `ChatService` adds one
complete assistant message to history only when the stream finishes
successfully. `SessionService` persists by comparing history before and after a
call, so a successful exchange stores one user row and one assistant row, and a
failed or abandoned one stores only the user row. Nothing is written per token.
A failed model call leaves your message in the database so you can retry; no
synthetic error message is ever inserted into a chat, and mode changes never
appear in history either.

## Roadmap

Not yet implemented: numeric mastery or scoring, automatic memory extraction, a
knowledge graph, spaced repetition, quizzes and a study planner, RAG over PDFs,
notes and slides, embeddings, image understanding, calendar or LMS integration,
cloud sync, accounts, and device or tool access.
