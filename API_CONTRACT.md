# Study Bot API Contract (v1)

This document is the reference for building a client (Flutter or
otherwise) against the Study Bot engine API added in Stage 5.5. It is
deliberately written by hand rather than left to auto-generated OpenAPI
docs, since the things a client author needs most — auth, the WebSocket
protocol, error codes, and the documented architectural limitations — are
exactly the things auto-generated docs describe worst.

The API is a thin transport layer over the same application services the
CLI (`python -m studybot`) uses (`SessionService`, `CourseService`). It
contains no course/chat/mode business logic of its own — every endpoint
translates a request into an existing service call and translates the
result back into JSON.

## Startup

```
python -m studybot.api
# or, once installed:
studybot-server
```

This is a **separate process** from the CLI (`python -m studybot`), which
is unchanged and keeps working exactly as before. Both can run at the same
time against the same local SQLite database (each opens its own
connection); that's fine for the sequential, single-user usage this stage
targets (see "Known limitations" below for the one caveat).

The server binds to **`127.0.0.1` only** — this is not configurable, by
design, so there is no way to accidentally expose it on the local network.

On startup, exactly one line of JSON is printed to **stdout** (not through
the logging system, so it never ends up in a log file):

```json
{"event": "studybot_api_ready", "host": "127.0.0.1", "port": 8765, "token": "<random>"}
```

A launcher (Flutter, or a dev harness) reads this one line to learn the
port and the auth token for this process. Neither value is persisted
anywhere or logged again after this line.

### Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `STUDYBOT_API_PORT` | `8765` | Port to bind. Set to `0` to request an OS-assigned ephemeral port — the actual bound port is always reported in the startup line above, so this works even when `0` was requested. |
| `STUDYBOT_API_TOKEN` | *(random)* | Deliberate development/test hook: pin a known token instead of generating a random one, so a dev harness doesn't have to scrape stdout. **Do not rely on this for anything but local development** — a real launcher should always read the token from the startup line. |

All the usual `STUDYBOT_*` settings (`STUDYBOT_MODEL_PROVIDER`,
`STUDYBOT_DATA_DIR`, `STUDYBOT_OLLAMA_MODEL`, ...) apply identically to the
API server and the CLI — see the main README.

### Shutdown

`Ctrl+C` (SIGINT) or SIGTERM triggers a graceful shutdown: in-flight
requests are allowed to finish, the SQLite connection is closed cleanly,
and the process exits without a traceback. Verified manually with both
signals against a real server.

## Authentication

Every request (HTTP and WebSocket) must carry:

```
Authorization: Bearer <token>
```

using the token from the startup line. There is no user-account system —
this is a single, high-entropy, per-process token, generated fresh every
time the server starts (`secrets.token_urlsafe(32)` unless overridden by
`STUDYBOT_API_TOKEN`), that authorizes anything on the local machine that
knows it, for exactly as long as this process lives. It is:

- never persisted to disk,
- never written to a log file (only to the one-time stdout startup line),
- never accepted via a query string or any other part of a URL.

A missing or incorrect token gets `401` with `{"code": "UNAUTHORIZED", ...}`
on HTTP, or the WebSocket connection is closed (code `4401`) before
`accept()` — no data is exchanged with an unauthenticated client at all.

## Versioning

Every route is under `/api/v1/...`. A future breaking change gets a new
`/api/v2/...` prefix added *alongside* v1, not a replacement — existing
clients on v1 keep working.

## Error model

Errors are JSON with a stable, machine-readable `code` and a human-readable
`message`. **Clients should switch on `code`, never parse `message`.**

```json
{"code": "CHAT_NOT_FOUND", "message": "No chat found with id '...'."}
```

| Code | HTTP status | Meaning |
|---|---|---|
| `CHAT_NOT_FOUND` | 404 | No chat with that id exists. |
| `COURSE_NOT_FOUND` | 404 | No course with that id exists. |
| `INVALID_MODE` | 422 | The `mode` string isn't a recognized teaching mode. |
| `INVALID_REASONING_MODE` | 422 | The `reasoningMode` string isn't a recognized reasoning mode. |
| `MODEL_UNAVAILABLE` | — | Reported via `GET /health`'s `providerReachable: false`, not as an error response — see below. |
| `MODEL_ERROR` | — (WebSocket `error` event) | The model failed to produce a response (connection issue, missing model, timeout, ...). Covers every generation-time failure uniformly; `message` carries the same user-safe detail text `OllamaModel` already produces for the CLI (e.g. the exact `ollama pull ...` command for a missing model). There is no finer-grained code because the underlying domain exception (`ModelError`) doesn't currently distinguish sub-cases either — see "Known limitations". |
| `VALIDATION_ERROR` | 422 | A business-rule validation failed (e.g. an empty course/chat name) or a WebSocket message was malformed. |
| `UNAUTHORIZED` | 401 | Missing/invalid auth token. |
| `INTERNAL_ERROR` | 500 | An unexpected server-side exception. The traceback is logged server-side (method + path only — never a request body) and never sent to the client. |

Python tracebacks never reach a client under any circumstance.

## Endpoints

All request/response bodies are JSON with **camelCase** field names (the
`ApiModel` base class aliases Python's snake_case attributes to camelCase
on the wire — Dart/Flutter's own JSON convention).

### Health

```
GET /api/v1/health
```
```json
{
  "apiVersion": "1",
  "status": "ok",
  "provider": "ollama",
  "model": "qwen3:4b",
  "providerReachable": true,
  "modelAvailable": true
}
```
`providerReachable`/`modelAvailable` mirror the CLI's `/status` command
(via `SessionService.get_status()` → `ProviderStatus`) — `null` when not
applicable (e.g. always `true`/non-null for `mock`).

### Courses

```
GET    /api/v1/courses                  -> [CourseOut]
POST   /api/v1/courses                  <- CourseCreateIn  -> CourseOut (201)
GET    /api/v1/courses/{id}             -> CourseOut
PUT    /api/v1/courses/{id}             <- CourseUpdateIn  -> CourseOut
DELETE /api/v1/courses/{id}             -> 204
```

```jsonc
// CourseOut
{
  "id": "...", "name": "University Physics I", "code": "PHY 215",
  "term": "Fall 2026", "description": "...",
  "createdAt": "...", "updatedAt": "..."
}
// CourseCreateIn / CourseUpdateIn
{ "name": "...", "code": null, "term": null, "description": null }
```

**`PUT` is a full replace**, matching `CourseService.edit_course`'s
existing contract exactly: send back the fields you want kept unchanged.
There is no "omit a field to keep it" merge semantics here — that's a
CLI-only presentation behavior (`/course edit`'s blank-means-keep,
`-`-means-clear prompts), not something the underlying service supports,
and the API does not duplicate it.

**Deleting a course never deletes chats or messages** — they become
unassigned (`courseId: null`). This is enforced by the database (`ON
DELETE SET NULL`), not reimplemented here.

### Teaching modes

```
GET /api/v1/modes -> [ModeInfoOut]
```
```json
[{"id": "teach", "displayName": "Teach", "description": "..."}, ...]
```
Always all five modes (`teach`, `homework`, `quick`, `practice`, `exam`),
sourced directly from `core.teaching_mode.all_modes()` — never duplicated
in the API layer, so this catalog can't drift from what the mode prompts
actually implement.

### Reasoning modes (Stage 5.7)

```
GET /api/v1/reasoning-modes -> [ModeInfoOut]
```
```json
[{"id": "fast", "displayName": "Fast", "description": "..."},
 {"id": "deep", "displayName": "Deep Think", "description": "..."}]
```
Always both modes (`fast`, `deep`), sourced from
`core.reasoning_mode.all_modes()`. Uses the same `ModeInfoOut` shape as
`GET /modes` (an id plus display metadata) — the two catalogs are
otherwise unrelated: **reasoning mode is completely independent of
teaching mode.** Teaching mode (Teach/Homework/Quick/Practice/Exam)
controls instructional behavior via the system prompt; reasoning mode
(Fast/Deep) controls the model's inference-time "thinking" depth and
latency and never touches the system prompt at all. A chat can be in any
combination of the two, and changing one never affects the other.

`fast` maps to Ollama's `think=False`; `deep` maps to `think=True` — see
`models/ollama.py`. **Hidden reasoning/thinking text is never sent to a
client and never persisted** — only the final, user-visible answer is
ever included in a `delta` event, `MessageOut.content`, or a WebSocket
`message_completed` payload, regardless of reasoning mode.

### Chats

```
GET    /api/v1/chats?course_id=...      -> [ChatOut]
POST   /api/v1/chats                    <- ChatCreateIn  -> ChatOut (201)
GET    /api/v1/chats/{id}               -> ChatOut
GET    /api/v1/chats/{id}/messages      -> [MessageOut]
PUT    /api/v1/chats/{id}/rename        <- {"title": "..."}  -> ChatOut
POST   /api/v1/chats/{id}/clear         -> ChatOut
DELETE /api/v1/chats/{id}               -> 204
PUT    /api/v1/chats/{id}/course        <- {"courseId": "..." | null}  -> ChatOut
GET    /api/v1/chats/{id}/mode          -> ModeInfoOut
PUT    /api/v1/chats/{id}/mode          <- {"mode": "homework"}  -> ModeInfoOut
GET    /api/v1/chats/{id}/reasoning-mode -> ModeInfoOut
PUT    /api/v1/chats/{id}/reasoning-mode <- {"reasoningMode": "deep"}  -> ModeInfoOut
```

```jsonc
// ChatOut
{
  "id": "...", "title": "...", "courseId": "..." | null,
  "teachingMode": "teach", "reasoningMode": "fast",
  "createdAt": "...", "updatedAt": "..."
}
// MessageOut
{ "id": 1, "role": "user", "content": "...", "createdAt": "..." }
```

- `GET /chats` with no query param lists every chat. `?course_id=<id>`
  filters to that course; `?course_id=none` filters to unassigned
  ("General") chats specifically.
- `POST /chats` with an omitted/`null` `courseId` always creates a
  **General** chat — unlike the CLI's `/new`, it never inherits "whatever
  course happens to be active" (there is no such ambient state from an API
  client's point of view; see "Known limitations").
- **Chat ids are full stable UUIDs.** The CLI's short-id-prefix convenience
  (`/open a3f1`) is a terminal-typing affordance and is *not* part of the
  API contract — always send the complete id you were given.
- `MessageOut` never includes the system prompt, course context, or
  teaching-mode instructions — only real, persisted user/assistant turns,
  exactly what `ChatRepository.load_message_records` returns.
- Every new chat starts at `reasoningMode: "fast"`, exactly like teaching
  mode always starts at `"teach"` — a new chat never inherits whatever
  reasoning mode was active elsewhere.

**Lazy persistence (important, and easy to be surprised by):** creating a
chat does **not** write a database row — this mirrors the CLI's existing
behavior (a chat launched and never used leaves no trace). A chat becomes
retrievable via `GET` only *after* its first message completes. If your UI
navigates straight to a newly created chat's detail screen, don't be
surprised by a `404` from `GET /chats/{id}` until a message has actually
been sent — use the `ChatOut` returned by the `POST` response for the
initial render instead of immediately re-fetching.

### WebSocket streaming chat

```
GET /api/v1/ws/chat   (upgrade to WebSocket)
```

Authenticate the same way as HTTP: `Authorization: Bearer <token>` on the
handshake request. One connection can be reused for any number of
messages, to any chat id, in sequence.

**Client → server** (only one message type):
```json
{"type": "send_message", "chat_id": "...", "content": "Explain acceleration"}
```

**Server → client**, in order, for each `send_message`:
```json
{"type": "message_started", "chatId": "..."}
{"type": "delta", "content": "Accel"}
{"type": "delta", "content": "eration"}
...
{"type": "message_completed", "message": {"id": 12, "role": "assistant", "content": "...", "createdAt": "..."}}
```
or, instead of the above, at any point:
```json
{"type": "error", "code": "MODEL_ERROR", "message": "..."}
```

An `error` event **does not close the connection** — send another
`send_message` on the same socket to try again or move to a different chat.

**Reasoning mode and streaming (Stage 5.7):** the chat's current reasoning
mode (see "Reasoning modes" above) is applied automatically to every
`send_message` on that chat — there is no separate parameter on the
WebSocket message itself; change it first via `PUT
/chats/{id}/reasoning-mode`. In Fast mode, the first `delta` typically
arrives quickly. In Deep mode, expect a materially longer gap between
`message_started` and the first `delta` while the model reasons — this is
expected, not a stall. **Whichever mode is active, only visible-answer
`delta` chunks are ever sent** — if the backend model produces hidden
"thinking" content, it is filtered out before reaching the WebSocket, never
streamed and never included in the final `message_completed.message`.

This reuses `SessionService.send_streaming()` exactly as the CLI does —
there is no second streaming implementation. That means the existing
Stage 2/3 guarantee carries through unchanged:

- **Success:** the user's message is persisted once; the complete assistant
  reply is persisted once, only after the stream finishes.
- **Failure (`MODEL_ERROR`) or client disconnect mid-stream:** the user's
  message may already be persisted (so retrying doesn't require retyping),
  but **no partial/incomplete assistant message is ever persisted** — not
  one row per token, and never a synthetic "Error: ..." message standing in
  for the assistant. This is enforced by `ChatService`/`SessionService`
  themselves (see their docstrings), not reimplemented in the WebSocket
  handler.

**Client disconnect handling:** if the client vanishes mid-generation, the
server does not crash and does not attempt to keep generating in the
background — the in-flight generator is closed (so no more of the model's
output is persisted or requested) and the connection handler exits
cleanly. Detection isn't instantaneous: since nothing is actively polling
for the disconnect while a chunk is being produced, it's only noticed the
next time the server tries to *send* a chunk to the now-gone client. This
mirrors the CLI's own equivalent limitation (Ctrl+C doesn't instantly
cancel an in-flight Ollama call either) — deliberately not solved with
more complex cancellation plumbing in this stage.

## Known limitations (documented, not hacked around)

**Single active-chat cursor.** `SessionService` — reused unchanged from the
CLI — was built around one mutable "active chat" per process, not a
request-scoped concept. Every API operation that needs a live model
context (rename, clear, delete, move-course, mode change, and the
WebSocket send) switches that cursor to the requested `chat_id` first, so
each *individual* request is self-contained and explicit — a client never
needs to call some separate "select this chat" endpoint first. What this
does **not** make safe is *concurrently interleaved* requests targeting
*different* chat ids against the *same running server process* (e.g. two
requests for two different chats in flight at the same moment) — the
cursor could be switched out from under one of them. For a single Flutter
app instance talking to its own engine process, driving one chat's
conversation at a time (the normal UI pattern — you're looking at one chat
screen), this is a non-issue. It would need addressing before this API
supports multiple simultaneous windows/devices against one engine process.
Read-only endpoints (`GET /chats`, `GET /chats/{id}`, `GET
/chats/{id}/messages`) are unaffected — they go through `SessionService`'s
stateless `get_chat`/`get_chat_history_records` passthroughs and never
touch the cursor.

**One `MODEL_ERROR` code for all generation failures.** The underlying
`ModelError` domain exception doesn't currently distinguish "connection
refused" from "model not found" from "timeout" as separate types — only as
different message text (already user-safe, written for the CLI). Rather
than fragile string-matching in the API layer to recover a sub-code that
doesn't structurally exist, every generation failure is `MODEL_ERROR`;
`GET /health`'s `providerReachable` is the one place a *pre-flight*
unavailability check is exposed with its own boolean, since that comes
from `ProviderStatus` (a real structured type), not from parsing an
exception.

**SQLite thread affinity.** `StudyBotApp` (and its one `sqlite3.Connection`)
is not designed to be touched from multiple threads. FastAPI dispatches
route handlers to a worker pool, so every call into `StudyBotApp` — the
constructor itself included — is routed through one dedicated
single-worker executor (`api/engine.py`) rather than left to land on
whatever thread FastAPI happens to pick. This was found and fixed during
this stage's own testing (`sqlite3.ProgrammingError: SQLite objects
created in a thread can only be used in that same thread`), not
anticipated in advance.

## Privacy

No analytics, telemetry, or remote reporting exist anywhere in this
codebase. The API adds no exception to that. Specifically:

- Request bodies (which is where message/course content lives — never in a
  URL or query string) are never logged.
- The unexpected-error handler logs only the HTTP method and path (chat/
  course ids only — UUIDs, not content) plus the exception, for developers;
  the client only ever receives the generic `INTERNAL_ERROR` message.
- Uvicorn's per-request access log is effectively disabled (`log_level=
  "warning"`, above the access log's own `INFO` level) — verified: a real
  run's server log contains only the one startup line, no per-request
  lines at all, so there's no access-log surface to worry about leaking
  anything.
- The auth token is never logged (verified by test, including deliberately
  wrong tokens).
