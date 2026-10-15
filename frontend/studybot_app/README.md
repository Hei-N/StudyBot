# StudyBot (Flutter)

A Flutter desktop/mobile client for the `studybot.api` server in the parent
repository. macOS is the primary target; Windows, iOS and iPad are future
targets.

The app contains **no business logic**. Courses, chats, teaching modes,
reasoning modes, learning memory and conversation history all live behind the
HTTP and WebSocket API described in [`../../API_CONTRACT.md`](../../API_CONTRACT.md),
which is the single source of truth for every data shape and protocol detail.

Three separate concepts appear in the UI:

- **Teaching mode** (Teach, Homework, Quick Answer, Practice, Exam) shapes how
  the assistant instructs.
- **Reasoning mode** (Fast, Deep Think) controls the model's thinking depth and
  latency. It is shown next to the teaching mode as a second small picker in the
  composer.
- **Learning memory** is durable, course-scoped learning facts ("needs review:
  vector components") kept independently of chat history. It appears in the
  Study Panel summary, in a management view reachable from the nav rail, and as
  a "Save to Learning Memory" action on each message. There are no mastery
  percentages.

## Running it

1. Start the Python engine from the repository root (see the main
   [README](../../README.md#api-server)):
   ```bash
   studybot-server
   ```
   It prints a base URL and a bearer token; copy both.
2. Run the app:
   ```bash
   flutter pub get
   flutter run -d macos
   ```
3. On first launch, enter the base URL and token on the connection screen. They
   are saved locally with `shared_preferences`. Nothing is bundled or hardcoded,
   and the app never starts the Python process itself.

## Structure

```
lib/
  app/          MaterialApp and top-level routing (setup / unavailable / shell)
  core/
    api/        Typed HTTP client, WebSocket client, connection config, ApiException
    models/     DTOs mirroring API_CONTRACT.md (Course, Chat, ChatMessage, ...)
    theme/      Design tokens (colors, spacing, radii, motion, breakpoints) and ThemeData
    widgets/    Shared presentational widgets (empty, error and loading states)
  features/
    courses/        Course list, create/edit/delete
    chats/          Chat list, rename/delete
    modes/          Teaching-mode and reasoning-mode pickers (backend catalogs)
    memory/         Learning memory providers, create/edit dialog, management view
    conversation/   Message list, streaming state, composer, "Save to Learning Memory"
    connection/     Setup screen, "engine unavailable" screen, connection state
    settings/       Theme picker, connection info, app info
    shell/          Adaptive desktop/tablet/phone layout and the Study Panel
```

State management is Riverpod. Network and application state live in `core/api`
and `features/*/*_providers.dart`, never in widgets; widgets render state and
call notifier methods.

## Testing

```bash
flutter analyze
flutter test
```

Tests use hand-written fakes (`test/support/`) for `StudyBotApi` and
`ChatWebSocketClient`, so none needs a running Python server. Widget tests
exercise the adaptive layout at all four breakpoints headlessly.

Automated tests check widget structure and logic, not pixels. For a quick
on-screen check against a real backend (`studybot-server` with
`STUDYBOT_MODEL_PROVIDER=ollama`, then `flutter run -d macos`):

1. **Replies are clean.** In a course chat set to Practice and Fast, send
   `help me to work practice quizzes`, then `ok`. Replies should read as direct
   answers, with no planning text and no `</think>`. Repeat in Deep Think (a
   typing indicator shows while the model reasons), and try each teaching mode.
   If a reply cannot be separated safely, its partial text disappears, an error
   banner appears, and only your message stays in the chat.
2. **Learning memory.** Use "Save to Learning Memory" on an assistant reply; the
   dialog should be pre-filled with that course and chat. After saving, the
   memory should appear in the Study Panel and the management view (nav rail,
   brain icon). Edit its topic; both views should update.
3. **Archive and restore.** Archive the memory: it leaves the Study Panel and the
   default "Active" filter and appears under "Archived" with a Restore option.
   Restore it and confirm it returns.
4. **Course deletion.** Delete the memory's course. The memory should remain,
   archived and shown under "General", rather than vanishing or staying active.
5. **Delete.** Delete the memory (with confirmation) and confirm it is gone from
   every view.

Old replies saved before reasoning was filtered may still show leaked reasoning
(see "Reasoning modes" in the main README); new replies in the same chat should
be clean.

## Not implemented

Materials, notes, mastery tracking, progress, RAG/PDF ingestion, OCR, vision, a
study planner, calendar/LMS integration, Python auto-launch or packaging,
installers, accounts and cloud sync. None of it exists in the backend yet, so
none of it is faked here.
