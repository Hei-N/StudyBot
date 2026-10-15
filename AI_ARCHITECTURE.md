# StudyBot AI architecture

This describes the AI boundary as it exists today. Where something is
deliberately missing, it says so.

## 1. Purpose

StudyBot is a study application and should not need to change when the model
underneath it does: a different local model today, a hosted or custom
fine-tuned model later. One small, stable interface, `ModelProvider`
(`src/studybot/models/base.py`), is the contract between the two.

## 2. Current boundary

```
StudyBot domain
  CourseService · SessionService · LearningMemoryService · teaching modes
        │
        │  builds the system prompt, restores history, picks reasoning mode,
        │  hands over already-built Message sequences
        ▼
ChatService ──► ModelProvider  (the AI boundary)
                    │
                    ├── MockModel      deterministic, for tests/development
                    └── OllamaModel    the only module that knows Ollama
```

`ModelProvider` has four members:

| Member | Meaning |
|---|---|
| `generate(messages, *, reasoning_mode)` | a complete answer |
| `stream(messages, *, reasoning_mode)` | the answer incrementally; `""` is a progress signal, never content |
| `get_status()` | is the backend reachable, is the model present |
| `get_capabilities()` | what the *model* reports it can do (`ModelCapabilities`) |

`models/factory.py` turns configuration into a provider and nothing more. It
has no routing, scoring or model whitelist; any Ollama tag works.

### Model capabilities

`ModelCapabilities` is `supports_vision`, `supports_tools`, `supports_thinking`,
`reasoning_modes_distinct`, `context_window`. Each flag is `True` (the provider
positively reports it), `False` (it positively reports the lack) or `None`
(couldn't be determined). They are discovered at runtime from Ollama's local
`/api/show` metadata (never from a model's name), fetched lazily, cached only
on success, and retried after a failure.

They describe the **model**, not StudyBot. `supports_vision=True` means the
model can accept images; it does *not* mean StudyBot's text-only `Message` can
carry one today. Nothing in the application changes behavior because of these
values yet.

`reasoning_modes_distinct` is whether Fast and Deep genuinely differ. For an
always-thinking model both modes must request reasoning (so the reasoning can
be separated from the answer), so it is `False`; for a model whose thinking can
be switched off it is `True`.

### Generation budgets

Every model request is bounded. `models/generation.py` defines two small,
provider-neutral value types: `GenerationBudget` (a token cap and a total
deadline) and `GenerationBudgetPolicy` (one budget for Fast, one for Deep).
The policy is chosen by **reasoning mode only** (never by model, course or
teaching mode) and is built once from `Settings` by the factory.

| Mode | Max generated tokens | Total deadline |
|---|---|---|
| Fast | 4096 | 120 s |
| Deep | 6144 | 300 s |

* **Token cap.** `max_generated_tokens` is the *total* the model may generate
  for the request; for a thinking model that includes hidden reasoning, not
  just the visible answer. `OllamaModel` sends it as `num_predict`. It does not
  touch `num_ctx` (the active context window is a separate server setting).
  If the model stops because it hit the cap (`done_reason == "length"`) the
  generation fails with `GenerationTokenLimitExceededError`, even if some text
  was already produced: a silently truncated answer is never saved as a
  successful reply. A model that spends its whole allowance reasoning is
  reported the same way (not as an "empty answer").
* **Deadline.** A *total* wall-clock limit for the provider call (reasoning,
  answer and streaming together), measured with an injectable monotonic clock.
  Receiving tokens or `""` progress signals does not extend it. It is checked
  before each received chunk is processed and again before anything becomes
  visible, and raises `GenerationDeadlineExceededError`.
* **One path.** `generate()` consumes the same internal stream as `stream()`,
  so budget, deadline, reasoning filter and `done_reason` handling cannot drift
  apart. The underlying stream is always closed (safely, tolerating iterators
  with no `close()`), which also makes Ollama stop generating.
* **Failure behaviour.** Both errors are ordinary `ModelError`s: the API sends
  the existing `MODEL_ERROR`, never `message_completed`; only the user's message
  is persisted; the chat's lock is released and the engine stays responsive, so
  the same or another chat works immediately. Text streamed before the failure
  is for the client to discard (the Flutter app already does). Logs carry only
  numbers and enums (model, mode, kind, limits, elapsed ms, character and chunk
  counts), never prompt, answer or reasoning text.
* **Limitation.** The deadline can only be checked when the client iterator
  hands control back. If a network call blocks without yielding anything, the
  lower-level HTTP timeout (`STUDYBOT_OLLAMA_TIMEOUT`) is the protection; no
  extra thread is used to kill it.

These are safety limits, not quality settings. There is no user-facing Stop
button yet.

## 3. What belongs in StudyBot

Courses, teaching modes (Teach / Homework / Quick / Practice / Exam), learning
memory, and later RAG, flashcards, mastery and study planning. These decide
*what the model is asked*. They live above the boundary and must not leak into
it.

## 4. What belongs in reusable AI infrastructure

Everything below the boundary should be usable by an application that has never
heard of a course:

- model construction (`models/factory.py`)
- generation and streaming
- capability discovery
- reasoning controls (the Fast/Deep → provider setting mapping, inside
  `OllamaModel` only)
- output integrity (`core/output_integrity.py`: hidden reasoning never leaves a
  provider; unsafe output fails closed)
- provider health

`core/output_integrity.py` and `ChatService` currently live under `core/`; they
know nothing about courses or teaching modes.

## 5. Current providers

- **MockModel**: echoes the last user message. All capabilities `False`/`None`.
- **OllamaModel**: talks to a local Ollama server. The only production module
  that imports `ollama`, reads `/api/show`, sends `think`, or interprets an
  Ollama error. Every response (streamed or not) goes through the reasoning
  output filter.

## 6. Future providers

A hosted-model provider or a custom fine-tuned model would be another
`ModelProvider` implementation (or simply another Ollama tag). It would need to
return only user-visible answer text, raise `ModelError` on failure, and report
capabilities honestly. Nothing above the boundary should need to change.

## 7. Why the AI layer is not a separate server yet

There is one consumer, StudyBot. A separate process would add deployment,
authentication, versioning and a network hop to solve a reuse problem that does
not exist yet. The boundary is clean enough that extraction would be mechanical.

## 8. Extraction trigger

Move the AI layer into its own service/repository when a **second real
application** needs to consume it, or when it must be deployed independently
(for example a model server on different hardware).

## 9. Current limitations

- **Text-only `Message` contract.** No image or other media can be sent.
- **One configured provider per process** (`STUDYBOT_OLLAMA_MODEL`). No router,
  no per-chat model, no fallback chain.
- **No tool loop.** Tool support may be reported by a model; StudyBot does not
  use it.
- **No multimodal request path.**
- **A single engine thread** serves the API; long reasoning relies on the
  progress-signal convention to keep other requests responsive.
- **Context window.** `context_window` is what the model advertises. The
  context Ollama actually uses is a smaller, separate server setting (check
  `ollama ps`); on an 8 GB machine do not raise it casually.
- The core package still contains the AI-agnostic pieces named in section 4;
  they have not been physically separated.

## 10. Non-negotiable invariants

1. A model provider never receives `Course` objects or any StudyBot domain
   object, only `Message` sequences.
2. A model provider never accesses SQLite.
3. Flutter never parses model-specific output.
4. Hidden reasoning never crosses `ModelProvider`; output that can't be
   separated from reasoning fails closed.
5. StudyBot context (course, teaching mode, learning memory) is prepared before
   inference, in the system prompt.
6. Replacing a model must not require changes to the education engine.
7. No provider-specific behavior (Ollama types, `think`, `/api/show`) exists
   outside `models/ollama.py`.
8. All candidate models receive the same StudyBot prompts; per-model prompt
   tuning is not allowed.
9. Generation budgets depend only on the reasoning mode, never on the model.
