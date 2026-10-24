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

```bash
flutter pub get
flutter run -d macos      # or Run from VS Code
```

In a debug run on macOS the app starts the engine itself, from the repository's
`.venv` (create it as described in the main [README](../../README.md#setup)).
It finds the repository by walking up from the built app, or from
`STUDYBOT_REPO_ROOT`. It generates a private token, picks a free port, waits
for the health check and connects, so there is nothing to type. The engine uses
the Ollama model provider unless `STUDYBOT_MODEL_PROVIDER` is set. When the app
closes, however it ends, the engine it started exits too; Ollama is never
started or stopped. If the engine can't start, the screen says why and offers
"Try again" and "Connect manually…".

To use a hand-started engine instead (see the main
[README](../../README.md#api-server)), run with
`--dart-define=STUDYBOT_AUTOSTART=false` and enter its base URL and token on the
connection screen; they are saved with `shared_preferences`.

### Sandbox settings

| Build | App Sandbox | Why |
|---|---|---|
| Debug / Profile (`DebugProfile.entitlements`) | **disabled** | A sandboxed app can't launch the repo-local Python engine. Development only. |
| Release (`Release.entitlements`) | **enabled** | Adds only the network server entitlement so the bundled engine can listen on loopback. |

The packaged app bundles its own engine and does not use this exception; see
[packaging/macos/README.md](../../packaging/macos/README.md). The launcher
prefers the bundled engine and only falls back to the repository `.venv` in
non-release builds.

## Ollama startup

`lib/core/ollama/ollama_lifecycle.dart` checks Ollama and, if it is down, opens the Ollama
desktop app once through LaunchServices (`macos/Runner/OllamaLauncher.swift`, channel
`studybot/ollama_launcher`, no entitlements needed) with the app's own `hidden` argument.
Polling is bounded, concurrent checks share one launch, and Ollama is never stopped.
`--dart-define=STUDYBOT_AUTOSTART=false` turns this off together with the engine autostart.

## Message rendering

Assistant messages render as GitHub-flavored Markdown with LaTeX math
(`lib/features/conversation/studybot_markdown.dart`, using `flutter_markdown_plus`
and `flutter_math_fork`). Supported math: `$...$` and `\(...\)` inline,
`$$...$$` and `\[...\]` display. Rendering is display-only; stored message text
is never changed.

- Code spans and fences stay literal.
- Currency (`$5`, `$5 or $10`) stays text: a `$` pair only becomes math when the
  closing `$` is not followed by a letter or digit.
- Incomplete (still streaming) or invalid math shows its source text, never an
  error. A display block is recognised only once its closing delimiter arrives.
- Wide display equations and matrices scroll horizontally.
- Limitation: rendered equations are not part of the text selection range.

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
study planner, calendar/LMS integration, a packaged (bundled-Python)
build, installers, accounts and cloud sync. None of it exists in the backend yet, so
none of it is faked here.
