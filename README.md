# Study Bot (v0.2, Stage 6.5 — Bounded Inference)

A local-first personal study assistant. **Stage 5.5** added a local HTTP +
WebSocket API (`python -m studybot.api`) in front of the same engine the
CLI uses; **Stage 5.6** added the first real product UI on top of it — a
Flutter desktop/mobile app at [`frontend/studybot_app/`](frontend/studybot_app/)
(primary target macOS) that drives Study Bot entirely through that API,
knowing nothing about SQLite, Ollama, or Python internals. **Stage 5.7**
added an explicit, per-chat **reasoning mode** (Fast/Deep Think) so the app
no longer leaves Qwen3's "thinking" behavior implicit. **Stage 5.8** removed
the API's last remaining coupling to a single mutable "active chat" per
process: every chat-specific HTTP/WebSocket operation addresses its
`chat_id` explicitly and is safe to interleave with operations on any other
chat, in any order. **Stage 6** added **learning memory** — durable,
course-scoped learning facts ("needs review: vector components",
"understands significant figures") that StudyBot retains independently of
raw chat history, are fully user-visible and user-controlled, and are
woven into future answers for the same course. **Stage 6.1** was a narrow
reliability pass on top of that: deleting a course started archiving its
memories instead of silently turning them into active global ones, and the
prompt guidance around using memory was refined after real-model testing
surfaced a subtler failure mode (treating a memory as authoritative proof
of current understanding, rather than a soft, overridable hint). **Stage
6.2** makes that course-deletion archiving genuinely atomic at the SQLite
transaction level (previously two sequential calls; now one real
`BEGIN`/`COMMIT`/`ROLLBACK`, verified with actual failure injection and a
second independent connection — see "Learning memory" below), and fixes a
real bug in this project's own verification tooling: several stages'
real-model verification scripts silently ran against the real default
database instead of a fresh one (see "Real-model verification scripts"
below). The CLI (`python -m studybot`) is unchanged and keeps working
exactly as before — these are two interfaces onto the same core, not a
replacement. See **[API_CONTRACT.md](API_CONTRACT.md)** for the full API
reference (endpoints, the WebSocket protocol, error codes, auth).

Teaching modes (Teach, Homework, Quick Answer, Practice, Exam — one active
per chat, prompt-based, added in Stage 5) and course organization (Stage 4)
are unchanged from before. **Reasoning mode is a separate, independent
per-chat setting** (Stage 5.7) — it controls the model's inference-time
"thinking" depth/latency, not instructional behavior; a chat can be in any
combination of the two.

The product name is provisional; the internal Python package is `studybot`.

## What this is (and isn't) right now

- ✅ A local HTTP + WebSocket API (`python -m studybot.api` /
  `studybot-server`) exposing the same `SessionService`/`CourseService`
  the CLI uses — courses, chats, teaching modes, and streaming chat, all
  under `/api/v1/...`. See [API_CONTRACT.md](API_CONTRACT.md).
- ✅ Binds to `127.0.0.1` only (not configurable) and requires a
  per-process `Authorization: Bearer <token>` on every request — never
  persisted, never logged, generated fresh each time the server starts
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
- ✅ A Flutter desktop/mobile app ([`frontend/studybot_app/`](frontend/studybot_app/)) —
  courses, chats, teaching-mode picker, reasoning-mode picker, and streaming
  conversation, adaptive from phone width up to a full four-pane desktop
  layout; see [frontend/studybot_app/README.md](frontend/studybot_app/README.md)
  for how to run it
- ✅ Two reasoning modes, one active per chat, independent of teaching mode:
  **Fast** (the default for every new chat) and **Deep Think** (for harder
  questions). Hidden model "thinking" is never shown in the UI and never
  persisted — only the final answer is (Stage 6.3 enforces this at the
  model-provider boundary for every mode; see "Reasoning modes").
- ❌ No Materials, Notes, Progress, RAG, mastery, or PDFs in the Flutter app
  — only what the API above actually exposes
- ❌ No remote/network exposure, cloud deployment, or user accounts — the
  API is a local bridge for one desktop app talking to its own engine
  process, nothing else

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

## Running the API server

For a future Flutter client (or any local tooling) instead of the terminal:

```bash
python -m studybot.api
# or, if installed as a script:
studybot-server
```

This prints one JSON line to stdout with the port and auth token to use:

```json
{"event": "studybot_api_ready", "host": "127.0.0.1", "port": 8765, "token": "..."}
```

Every request needs `Authorization: Bearer <token>` from that line. Full
reference: **[API_CONTRACT.md](API_CONTRACT.md)**. Quick example:

```bash
curl http://127.0.0.1:8765/api/v1/health -H "Authorization: Bearer <token>"
```

The CLI and the API server can run at the same time against the same
local database — try creating a course through one and listing it through
the other.

## Running the Flutter app

With the API server running (see above), and its printed port + token in
hand:

```bash
cd frontend/studybot_app
flutter pub get
flutter run -d macos   # or: flutter analyze / flutter test
```

On first launch, enter the base URL (default `http://127.0.0.1:8765`) and
the token printed by `studybot-server` into the connection screen — both
are remembered locally for next time. The app never bundles or auto-starts
the Python engine; start it yourself first. See
[frontend/studybot_app/README.md](frontend/studybot_app/README.md) and the
Flutter section of the architecture notes below for details.

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
| `/reasoning`         | Show the active chat's reasoning mode and all available modes |
| `/reasoning <name>`  | Change the active chat's reasoning mode (`fast` or `deep`)    |
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

### Reasoning modes

A second, **independent** per-chat setting (Stage 5.7) — controls how much
inference-time "thinking" Ollama/Qwen3 does before answering, not
instructional behavior (that's teaching mode, above). A chat can combine
any teaching mode with any reasoning mode.

| Mode | `/reasoning` name | What it does |
|------|-------------------|--------------|
| Fast | `fast` | Answers without extended reasoning, *if the model supports turning reasoning off*. **Default for every new chat.** |
| Deep Think | `deep` | Reasons through the problem before answering — slower, for harder questions. |

```
You > /reasoning
Reasoning mode: Fast

Available:
  fast       Answers without extended reasoning when the model supports it — faster.
  deep       Reasons through the problem before answering — slower, for harder questions.

You > /reasoning deep
Reasoning mode changed to Deep Think.
```

**With the default `qwen3:4b`, Fast and Deep behave the same.** That tag
is Qwen3-4B-Thinking-2507, a *thinking-only* model: it always reasons
before answering, and asking it not to (`think=False`) only stops Ollama
from separating the reasoning from the answer — which is exactly how
Stage 6.3's bug happened (the model's planning text streamed into the chat
as if it were the reply, ending in a stray `</think>`). StudyBot now reads
the model's capabilities from Ollama and always requests separated
reasoning from a thinking-only model; Fast only gives a real speed-up with
a *toggleable* model (a hybrid Qwen3 build), where it maps to
`think=False`. The earlier "~3.7s to first token in Fast" figure (Stage
5.7) was measuring the first token of *leaked reasoning*, not of the
answer, and is withdrawn. See
[API_CONTRACT.md](API_CONTRACT.md#reasoning-modes-stage-57) for the full
mapping.

Whichever mode is active, the model's reasoning is never shown in the UI
and never persisted — only the final answer is. Every reply passes one
filter at the model-provider boundary that strips a leading `<think>…
</think>` span without ever displaying it, and **fails closed** (the reply
is discarded with an error; only your message is saved) if reasoning
can't be separated from the answer with confidence. Legitimate mentions of
those tags inside code blocks are left alone.

**Replies saved before Stage 6.3** may still contain leaked reasoning.
StudyBot keeps confidently-identified reasoning in those old replies out
of every new model request without modifying them. To see which chats are
affected (read-only; prints ids and counts, never content):

```bash
python3 scripts/audit_reasoning_contamination.py
```

Rewriting the stored replies is optional and only happens if you ask for
it — stop `studybot-server` first; a full backup is written before
anything changes, and ambiguous replies are never touched:

```bash
python3 scripts/audit_reasoning_contamination.py --apply --backup-dir ~/studybot-backups --yes
# undo:
python3 scripts/audit_reasoning_contamination.py --rollback ~/studybot-backups/<name>.manifest.json --yes
```

### Learning memory

**A different system from chat history.** Chat history answers "what was
said?"; learning memory answers "what useful learning information should
StudyBot retain?" — a small, deliberately-recorded set of durable facts
("needs review: vector components", "understands significant figures",
"recurring misconception: confuses velocity and acceleration"), completely
independent of the conversation that produced them. Clearing or deleting a
chat never destroys a memory it produced. **This is not a mastery/scoring
engine** — there are no percentages, numeric weights, or aggregation
anywhere in Stage 6, by design; that's explicitly deferred (see "Next
planned stage").

**Five kinds, a strict closed set** (never arbitrary free text):

| Kind | Shown as | Meaning |
|------|----------|---------|
| `understands` | Understands | The student has shown they understand this. |
| `needs_review` | Needs review | The student should revisit this before moving on. |
| `misconception` | Misconception | A recurring mistaken belief worth gently correcting. |
| `learning_goal` | Goal | Something the student wants to work toward. |
| `useful_strategy` | Helpful approach | An explanation/strategy that worked well before. |

**Course-scoped by default.** A memory normally belongs to a course
(`courseId`) — Physics memories never appear in a Calculus chat, no matter
how similar the wording. A memory can also be global (`courseId: null`,
shown in every course), but that should be the exception, not the norm.

**Source-chat provenance, not a dependency.** A memory may record
`sourceChatId` — which chat produced it — purely for reference. The memory
remains fully valid, with all its own content intact, even after that chat
is cleared or deleted (`sourceChatId` just becomes `null`). Neither foreign
key ever cascades a delete into a memory — see `ON DELETE SET NULL` in the
schema below.

**Archive, don't delete.** Retiring a memory (e.g. the student no longer
needs review on a topic) archives it — it stays visible under "Archived"
and can be restored — rather than being erased. A separate, explicit hard
delete is available for when a memory should genuinely be gone.

**Deleting a course atomically archives its memories first (Stage 6.1,
made a real SQLite transaction in Stage 6.2).** The database's `ON DELETE
SET NULL` would, by itself, turn every active memory in a deleted course
into an active *global* memory the instant the course disappears —
silently injecting that subject's context into every other course from
then on. Instead, `SQLiteCourseRepository.delete_course_archiving_memories`
archives every active memory belonging to that course and deletes the
course as **one atomic transaction** (`BEGIN`/`COMMIT`/`ROLLBACK` around
both statements, on the shared connection) — either both happen or
neither does, verified by actually injecting a failure between the two
statements and confirming the archive rolls back too, that a retry
afterward succeeds cleanly, and that a second, fully independent
`sqlite3.Connection` to the same file never observes an in-between state.
`CourseService.delete_course` (used by both the API and the CLI's
`/course delete` — one implementation, so both stay consistent) is the
only caller. Memories that were already global, or belong to a different
course, are never touched. The archived memory keeps all its content and
is fully visible/editable via the usual archive-listing and edit
operations; recovering it into active use again is a **separate,
explicit** choice — restore it (it becomes global, since its course is
gone) or reassign its `courseId` to a different existing course first —
never automatic.

**Duplicate and conflict policy** (deliberately simple, no fuzzy/semantic
matching yet): within one course (or the global scope), topics are compared
case-insensitively with whitespace collapsed.
- The exact same active topic+kind already exists → rejected
  (`MEMORY_CONFLICT`); edit the existing memory instead.
- The same topic has an active memory in the **opposite** learning state
  (`understands` vs. `needs_review`/`misconception`) → the old one is
  **archived automatically** as the new one is created — learning changes,
  and Stage 6 models that as supersession, not indefinite coexistence.
  `learning_goal`/`useful_strategy` never trigger this (they're not claims
  about current understanding).

**User control first.** Every memory is visible and editable in the
Flutter app's Study Panel and a dedicated management view: create, edit,
archive, restore, delete. **Nothing is created automatically** — Stage 6
deliberately does not run a second model call after every chat response to
extract memories on its own (local inference is still comparatively
expensive and serialized; see "Known limitations" — automatic extraction
is explicitly future work, not implemented here). Instead, the composer's
message actions include **"Save to Learning Memory"**, turning a specific
assistant explanation or user-stated weakness into a real, structured
memory with one action.

**Woven into future answers, not announced — and never authoritative
(refined in Stage 6.1).** Every chat request automatically includes a
compact, size-limited block of that chat's course's active memories (plus
global ones) in the model's system prompt — at most 12 entries, ~1200
characters, most-recently-updated first. The model is told to treat this
as a soft, possibly outdated hint, never as proof of the student's current
understanding: if a memory says they "understand" a topic but they ask
about it anyway, it's instructed to explain in full rather than shorten or
skip the explanation — real testing during Stage 6.1 showed an earlier,
less careful wording risked exactly that under-explaining failure. It's
also told never to mention, quote, or refer to this background in its
reply, and to always follow the student's current question and teaching
mode when they conflict with it — Quick Answer mode still gives a quick
answer even with a relevant memory present. None of this is enforced by
editing the model's output afterward; it's prompt guidance only, checked
against real `qwen3:4b` responses in both Fast and Deep modes, not just
asserted. Composing this context measures at **well under 1ms of overhead**
regardless of memory count (0/5/20 memories benchmarked — see
[API_CONTRACT.md](API_CONTRACT.md#learning-memory-stage-6)) — it never
materially affects first-token latency.

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
| `STUDYBOT_FAST_MAX_GENERATED_TOKENS` | `4096`                                | Token cap for a Fast reply (includes hidden reasoning) |
| `STUDYBOT_DEEP_MAX_GENERATED_TOKENS` | `6144`                                | Token cap for a Deep reply                |
| `STUDYBOT_FAST_GENERATION_DEADLINE_SECONDS` | `120`                          | Total time limit for a Fast reply         |
| `STUDYBOT_DEEP_GENERATION_DEADLINE_SECONDS` | `300`                          | Total time limit for a Deep reply         |

Examples:

```bash
STUDYBOT_LOG_LEVEL=DEBUG python -m studybot
STUDYBOT_MODEL_PROVIDER=ollama STUDYBOT_OLLAMA_MODEL=qwen3:8b python -m studybot
```

The model name is entirely configuration-driven — swapping in `qwen3:8b`,
`qwen3:14b`, a Gemma or Llama model, or any other model already pulled into
Ollama is just an environment variable change; nothing in the code is tied
to Qwen specifically.

### Generation limits (Stage 6.5)

Every reply is bounded so one runaway generation can't occupy the engine
for hours: a **token cap** (hidden reasoning counts toward it) and a **total
time limit**, with a bigger allowance for Deep than Fast (the table above lists
the four overrides). If a reply hits either limit it is discarded, you see an
error, only your own message is kept, and the chat is immediately usable again.
Invalid values (zero, negative, `nan`, `inf`, non-numeric) refuse to start
rather than being silently corrected.

These are **safety controls, not quality knobs**: a bigger allowance can't make
a small model smarter, it mostly makes a stuck generation last longer. A long
multi-step problem on a reasoning model can still exhaust the token cap; if you
see token-limit errors, raising the relevant cap is the fix. The time limit can
only be enforced while the model is producing output; if the model server itself
stops responding, `STUDYBOT_OLLAMA_TIMEOUT` is what applies.

### Choosing and benchmarking a local model (Stage 6.4)

**The default is `qwen3:4b`.** Stage 6.4 benchmarked it against `qwen3.5:4b` and
`gemma3:4b` on an 8 GB M3 Mac, through the real StudyBot stack with identical
prompts, and **no upgrade was justified**: both candidates failed hard gates
(`qwen3.5:4b` intermittently ran out of its 4,096-token context while
reasoning in Deep mode and, in Practice, revealed answers before the learner
tried; `gemma3:4b` revealed Practice answers and wrongly marked incorrect
answers correct). To try another model, install it (`ollama pull <tag>`) and
override it — no code changes:

```bash
STUDYBOT_MODEL_PROVIDER=ollama STUDYBOT_OLLAMA_MODEL=qwen3.5:4b studybot-server
```

What a model can do is **discovered at runtime** from Ollama's local metadata
(`/api/show`), never assumed from its name: vision, tools, thinking, whether
Fast and Deep genuinely differ, and its advertised context length. Fast and
Deep only differ for a model whose thinking can be switched off; an
always-thinking model (like the default) runs both the same way. A model may
report **vision or tool support that StudyBot does not use yet** — the message
pipeline is text-only and there is no tool loop; capabilities are recorded for
future stages, not wired in.

> **8 GB machines:** don't raise Ollama's context length (`num_ctx` /
> `OLLAMA_CONTEXT_LENGTH`) casually. A model's *advertised* context (often
> 128K+) is not what Ollama actually uses (check `ollama ps`; currently 4,096
> here), and a longer one costs memory you may not have. A thinking model
> that spends the whole window reasoning produces no answer, which StudyBot
> reports as an error rather than showing partial reasoning.

To compare models yourself (development tool; uses a throwaway database per
model, guarded so it can never touch your real data, and prints answers only
with `--show-answers`):

```bash
python scripts/benchmark_local_models.py \
  --models qwen3:4b qwen3.5:4b gemma3:4b --output results.json
python scripts/benchmark_local_models.py --score-from results.json --grades grades.json
```

Saved results hold scenario ids, timings, lengths and capability values —
never prompts or answers. See [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) for how
the AI boundary is structured and what is deliberately not built yet.

## Where chats and courses are stored

Everything lives in one local SQLite database at
`STUDYBOT_DATA_DIR/studybot.db` (default:
`~/Library/Application Support/StudyBot/studybot.db`). The schema is
created and upgraded automatically — there's nothing to run by hand. A
database from any earlier version is upgraded the first time this version
opens it, in one atomic step per version bump: it either fully succeeds or
leaves your existing database completely untouched, chained as needed
(e.g. a Version 0.1 database goes v1 → v2 → v3 → v4 in one open). Existing
chats keep their ids, titles, timestamps, course assignments, and
messages exactly; they simply default to Teach teaching mode and Fast
reasoning mode until you change them. You never need to open this
database file directly; manage everything through the app's commands.

**Resetting local data:** to start over with a clean slate, quit Study Bot
and delete the database file:

```bash
rm ~/Library/Application Support/StudyBot/studybot.db
```

This removes all chats, courses, and mode assignments — do it only if you
actually want to lose your local history.

**Inspecting the database safely (read-only):**

```bash
# A plain read-only look, no risk of writing anything:
sqlite3 -readonly "~/Library/Application Support/StudyBot/studybot.db" \
  "SELECT id, name FROM courses; SELECT COUNT(*) FROM chats; SELECT COUNT(*) FROM learning_memories;"
```

**Backing it up before anything risky** (upgrading, running a real-model
verification script by hand, etc.) — a plain file copy is safe as long as
Study Bot isn't actively running (SQLite's on-disk format has no special
export step for a simple backup):

```bash
studybot_db="$HOME/Library/Application Support/StudyBot/studybot.db"
cp "$studybot_db" "$studybot_db.bak-$(date +%Y%m%d-%H%M%S)"
```

To restore, quit Study Bot and copy the `.bak-...` file back over
`studybot.db`. Nothing in this codebase ever deletes, resets, or writes to
this file automatically as a side effect of development/testing — see
"Real-model verification scripts" below for the guarantee that a
verification script can't touch it either.

### Real-model verification scripts

A script that starts a real `studybot-server` (`STUDYBOT_MODEL_PROVIDER=
ollama`) to check actual model behavior needs its own, disposable database
— never the real one above. **`STUDYBOT_DATA_DIR` is the only environment
variable that controls where that database lives** (`STUDYBOT_DB_PATH`,
used in this project's own earlier verification scripts across several
stages, is not a real setting — `Settings.from_env` silently ignores an
unrecognized key and falls back to the real default directory; this was
found and fixed in Stage 6.2, see `src/studybot/config/
verification_guard.py`). Every real-model verification script should
follow this exact pattern:

```bash
# 1. A fresh, unique, disposable directory — never a hardcoded /tmp path
#    reused across runs, and never the real default.
export STUDYBOT_DATA_DIR="$(mktemp -d -t studybot_verify)"

# 2. Fail fast if it somehow still resolves to the real default directory
#    (e.g. STUDYBOT_DATA_DIR wasn't actually exported, or was overridden
#    again downstream) — this must pass before anything destructive runs.
python3 scripts/check_verification_env.py || exit 1

# 3. Only now start the real server against that confirmed-safe directory.
STUDYBOT_MODEL_PROVIDER=ollama studybot-server &
```

`scripts/check_verification_env.py` prints the resolved database path and
exits `0` when it's safe, or refuses (exit `1`, nothing printed that looks
like a green light) when the resolved directory is, contains, or is
contained by the real default — including when `STUDYBOT_DATA_DIR` was
never set at all. `studybot.config.verification_guard.
assert_safe_for_verification(settings)` is the same check, importable
directly for a verification script that constructs `Settings` in-process
instead of launching a subprocess. Neither this guard, `scripts/
check_verification_env.py`, nor anything else in this codebase ever
deletes, truncates, or modifies the real default database — the guard's
only job is refusing to let a *verification script* proceed against it;
resetting your own real data (see above) remains something only you do,
by hand, on purpose.

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

All tests are deterministic and self-contained: they fake the `ollama`
client boundary (`tests/fake_ollama.py`) rather than requiring a running
Ollama server or a downloaded model, and every persistence test opens its
own SQLite database under pytest's `tmp_path` — no test reads or writes
`~/Library/Application Support/StudyBot` or any other real user data. The
API tests (`tests/test_api_*.py`) use FastAPI's `TestClient` (in-process,
no real network/port) with a fake `ModelProvider` where streaming/failure
behavior needs to be controlled deterministically — no test requires a
running API server, Ollama, or internet.

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

The API server follows the same rules: it binds to `127.0.0.1` only, never
logs request bodies (where message/course content lives) or the auth
token, and its per-request access log is effectively disabled by default
so there's no log surface to worry about. See
[API_CONTRACT.md](API_CONTRACT.md#privacy) for specifics.

## Architecture

```
CLI (python -m studybot)     Flutter (frontend/studybot_app) → studybot.api (FastAPI, HTTP + WebSocket)
        ↓                                              ↓
        └──────────────────→ StudyBotApp (src/studybot/app.py) ←──────────────────┘
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

Both interfaces are equally thin: neither the CLI nor `studybot/api/`
contains course/chat/mode business logic — both only translate their own
transport (terminal I/O vs. HTTP/WebSocket JSON) into calls on
`SessionService`/`CourseService` and translate results back. Everything
below `StudyBotApp` is completely unaware that either interface, or FastAPI/
Starlette/HTTP/WebSocket, exists.

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
  the single place baseline instructions, course context, learning-memory
  context (Stage 6), and teaching-mode instructions are composed into one
  system prompt, in that order — kept separate from both
  `core/prompts.py`/`core/mode_prompts.py` and any model provider so
  there's no scattered string concatenation elsewhere
- `src/studybot/core/learning_memory.py` (Stage 6) — the `MemoryKind`
  (`understands`/`needs_review`/`misconception`/`learning_goal`/
  `useful_strategy`) and `MemoryStatus` (`active`/`archived`) enums, their
  display metadata/`all_kinds()` catalog, `parse_memory_kind()`, and
  `opposes()` — the pure building block the conflict/supersession policy
  is built on (which kinds represent opposite learning states for the same
  topic). No I/O, no business logic.
- `src/studybot/core/memory_service.py` (Stage 6) — `LearningMemoryService`:
  validation/normalization, the duplicate (`MEMORY_CONFLICT`) and
  conflict/supersession (auto-archive) policy, course-scoped CRUD, and
  `build_memory_context_text()` — the compact, size-limited block injected
  into a chat's system prompt. The only place that knows what a "learning
  memory" is at the business-logic level; `OllamaModel`, the SQLite
  repository, and Flutter never do.
- `src/studybot/core/titles.py` — deterministic, local chat-title
  generation from a chat's first message (no LLM call)
- `src/studybot/core/chat.py` — `ChatService`: in-memory history for one
  chat, `send`/`send_streaming`, `clear`, `get_status`; can be seeded with
  restored history via its `history=` constructor argument; stateless
  enough to be freely (re)constructed per request, which is exactly what
  `SessionService`'s explicit-by-id layer does
- `src/studybot/core/session_service.py` — `SessionService`: two layers
  over the same storage (Stage 5.8). The **active-chat convenience layer**
  (unchanged since earlier stages) owns one mutable "current chat" per
  process — `new_chat`/`open_chat`/`send`/`send_streaming`/
  `get_teaching_mode()`/`set_teaching_mode()`/etc. — exactly what the CLI
  needs. The **explicit-by-id layer**
  (`create_chat`/`send_to_chat`/`send_streaming_to_chat`/`rename_chat`/
  `set_teaching_mode_for_chat`/`assign_course_to_chat`/...) takes a
  `chat_id` and operates on exactly that chat, loaded fresh from the
  repository every call, with no cursor involved — this is what the API
  layer is built on. A per-chat `threading.Lock` (`_chat_lock`) rejects a
  second concurrent generation for the same chat id with `ChatBusyError`
  rather than letting two replies race; different chat ids are never
  blocked by each other. Both layers persist new messages the same way:
  by diffing a `ChatService`'s history before/after each call.
- `src/studybot/core/course_service.py` — `CourseService`: course
  validation (name required and length-limited; optional fields trimmed;
  full Unicode support) and CRUD, independent of `SessionService`.
  `delete_course` calls `CourseRepository.delete_course_archiving_memories`
  (Stage 6.2) — see "Learning memory" above for why
- `src/studybot/storage/sqlite_course_repository.py` —
  `delete_course_archiving_memories` (Stage 6.2) archives a doomed
  course's active memories and deletes the course as one real SQLite
  transaction; the one deliberate, documented exception to "one
  repository, one table" in this codebase, made because a transaction is
  connection-scoped, not repository-scoped
- `src/studybot/config/verification_guard.py` (Stage 6.2) —
  `assert_safe_for_verification(settings)` refuses to let a real-model
  verification script run against the real default data directory; see
  "Real-model verification scripts" above and `scripts/
  check_verification_env.py`, a thin CLI wrapper around it
- `src/studybot/core/exceptions.py` — `StudyBotError` and subclasses:
  `SessionError` for chat/course navigation or validation problems (not
  found, ambiguous id prefix, empty name, ...); `ChatNotFoundError`/
  `CourseNotFoundError` (`SessionError` subtypes) for precise
  `CHAT_NOT_FOUND`/`COURSE_NOT_FOUND` mapping when a call could otherwise
  raise either; `ChatBusyError` for the per-chat generation lock above;
  `MemoryNotFoundError` (Stage 6, a `SessionError` subtype) and
  `MemoryConflictError` (Stage 6) for the learning-memory duplicate policy
- `src/studybot/storage/sqlite_learning_memory_repository.py` (Stage 6) —
  `SQLiteLearningMemoryRepository`, one of three modules allowed to
  contain SQL (with `sqlite_repository.py`/`sqlite_course_repository.py`);
  a dumb data layer with no validation or policy logic of its own
- `src/studybot/models/` — unchanged since Stage 2 (`ModelProvider`,
  `MockModel`, `OllamaModel`, the provider factory); `OllamaModel` has no
  awareness of courses, teaching modes, or SQLite
- `src/studybot/storage/base.py` — `ChatRepository`/`CourseRepository`
  protocols and the `ChatSession`/`Course` domain types (`ChatSession`
  carries a typed `teaching_mode: TeachingMode`); nothing outside
  `storage/` sees a raw SQLite row
- `src/studybot/storage/database.py` — opens the one shared
  `sqlite3.Connection` both repositories use and applies schema migrations,
  versioned via SQLite's own `PRAGMA user_version` (currently `4`); each
  migration step runs in one explicit, all-or-nothing transaction, chained
  as needed (v1 → v2 → v3 → v4)
- `src/studybot/storage/sqlite_repository.py` / `sqlite_course_repository.py`
  — the **only** two modules allowed to contain SQL; parameterized queries
  only, for chats/messages and courses respectively. `sqlite_repository.py`
  converts the stored `teaching_mode` string to a `TeachingMode` at the
  repository boundary, falling back to the default mode (with a warning
  log containing only the invalid identifier, never chat content) if the
  stored value is ever unrecognized
- `src/studybot/logging_config.py` — console logging setup; quiet by
  default, verbosity controlled via `STUDYBOT_LOG_LEVEL`
- `src/studybot/api/` — the local HTTP + WebSocket bridge; see
  [API_CONTRACT.md](API_CONTRACT.md) for the contract and
  `api/engine.py`'s docstring for why every call is routed through one
  dedicated worker thread (the shared SQLite connection is not safe to
  touch from FastAPI's default worker pool — found and fixed via this
  stage's own testing). Nothing under `core/`, `models/`, or `storage/`
  imports anything from this package or knows it exists.

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

### Schema migrations (v1 → v2 → v3 → v4 → v5)

- **v1 → v2** (Stage 4): adds a `courses` table and a nullable
  `chats.course_id` referencing it with `ON DELETE SET NULL` — deleting a
  course never touches its chats or their messages.
- **v2 → v3** (Stage 5): adds `chats.teaching_mode` (`NOT NULL DEFAULT
  'teach'`) — every existing chat becomes Teach mode; nothing else changes.
- **v3 → v4** (Stage 5.7): adds `chats.reasoning_mode` (`NOT NULL DEFAULT
  'fast'`) — every existing chat becomes Fast reasoning mode; teaching
  mode, courses, chats, and messages are all left completely untouched.
- **v4 → v5** (Stage 6): adds a new `learning_memories` table (`course_id`
  and `source_chat_id` both nullable, both `ON DELETE SET NULL`, plus
  indexes on `course_id`/`status`/`topic`) — a brand-new table, so no
  existing courses/chats/messages/modes are touched at all; the table
  starts empty.

Each step is one explicit SQL transaction (`BEGIN` ...
`commit()`/`rollback()` — plain DDL statements are *not* automatically
transactional in Python's `sqlite3` module, so this is done by hand): if
anything in a step fails, the database is left exactly as it was before
that step, not partially upgraded. Steps chain automatically (a v1
database run against this version goes straight to v5 in one `open`), a
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

The Flutter app at [`frontend/studybot_app/`](frontend/studybot_app/) now
covers courses, chats, teaching modes, reasoning modes, streaming
conversation, and (Stage 6) learning memory end to end, with control over
Ollama's thinking behavior (Stage 5.7) so simple prompts answer materially
faster by default, an API that no longer depends on a single mutable
"active chat" per process (Stage 5.8), and durable, user-controlled,
course-scoped learning facts that are woven into future answers without
ever exposing a mastery percentage (Stage 6). Deliberately **not** yet
implemented: numeric mastery/scoring, automatic LLM-driven memory
extraction, a knowledge graph, spaced repetition, quizzes, a study planner,
RAG over PDFs/notes/slides, embeddings, image/screenshot understanding,
calendar/LMS integration, cloud sync, accounts, and eventually device/tool
access — none of which exists yet, in either the API or the Flutter app.
