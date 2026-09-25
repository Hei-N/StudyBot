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
| `CHAT_BUSY` | — (WebSocket `error` event) | That chat already has a generation (`send_message`) in progress on some connection; this one was rejected rather than allowed to race it — see "Concurrency and chat identity" below. Retry once the first one finishes. |
| `COURSE_NOT_FOUND` | 404 | No course with that id exists. |
| `MEMORY_NOT_FOUND` | 404 | No learning memory with that id exists. |
| `MEMORY_CONFLICT` | 409 | Creating/reactivating this memory would produce two *active* memories with the same normalized topic and kind in the same scope — see "Learning memory" below. |
| `INVALID_MODE` | 422 | The `mode` string isn't a recognized teaching mode. |
| `INVALID_REASONING_MODE` | 422 | The `reasoningMode` string isn't a recognized reasoning mode. |
| `INVALID_MEMORY_KIND` | 422 | The `kind` string isn't one of the five recognized learning-memory kinds. |
| `INVALID_MEMORY_STATUS` | 422 | The `status` filter isn't `active` or `archived`. |
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
  client's point of view — every chat-specific operation is addressed by
  `chat_id` alone; see "Explicit chat-id semantics" below).
- **Chat ids are full stable UUIDs.** The CLI's short-id-prefix convenience
  (`/open a3f1`) is a terminal-typing affordance and is *not* part of the
  API contract — always send the complete id you were given.
- `MessageOut` never includes the system prompt, course context, or
  teaching-mode instructions — only real, persisted user/assistant turns,
  exactly what `ChatRepository.load_message_records` returns.
- Every new chat starts at `reasoningMode: "fast"`, exactly like teaching
  mode always starts at `"teach"` — a new chat never inherits whatever
  reasoning mode was active elsewhere.

**Immediate persistence (Stage 5.8):** `POST /chats` writes a real database
row before responding — the returned `id` is retrievable via `GET`, has an
empty message history, and accepts every operation below immediately, with
zero messages sent. This is deliberately *not* what the CLI's `/new` does
(the CLI still defers writing a row until the first message, so a terminal
chat opened and abandoned leaves no trace — see "Known limitations" in the
main README for that CLI-only convenience); an API client has no such
concept, and an earlier version of this API used to defer persistence the
same way the CLI does, which caused a real bug: creating a second chat
before the first had ever been messaged could silently make the first
chat's id 404. It cannot anymore — see "Explicit chat-id semantics" below.

**Explicit chat-id semantics:** every chat-specific endpoint above operates
on exactly the `chat_id` in its URL, loaded fresh from storage on every
call. There is no server-side "current chat" for the API to get out of
sync with, no "open this chat first" step, and no ordering requirement
between requests for different chat ids — creating, messaging, renaming,
or reconfiguring one chat never affects any other chat's availability or
state, no matter what order requests arrive in or how many other chats
exist. (The CLI *does* still have a single current chat — `/open`, `/new`,
etc. — but that's a terminal-only convenience built on top of the same
explicit-by-id operations; it was never something the API needed and
nothing here depends on it.)

### Learning memory (Stage 6)

```
GET    /api/v1/memory-kinds                         -> [MemoryKindInfoOut]
GET    /api/v1/memories?course_id=...&kind=...&status=...  -> [LearningMemoryOut]
POST   /api/v1/memories                              <- LearningMemoryCreateIn  -> LearningMemoryOut (201)
GET    /api/v1/memories/{id}                         -> LearningMemoryOut
PATCH  /api/v1/memories/{id}                         <- LearningMemoryUpdateIn  -> LearningMemoryOut
POST   /api/v1/memories/{id}/archive                 -> LearningMemoryOut
POST   /api/v1/memories/{id}/restore                 -> LearningMemoryOut
DELETE /api/v1/memories/{id}                         -> 204
```

```jsonc
// MemoryKindInfoOut — GET /memory-kinds always returns exactly these five
[{"id": "understands", "displayName": "Understands", "description": "..."},
 {"id": "needs_review", "displayName": "Needs review", "description": "..."},
 {"id": "misconception", "displayName": "Misconception", "description": "..."},
 {"id": "learning_goal", "displayName": "Goal", "description": "..."},
 {"id": "useful_strategy", "displayName": "Helpful approach", "description": "..."}]

// LearningMemoryOut
{
  "id": "...", "courseId": "..." | null, "sourceChatId": "..." | null,
  "topic": "Vector components", "kind": "needs_review",
  "summary": "Often mixes x/y components.", "status": "active",
  "createdAt": "...", "updatedAt": "..."
}

// LearningMemoryCreateIn
{ "topic": "...", "kind": "needs_review", "summary": "...",
  "courseId": null, "sourceChatId": null }

// LearningMemoryUpdateIn (PATCH — every field optional; see below)
{ "topic": "...", "kind": "...", "summary": "...", "courseId": "..." | null }
```

**What this is, and what it isn't:** a learning memory is one deliberately
recorded, durable piece of learning information ("needs review: vector
components", "understands significant figures") — completely separate from
chat history, which just answers "what was said?". Clearing or deleting a
chat never destroys a memory it produced (see `sourceChatId` below). This
is **not** a mastery/scoring engine: there is no percentage, numeric
weight, or aggregation anywhere in this API, deliberately — see the main
README's "Learning memory" section for the full rationale.

**The five kinds are a closed, strict set** (`understands`, `needs_review`,
`misconception`, `learning_goal`, `useful_strategy`) — always fetch them
from `GET /memory-kinds` rather than hardcoding them, exactly like teaching
modes. `status` is `active` or `archived`; archiving (not deleting) is the
normal way a memory is retired — a superseded memory is still visible via
`?status=archived`, never silently lost. `DELETE` is a separate, explicit
hard delete.

**Course scope:** `courseId: null` means a genuinely general/global memory
(shown in every course's context, and in a General chat's), not the common
case — most memories should belong to a course. A course-scoped memory
never appears in a different course's context, no matter how similar the
wording (see "Context injection" below).

**`sourceChatId` is provenance only.** It records which chat (if any)
produced a memory, but the memory's validity never depends on that chat
still existing: clearing or deleting the source chat leaves the memory
completely intact and simply sets `sourceChatId` to `null` (`ON DELETE SET
NULL`, like `chats.courseId` → `courses.id`). Neither foreign key ever
cascades a delete into a memory.

**Deleting a course archives its memories first (Stage 6.1).** The
database's `ON DELETE SET NULL` on `learning_memories.courseId` would, on
its own, turn every *active* memory in a deleted course into an active
*global* one the instant the course disappears — silently injecting that
subject's context into every other course's (and every General chat's)
requests from then on. `DELETE /courses/{id}` prevents that: every
currently active memory belonging to that course is archived first, then
the course is deleted. Only that course's memories are touched — memories
that were already global, or that belong to a different course, are
completely unaffected. The archived memory keeps all its content (topic,
kind, summary) and is fully visible via `?status=archived` and editable —
it is never hard-deleted by this. Its `courseId` still becomes `null` (the
same `ON DELETE SET NULL` as before), so recovering it is a **separate,
explicit** decision: `POST /memories/{id}/restore` makes it an active
*global* memory (since its course is gone), or `PATCH
{"courseId": "<a-different-course>"}` reassigns it to a different existing
course first (in either order relative to restoring). Neither happens
automatically — both require the same deliberate action a brand-new
global/reassigned memory would need. This applies uniformly everywhere a
course can be deleted (the HTTP API and the CLI's `/course delete` both go
through the same `CourseService.delete_course`, so there is only one
implementation of this policy to keep correct).

**`PATCH` is a true partial update**, unlike course's full-replace `PUT`:
omit a field to leave it unchanged. `topic`/`kind`/`summary` additionally
treat an explicit `null` the same as omission (a valid value can never
legitimately be `null`). `courseId` is the one field where explicit `null`
is meaningful (unassign to General) and distinct from omitting it
(leave unchanged) — send the key only when you actually want to change it.

**Duplicate and conflict policy (deliberately simple — no fuzzy/semantic
matching in Stage 6):** topics are compared case-insensitively with
whitespace collapsed, within one scope (the same `courseId`, including
`null`==`null` for global).
- Creating (or restoring) an *active* memory whose normalized topic and
  exact kind already has an active match in that scope is rejected with
  `MEMORY_CONFLICT` — edit the existing memory via `PATCH` instead of
  creating a duplicate.
- Creating (or restoring) an *active* memory whose normalized topic
  matches an active memory in an **opposing** learning state (`understands`
  vs. `needs_review`/`misconception`) automatically **archives** the
  superseded one — learning changes, and the old state is preserved via
  archiving, never silently kept active forever or hard-deleted.
  `learning_goal`/`useful_strategy` never oppose anything or trigger this.
- Anything else (different topic, or a different non-opposing kind on the
  same topic, e.g. an existing `needs_review` alongside a new
  `learning_goal`) creates normally, with no conflict.

**Context injection into chat responses:** every chat request (both the
WebSocket `send_message` path and the CLI) automatically includes a
compact block of that chat's course's active memories (plus any global
ones) in the model's system prompt — there is no separate API call needed
to "activate" memory for a chat, and no way to turn it off per-request. At
most 12 entries and roughly 1200 characters are included, most recently
updated first, course-specific entries preferred over global ones — never
the full memory history. This costs well under a millisecond of extra
request-preparation time regardless of how many memories exist (measured;
see the main README's "Performance" notes), so it never materially affects
first-token latency.

The model is instructed (Stage 6.1 wording, refined after real testing) to
treat this context as a soft, possibly outdated hint about where to
focus — **never as proof of the student's current understanding**, and
never authoritative over what they're actually asking right now. If a
memory says the student "understands" a topic but they ask about it
anyway, the instruction is to explain it in full, not shorten, skip, or
refuse the explanation because of the memory — a real failure mode caught
during testing (an earlier, less careful wording risked the model treating
"understands" as a reason to under-explain). It's told never to mention,
quote, or otherwise refer to this background or its existence in its
reply, and to always follow the student's current question and the active
teaching mode when they conflict with it (e.g. Quick Answer mode still
answers quickly, even with a "needs review" memory for the topic asked
about). None of this is enforced by post-processing the model's output —
there is no text stripped or filtered after generation; it is prompt
guidance only, verified against real `qwen3:4b` output in both Fast and
Deep modes rather than assumed. Nothing about this is visible in
`MessageOut`/`message_completed` — the
composed context is injected the same way course context and teaching-mode
instructions already were, and is never itself persisted as a chat
message.

**No automatic extraction (deliberate, for now):** nothing in this API
calls a model to generate a learning memory automatically after a chat
response. Every memory is created by an explicit `POST /memories` — driven
by the user (a "Save to Learning Memory" action in the Flutter app) or a
future application feature, but never as a hidden side effect of sending a
message. This is a deliberate Stage 6 scope decision, not a technical
limitation — see "Deferred" in the Stage 6 report for what a later stage
might add here.

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
{"type": "delta", "content": "Accel", "chatId": "..."}
{"type": "delta", "content": "eration", "chatId": "..."}
...
{"type": "message_completed", "chatId": "...", "message": {"id": 12, "role": "assistant", "content": "...", "createdAt": "..."}}
```
or, instead of the above, at any point:
```json
{"type": "error", "code": "MODEL_ERROR", "message": "...", "chatId": "..."}
```

**Every event carries `chatId`** (Stage 5.8) — since one connection can be
reused for any number of chats in sequence, this lets a client attribute
each event to the right chat without having to track "whichever chat I
sent to last" itself. (`chatId` is omitted only for a malformed
`send_message` payload that never named a valid chat id to begin with —
e.g. a missing/non-string `chat_id` field.)

An `error` event **does not close the connection** — send another
`send_message` on the same socket to try again or move to a different chat.

**Concurrency and chat identity (Stage 5.8):** `send_message` addresses its
`chat_id` explicitly and independently every time — sending to chat A and
then chat B on the same connection (or on two different connections) never
mixes their history, course, or teaching/reasoning mode, and creating or
messaging other chats in between has no effect. Within one chat, however,
**only one generation may be in flight at a time**: if a `send_message` for
a chat that already has a generation in progress arrives (from this or any
other connection), the server rejects it immediately with a `CHAT_BUSY`
error rather than letting two assistant replies race and append to that
chat's history in a nondeterministic order. `message_started` is still
sent first (the busy check happens once generation actually begins); retry
once the first generation's `message_completed`/`error` arrives. A
different chat id is entirely unaffected by another chat being busy.

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

This reuses `SessionService.send_streaming_to_chat()` (the explicit-by-id
layer added in Stage 5.8) — there is no second streaming implementation,
and no "activate this chat first" step. That means the existing Stage 2/3
guarantee carries through unchanged:

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

**~~Single active-chat cursor~~ — resolved in Stage 5.8.** Earlier versions
of this API switched a single mutable "active chat" (reused unchanged from
the CLI) to the requested `chat_id` before every write, which made two
different chat ids unsafe to interleave against one running server process
— creating a second chat before the first had ever been messaged could
silently evict the first's not-yet-persisted in-memory state and make it
404 afterward. `SessionService` now has a separate explicit-by-id layer
(`send_to_chat`, `rename_chat`, `set_teaching_mode_for_chat`, ...) that
every route and the WebSocket handler use instead: each call loads its
chat fresh from storage by id, with no cursor to evict, and `POST /chats`
persists immediately (see "Immediate persistence" above) so there is no
window where a chat exists only in one request's memory. The CLI keeps its
own active-chat cursor as a terminal-only convenience built on top of the
same explicit operations — nothing about its behavior changed.

**Per-chat generation exclusion, not true parallel inference.** Two
different chat ids are now safe to *interleave* (in any order, from any
number of connections) — but "safe" does not mean the actual model calls
run in true OS-level parallel, because of the next limitation below
(SQLite thread affinity): every call, for every chat, still funnels
through one dedicated worker thread, so a long-running generation for chat
A does temporarily delay a request for chat B that arrives while A's
current chunk is being produced, exactly as it would delay any other
request (a plain `GET`, say). What Stage 5.8 guarantees is *correctness*
under that serialization, not concurrency the underlying engine doesn't
have: chat B's state is never corrupted or mixed with chat A's regardless
of arrival order, and within a single chat, a second generation attempt
while one is already in flight gets `CHAT_BUSY` rather than racing it (see
"Concurrency and chat identity" above) — enforced by a lock per chat id,
not one process-wide lock.

**SQLite thread affinity.** `StudyBotApp` (and its one `sqlite3.Connection`)
is not designed to be touched from multiple threads. FastAPI dispatches
route handlers to a worker pool, so every call into `StudyBotApp` — the
constructor itself included — is routed through one dedicated
single-worker executor (`api/engine.py`) rather than left to land on
whatever thread FastAPI happens to pick. This was found and fixed during
Stage 5.7's own testing (`sqlite3.ProgrammingError: SQLite objects created
in a thread can only be used in that same thread`), not anticipated in
advance. Increasing the executor's worker count would need a thread-safe
connection strategy (e.g. one connection per worker, or a connection
pool) — out of scope here; the single-worker executor is a deliberate,
still-correct trade-off, not an oversight.

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
- The per-chat generation lock (`CHAT_BUSY`, Stage 5.8) never logs prompt
  or response content — only a chat id and lock/busy state are ever
  eligible for debug-level logging, never message content.
- Learning memory (Stage 6) topic/summary text is never logged, including
  when it's composed into a chat's system prompt — only a memory id, kind,
  course id, and status transition (e.g. active → archived) are ever
  eligible for debug-level logging (verified by test, including a memory
  actually injected into a real chat request).
