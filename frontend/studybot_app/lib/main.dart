import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';
import 'features/connection/managed_backend.dart';

/// Debug runs on macOS start the engine from the repository's `.venv`.
/// Disable with `--dart-define=STUDYBOT_AUTOSTART=false`.
const _autostart = bool.fromEnvironment('STUDYBOT_AUTOSTART', defaultValue: true);

void main() {
  runApp(
    ProviderScope(
      // Riverpod 3 silently retries a failing provider build (exponential backoff,
      // ~10 attempts), which fights the app's explicit "Retry" buttons and
      // connecting/unavailable states, so it is disabled.
      retry: (_, _) => null,
      overrides: [managedBackendEnabledProvider.overrideWithValue(kDebugMode && _autostart && Platform.isMacOS)],
      child: const StudyBotApp(),
    ),
  );
}
