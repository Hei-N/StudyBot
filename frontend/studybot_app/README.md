# Study Bot (Flutter)

The Study Bot product UI — a Flutter desktop/mobile client for the
`studybot.api` server in the parent repository. Primary target is macOS;
Windows, iOS, and iPad are future targets. This app contains **no business
logic** of its own: courses, chats, teaching modes, and conversation
history all live behind the HTTP + WebSocket API documented in
[`../../API_CONTRACT.md`](../../API_CONTRACT.md), which this app treats as
the single source of truth for every data shape and protocol detail.

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
    modes/      Teaching-mode picker (backend catalog only)
    conversation/  Message list, streaming state machine, composer
    connection/ Setup screen, "engine unavailable" screen, connection state
    settings/   Theme picker, connection info, app info
    shell/      Adaptive four-breakpoint desktop/tablet/phone layout
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

## What this app deliberately does not do yet

Materials, notes, mastery tracking, progress, RAG/PDF ingestion, OCR,
vision, a study planner, calendar/LMS integration, Python auto-launch or
packaging, installers, accounts, and cloud sync are all out of scope for
this stage — none of it exists in the backend yet, so none of it is faked
here either.
