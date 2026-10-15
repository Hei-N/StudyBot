#!/bin/bash
# Builds a self-contained StudyBot.app: the PyInstaller engine plus the Flutter
# macOS release build, ad-hoc signed for local use (not notarized).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
grep -q '^name = "studybot"' pyproject.toml || { echo "Run from the StudyBot repository." >&2; exit 1; }

APP_DIR="$ROOT/frontend/studybot_app"
BUILD="$ROOT/build/macos"
BUILD_VENV="$ROOT/.build-venv"
ENTITLEMENTS_APP="$APP_DIR/macos/Runner/Release.entitlements"
ENTITLEMENTS_BACKEND="$ROOT/packaging/macos/backend.entitlements"

[ "$(uname)" = "Darwin" ] || { echo "macOS only." >&2; exit 1; }
command -v flutter >/dev/null || { echo "flutter not found on PATH." >&2; exit 1; }
PYTHON="${STUDYBOT_BUILD_PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { echo "$PYTHON not found." >&2; exit 1; }

echo "==> Build environment ($("$PYTHON" --version))"
[ -x "$BUILD_VENV/bin/python" ] || "$PYTHON" -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/python" -m pip install --quiet --upgrade pip
"$BUILD_VENV/bin/python" -m pip install --quiet ".[build]"
"$BUILD_VENV/bin/python" -m pip install --quiet --force-reinstall --no-deps .

echo "==> Packaging the engine"
rm -rf "$BUILD/dist" "$BUILD/work"
mkdir -p "$BUILD"
"$BUILD_VENV/bin/python" -m PyInstaller --noconfirm --clean \
    --distpath "$BUILD/dist" --workpath "$BUILD/work" \
    "$ROOT/packaging/macos/studybot_backend.spec" >"$BUILD/pyinstaller.log" 2>&1 \
    || { tail -30 "$BUILD/pyinstaller.log" >&2; exit 1; }
[ -x "$BUILD/dist/studybot_backend/studybot-backend" ] || { echo "Engine build failed." >&2; exit 1; }

echo "==> Smoke-testing the packaged engine"
"$BUILD_VENV/bin/python" "$ROOT/packaging/macos/smoke_test.py" "$BUILD/dist/studybot_backend/studybot-backend"

echo "==> Building the Flutter release app"
(cd "$APP_DIR" && flutter pub get >/dev/null && flutter build macos --release)
APP="$(find "$APP_DIR/build/macos/Build/Products/Release" -maxdepth 1 -name 'StudyBot.app' -type d | head -1)"
[ -n "$APP" ] || { echo "StudyBot.app not found in the Flutter output." >&2; exit 1; }

echo "==> Embedding the engine"
BACKEND_HOME="$APP/Contents/Resources"
rm -rf "$APP/Contents/Helpers" "$BACKEND_HOME/studybot_backend"
mkdir -p "$BACKEND_HOME"
ditto "$BUILD/dist/studybot_backend" "$BACKEND_HOME/studybot_backend"
chmod +x "$BACKEND_HOME/studybot_backend/studybot-backend"
# codesign rejects *.dist-info folders inside an app as malformed bundles; the engine runs without them.
find "$BACKEND_HOME/studybot_backend" -name '*.dist-info' -type d -prune -exec rm -rf {} +

echo "==> Signing (ad-hoc, nested code first)"
while IFS= read -r -d '' file; do
    if file -b "$file" | grep -q 'Mach-O' && [ "$file" != "$BACKEND_HOME/studybot_backend/studybot-backend" ]; then
        codesign --force --sign - --timestamp=none "$file"
    fi
done < <(find "$BACKEND_HOME/studybot_backend" -type f -print0)
codesign --force --sign - --timestamp=none --entitlements "$ENTITLEMENTS_BACKEND" \
    "$BACKEND_HOME/studybot_backend/studybot-backend"
codesign --force --sign - --timestamp=none --entitlements "$ENTITLEMENTS_APP" "$APP"

echo "==> Verifying"
codesign --verify --strict --verbose=2 "$APP"
codesign --verify --strict --verbose=2 "$BACKEND_HOME/studybot_backend/studybot-backend"
[ -x "$APP/Contents/MacOS/StudyBot" ] || { echo "App executable missing." >&2; exit 1; }
[ ! -e "$APP/Contents/Resources/studybot_backend/.venv" ] && ! find "$APP" -name '.venv' -maxdepth 6 | grep -q . \
    || { echo "A .venv ended up inside the app." >&2; exit 1; }

echo
echo "Built: $APP"
