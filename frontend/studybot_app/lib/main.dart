import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';

void main() {
  runApp(
    ProviderScope(
      // Riverpod 3 silently retries a failing provider build (exponential backoff,
      // ~10 attempts), which fights the app's explicit "Retry" buttons and
      // connecting/unavailable states, so it is disabled.
      retry: (_, _) => null,
      child: const StudyBotApp(),
    ),
  );
}
