# Study Bot (Foundation Build — v0.1, Stage 1)

A local-first personal study assistant. This is **Stage 1: Project
Foundation** — it establishes clean architecture (config, logging, a
model-provider abstraction, a chat service, a CLI) with **no real AI model
connected yet**.

The product name is provisional; the internal Python package is `studybot`.

## What this is (and isn't) right now

- ✅ A working interactive CLI chat shell
- ✅ A model-provider interface designed to support Ollama / local LLMs /
  cloud models / streaming later, without changing the rest of the app
- ✅ A deterministic `MockModel` that only echoes your input — it is **not**
  intelligent
- ✅ In-memory conversation history for a single session
- ✅ Centralized configuration and privacy-safe logging
- ❌ No real LLM is connected (no Ollama, no OpenAI, no local model weights)
- ❌ No persistence — conversations are not saved to disk
- ❌ No RAG, embeddings, PDFs, OCR, screenshots, courses, quizzes, or agent
  behavior — all of that is later work

## Prerequisites

- macOS
- Python 3.12 or newer

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the chatbot

```bash
python -m studybot
```

or, if installed as a script (via the venv above):

```bash
studybot
```

Example session:

```
Study Bot
Local study assistant — Foundation Build

Type /help for commands.
You > hello
Bot > [Mock] You said: hello
You > /quit
Goodbye.
```

Supported commands:

| Command    | Description                        |
|------------|-------------------------------------|
| `/help`    | List available commands             |
| `/history` | Show the current conversation       |
| `/clear`   | Clear the conversation history      |
| `/quit`    | Exit                                 |

`Ctrl+C` and `Ctrl+D` (EOF) both exit cleanly with no stack trace.

## Configuration

Configuration is centralized in `studybot.config.settings.Settings` and read
from environment variables (all optional, sensible defaults apply):

| Variable                  | Default        | Purpose                                   |
|---------------------------|----------------|--------------------------------------------|
| `STUDYBOT_ENV`             | `development`  | Environment name                          |
| `STUDYBOT_LOG_LEVEL`       | `INFO`         | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `STUDYBOT_MODEL_PROVIDER`  | `mock`         | Which model backend to use (only `mock` exists in Stage 1) |
| `STUDYBOT_DATA_DIR`        | `~/Library/Application Support/StudyBot` | Future app data directory (chats, memory, indexes, logs) — not written to yet |

Example:

```bash
STUDYBOT_LOG_LEVEL=DEBUG python -m studybot
```

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

Tests never write to the real macOS application-support directory — they
construct `Settings` explicitly (with an in-memory environment mapping and/or
`tmp_path`) rather than relying on the OS default.

## Architecture

```
Interface (CLI today; desktop UI / macOS assistant later)
        ↓
StudyBotApp (src/studybot/app.py)  — wires config, logging, chat service
        ↓
ChatService (src/studybot/core/chat.py) — conversation history, message flow
        ↓
ModelProvider (src/studybot/models/base.py) — backend-agnostic interface
        ↓
MockModel (src/studybot/models/mock.py) — Stage 1's only backend
```

Key modules:

- `src/studybot/__main__.py` — `python -m studybot` entry point
- `src/studybot/cli.py` — interactive terminal shell; contains no core logic,
  only input/output and command dispatch
- `src/studybot/app.py` — builds settings, logging, and the chat service for
  a run of the app; the thing every interface talks to
- `src/studybot/config/settings.py` — typed, validated configuration with
  environment-variable overrides
- `src/studybot/core/messages.py` — typed `Message`/`Role` representation
  (`system`/`user`/`assistant`)
- `src/studybot/core/chat.py` — `ChatService`: session history, sending
  messages, clearing history
- `src/studybot/core/exceptions.py` — `StudyBotError` and subclasses for
  expected, user-facing failures
- `src/studybot/models/base.py` — `ModelProvider` protocol and
  `ModelResponse`; the seam future backends plug into
- `src/studybot/models/mock.py` — deterministic echo model for Stage 1
- `src/studybot/models/factory.py` — maps a provider name from config to a
  concrete `ModelProvider`
- `src/studybot/logging_config.py` — console logging setup; quiet by
  default, verbosity controlled via `STUDYBOT_LOG_LEVEL`

The CLI never talks to `MockModel` or any concrete backend directly — it only
sees `ChatService`, which only sees the `ModelProvider` protocol. This is
what lets later stages swap in Ollama, other local LLMs, or hybrid routing
without touching the CLI (or a future desktop UI) at all.

## Next planned stage

**Stage 2** will connect a real local model backend (e.g. Ollama) behind the
existing `ModelProvider` interface. Everything else in this document's
"isn't" list remains for stages after that.
