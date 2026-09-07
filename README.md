# Study Bot (v0.1, Stage 2 — Real Local LLM Integration)

A local-first personal study assistant. **Stage 2** connects a real, fully
local LLM (via [Ollama](https://ollama.com)) behind the same provider
abstraction Stage 1 established, while keeping a mock backend available for
offline development and tests.

The product name is provisional; the internal Python package is `studybot`.

## What this is (and isn't) right now

- ✅ A working interactive CLI chat shell with streaming responses
- ✅ A real local model backend (Ollama), swappable behind a
  `ModelProvider` interface that knows nothing about Ollama specifically
- ✅ A deterministic `MockModel` for offline development/tests — still
  available via configuration, requires no server
- ✅ Application-owned, in-memory multi-turn conversation history sent in
  full on every request (no reliance on hidden server-side session state)
- ✅ A minimal, centrally-defined system prompt shared by every backend
- ✅ `/status`: on-demand provider/server/model health check
- ✅ Centralized configuration and privacy-safe logging (prompts/responses
  are never written to logs)
- ❌ No cloud AI provider (OpenAI, Anthropic, etc.) — local-only
- ❌ No persistence — conversations are not saved to disk
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

Example session (Ollama mode):

```
Study Bot
Local study assistant

Provider: Ollama
Model: qwen3:4b

Type /help for commands.
You > What's the difference between speed and velocity?
Bot > Speed is how fast something moves; velocity is speed with a direction...
You > /quit
Goodbye.
```

Supported commands:

| Command    | Description                                          |
|------------|-------------------------------------------------------|
| `/help`    | List available commands                                |
| `/history` | Show the current conversation                           |
| `/status`  | Show provider/server connection and model availability |
| `/clear`   | Clear the conversation history                          |
| `/quit`    | Exit                                                     |

`Ctrl+C` and `Ctrl+D` (EOF) both exit cleanly with no stack trace.

## Configuration

Configuration is centralized in `studybot.config.settings.Settings` and read
from environment variables (all optional, sensible defaults apply):

| Variable                     | Default                                    | Purpose                                   |
|-------------------------------|---------------------------------------------|--------------------------------------------|
| `STUDYBOT_ENV`                 | `development`                               | Environment name                          |
| `STUDYBOT_LOG_LEVEL`           | `INFO`                                       | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `STUDYBOT_MODEL_PROVIDER`      | `mock`                                       | `mock` or `ollama`                        |
| `STUDYBOT_DATA_DIR`            | `~/Library/Application Support/StudyBot`     | Future app data directory (chats, memory, indexes, logs) — not written to yet |
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

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

All tests are deterministic and server-independent: they fake the `ollama`
client boundary (`tests/fake_ollama.py`) rather than requiring a running
Ollama server or a downloaded model, and they build `Settings` explicitly
(with an in-memory environment mapping and/or `tmp_path`) rather than
touching the real macOS application-support directory or `~`.

## Troubleshooting

**"Could not connect to the local Ollama service."** — Ollama isn't
running. Start it with `ollama serve` (or open the Ollama app), then check
`STUDYBOT_OLLAMA_HOST` matches where it's listening (default
`http://localhost:11434`). Run `/status` in the chat to confirm.

**"Model 'x' is not available locally. Run: ollama pull x"** — the
configured model hasn't been downloaded. Run the suggested `ollama pull`
command yourself; Study Bot deliberately never downloads models
automatically.

## Privacy

This is a local-first project. There is no analytics, telemetry, cloud
logging, or remote error reporting anywhere in the codebase, and inference
runs entirely against your local Ollama server. Application logs record
message *counts*, provider/model names, and structural error details for
debugging — never the actual content of prompts or model responses. This
matters more with each stage: eventually Study Bot will read your course
materials, screenshots, and other personal files, so privacy-safe logging
is the default from the start, not an afterthought.

## Architecture

```
Interface (CLI today; desktop UI / macOS assistant later)
        ↓
StudyBotApp (src/studybot/app.py)  — wires config, logging, chat service
        ↓
ChatService (src/studybot/core/chat.py) — history, streaming, status
        ↓
ModelProvider (src/studybot/models/base.py) — backend-agnostic interface
        ↓                                  ↓
MockModel (src/studybot/models/mock.py)   OllamaModel (src/studybot/models/ollama.py)
                                            ↓
                                           Ollama local server → configured LLM
```

Key modules:

- `src/studybot/__main__.py` — `python -m studybot` entry point
- `src/studybot/cli.py` — interactive terminal shell; contains no core logic
  and imports nothing Ollama-specific — only `ChatService`/`StudyBotApp`
- `src/studybot/app.py` — builds settings, logging, and the chat service for
  a run of the app; the thing every interface talks to
- `src/studybot/config/settings.py` — typed, validated configuration
  (mock and Ollama settings alike) with environment-variable overrides
- `src/studybot/core/messages.py` — typed `Message`/`Role` representation
  (`system`/`user`/`assistant`)
- `src/studybot/core/prompts.py` — the shared baseline system prompt, kept
  out of any provider so every backend gets the same behavior
- `src/studybot/core/chat.py` — `ChatService`: session history, `send`
  (complete response) and `send_streaming` (incremental), `clear`,
  `get_status`
- `src/studybot/core/exceptions.py` — `StudyBotError` and subclasses for
  expected, user-facing failures (e.g. `ModelError` for a down/misconfigured
  backend)
- `src/studybot/models/base.py` — `ModelProvider` protocol
  (`generate`/`stream`/`get_status`), `ModelResponse`, `ProviderStatus`
- `src/studybot/models/mock.py` — deterministic echo model
- `src/studybot/models/ollama.py` — the **only** module allowed to import
  `ollama`/`httpx` or know about Ollama's request/response shapes; converts
  typed `Message`s to/from Ollama's format and translates connection/model
  errors into `ModelError`
- `src/studybot/models/factory.py` — maps `model_provider` from config to a
  concrete `ModelProvider` (`mock` → `MockModel`, `ollama` → `OllamaModel`)
- `src/studybot/logging_config.py` — console logging setup; quiet by
  default, verbosity controlled via `STUDYBOT_LOG_LEVEL`

The CLI only ever talks to `ChatService`, which only ever talks to the
`ModelProvider` protocol — neither imports anything Ollama-specific. This is
what lets a future backend (a different local model, hybrid routing, etc.)
replace `OllamaModel` without touching `ChatService`, the CLI, or a future
GUI at all, and it's why choosing `mock` still runs with no Ollama installed.

### Streaming design

`ModelProvider.stream()` yields response content incrementally;
`ChatService.send_streaming()` consumes it, prints/forwards each chunk to
the caller, and accumulates the full text itself. **History is only updated
once, after the stream completes successfully** — never with partial
content. If the underlying model fails partway through (or the caller stops
consuming the generator early), no assistant message is recorded at all;
the user's message stays in history but the reply does not, so a failed or
abandoned generation can never be mistaken for a complete answer. The
non-streaming `send()`/`generate()` path is preserved unchanged alongside
streaming for tests and any future caller that just wants a complete
response.

### Reasoning/thinking output

Some models return a separate `thinking` field distinct from their answer
`content`. `OllamaModel` only ever reads `content` — thinking traces are
never surfaced in the chat UI, and there is no "show reasoning" feature in
this stage.

## Next planned stage

Stage 3 and beyond will add course-specific study spaces, persistent
memory, RAG over PDFs/notes/slides, embeddings, image/screenshot
understanding, mastery tracking, quizzes, and eventually device/tool
access — none of which exists yet.
