# Packaging the macOS app

`scripts/build_macos_app.sh` builds a self-contained `StudyBot.app`; `scripts/install_macos_app.sh` copies it to `~/Applications` (no sudo).

```bash
./scripts/build_macos_app.sh
./scripts/install_macos_app.sh
open ~/Applications/StudyBot.app
```

## What the build does

1. Creates `.build-venv/` and installs the project with the `build` extra (PyInstaller).
2. Packages the engine as a PyInstaller one-folder build from `studybot_backend.spec`. `backend_entry.py` only calls `studybot.api.__main__.main`, the same entry point as `python -m studybot.api`.
3. Smoke-tests that build in isolation (`smoke_test.py`: temp data dir, throwaway token, free port, health, auth, shutdown).
4. Runs `flutter build macos --release`.
5. Copies the engine to `StudyBot.app/Contents/Resources/studybot_backend/`.
6. Signs ad-hoc, nested code first, then the app with `Release.entitlements`.

The app locates the engine relative to its own executable (`Contents/Resources/studybot_backend/studybot-backend`), never through the repository or a system Python.

## Sandbox and signing

- The release app stays sandboxed. It has the network client entitlement and the network server entitlement; the latter lets the bundled engine listen on `127.0.0.1`.
- The engine is signed with `backend.entitlements` (`app-sandbox` + `inherit`), so it runs inside the app's sandbox. Because of that it cannot be launched directly from a shell; test the unsigned build in `build/macos/dist` instead (the build script does).
- Signing is ad-hoc for local use. The app is not notarized and not Developer ID signed.

## Data

The engine gets `STUDYBOT_DATA_DIR` from the app's Application Support directory (inside the sandbox container), so packaged data is separate from a development database. Nothing is migrated automatically.

## Requirements

Ollama must be installed and running with the model pulled (`ollama pull qwen3:4b`). Python and the venv are needed to build, not to run the installed app.
