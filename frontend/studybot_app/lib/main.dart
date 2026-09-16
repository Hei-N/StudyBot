import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';

void main() {
  runApp(
    ProviderScope(
      // Riverpod 3's default provider `build()` retries silently on
      // failure (exponential backoff, up to ~10 attempts) before
      // surfacing an error — that fights the explicit "Retry" buttons and
      // predictable connecting/unavailable states this app already
      // provides, so it's disabled in favor of that explicit UX.
      retry: (_, _) => null,
      child: const StudyBotApp(),
    ),
  );
}
