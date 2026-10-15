#!/bin/bash
# Installs the built StudyBot.app to ~/Applications (no sudo), replacing only an
# existing StudyBot.app at that exact path.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/frontend/studybot_app/build/macos/Build/Products/Release/StudyBot.app"
TARGET_DIR="${STUDYBOT_INSTALL_DIR:-$HOME/Applications}"
TARGET="$TARGET_DIR/StudyBot.app"

[ -d "$SOURCE" ] || { echo "Build first: ./scripts/build_macos_app.sh" >&2; exit 1; }
[ "$(basename "$TARGET")" = "StudyBot.app" ] || { echo "Refusing unexpected target: $TARGET" >&2; exit 1; }

mkdir -p "$TARGET_DIR"
[ -d "$TARGET" ] && rm -rf "$TARGET"
ditto "$SOURCE" "$TARGET"
codesign --verify --strict "$TARGET"
echo "Installed: $TARGET"
