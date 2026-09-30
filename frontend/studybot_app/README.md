# Study Bot (Flutter)

The Study Bot product UI — a Flutter desktop/mobile client for the
`studybot.api` server in the parent repository. Primary target is macOS;
Windows, iOS, and iPad are future targets. This app contains **no business
logic** of its own: courses, chats, teaching modes, reasoning modes,
learning memory, and conversation history all live behind the HTTP +
WebSocket API documented in [`../../API_CONTRACT.md`](../../API_CONTRACT.md),
which this app treats as the single source of truth for every data shape
and protocol detail. Teaching mode and reasoning mode are independent
per-chat settings — the former (Teach/Homework/Quick/Practice/Exam) shapes
instructional behavior, the latter (Fast/Deep Think) controls the model's
inference-time "thinking" depth/latency, shown as two small pickers side by
side in the composer. Learning memory (Stage 6) is a third, separate
concept from either: durable, course-scoped learning facts ("needs review:
vector components") that persist independently of chat history, shown in
the Study Panel's compact summary, a dedicated management view (reachable
from the nav rail), and a "Save to Learning Memory" action on each
conversation message — never a mastery percentage.

## Running it

1. Start the Python engine from the repository root (see the main
   [README](../../README.md#running-the-api-server)):
   ```bash
   studybot-server
   ```
   It prints a base URL and bearer token to stdout — copy both.
2. Run the app:
   ```bash
   flutter pub get
   flutter run -d macos
   ```
3. On first launch, paste the base URL and token into the connection
   screen. They're saved locally (via `shared_preferences`) for next time —
   nothing is bundled or hardcoded, and the app never launches the Python
   process itself.

## Structure

```
lib/
  app/          MaterialApp + top-level routing (setup / unavailable / shell)
  core/
    api/        Typed HTTP client, WebSocket client, connection config, ApiException
    models/     DTOs mirroring API_CONTRACT.md exactly (Course, Chat, ChatMessage, ...)
    theme/      Design tokens (colors, spacing, radii, motion, breakpoints) + ThemeData
    widgets/    Small shared presentational widgets (empty/error/loading states, ...)
  features/
    courses/    Course list, create/edit/delete
    chats/      Chat list, rename/delete
    modes/      Teaching-mode and reasoning-mode pickers (backend catalogs only)
    memory/     Learning memory (Stage 6): providers, create/edit dialog,
                full management view (filter/archive/restore/delete)
    conversation/  Message list, streaming state machine, composer,
                    "Save to Learning Memory" per-message action
    connection/ Setup screen, "engine unavailable" screen, connection state
    settings/   Theme picker, connection info, app info
    shell/      Adaptive four-breakpoint desktop/tablet/phone layout,
                Study Panel's learning-memory summary
```

State management is Riverpod (`flutter_riverpod`); network/application
state lives in `core/api` and `features/*/*.providers.dart`, never inside
widgets. Widgets only render state and call notifier methods.

## Testing

```bash
flutter analyze
flutter test
```

Tests use hand-written fakes (`test/support/`) for `StudyBotApi` and
`ChatWebSocketClient` rather than real network calls — no test requires a
running Python server. Widget tests exercise the adaptive layout at all
four breakpoints headlessly (no real window needed).

**What automated tests can't confirm:** there is no graphical environment
in this project's automated-testing/CI setup, so no automated report ever
claims to have visually clicked through the real macOS app — only
`flutter analyze`/`flutter test` results, which check widget structure and
logic, not pixels. If you want to confirm the actual on-screen experience
yourself (worth doing after any Stage 6.x learning-memory change), here's
a short manual checklist:

1. Start a real backend (`studybot-server`, `STUDYBOT_MODEL_PROVIDER=
   ollama`) and run the app (`flutter run -d macos`).
2. Create a course, open a chat in it, and use the composer's **"Save to
   Learning Memory"** action on a real assistant reply — confirm the
   dialog opens pre-filled with that course and chat, pick a kind, save.
3. Confirm the new memory appears immediately in the **Study Panel**'s
   "Learning memory" section (grouped under its kind), with no manual
   refresh needed.
4. Open the full management view (nav rail → the brain/psychology icon)
   and confirm the same memory is listed; **edit** its topic and confirm
   both the management view and the Study Panel reflect the new topic
   after closing the dialog.
5. **Archive** it from the management view; confirm it disappears from
   the Study Panel's active summary and from the management view's
   default ("Active") filter, then switch that filter to "Archived" and
   confirm it's there with a **Restore** option.
6. **Restore** it; confirm it reappears in the Study Panel.
7. Delete the *course* that memory belongs to (not the memory itself) via
   the courses list; reopen the management view, switch to "Archived", and
   confirm the memory is still there, now archived and showing "General"
   as its course — never silently vanished, never left active.
8. **Delete** the memory itself (with confirmation) and confirm it's gone
   from every view.

## What this app deliberately does not do yet

Materials, notes, mastery tracking, progress, RAG/PDF ingestion, OCR,
vision, a study planner, calendar/LMS integration, Python auto-launch or
packaging, installers, accounts, and cloud sync are all out of scope for
this stage — none of it exists in the backend yet, so none of it is faked
here either.
