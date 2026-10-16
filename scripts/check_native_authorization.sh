#!/bin/bash
# Compiles the native authorization logic with standalone checks and runs them.
# These run outside the app sandbox, so they test logic (containment, staging,
# leases), not sandbox behavior.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NATIVE="$ROOT/frontend/studybot_app/macos"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

for check in lease staging; do
    swiftc -o "$WORK/$check" "$NATIVE/Runner/LibraryAuthorization.swift" "$NATIVE/NativeChecks/$check/main.swift"
    echo "== $check"
    "$WORK/$check"
done
