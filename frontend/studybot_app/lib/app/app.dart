import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/theme/app_theme.dart';
import '../features/connection/connection_providers.dart';
import '../features/connection/connection_setup_view.dart';
import '../features/connection/engine_starting_view.dart';
import '../features/connection/managed_backend.dart';
import '../features/connection/ollama_startup.dart';
import '../features/connection/engine_unavailable_view.dart';
import '../features/settings/theme_providers.dart';
import '../features/shell/app_shell.dart';
import '../features/status/status_providers.dart';

class StudyBotApp extends ConsumerWidget {
  const StudyBotApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themeMode = ref.watch(themeModeProvider);
    return MaterialApp(
      title: 'Study Bot',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: themeMode,
      home: const AppGate(),
    );
  }
}

/// Routes between the setup screen, an "engine unavailable" screen, and the
/// real app shell based on whether a connection is configured and whether
/// the engine actually answers — never shows the product UI against a
/// backend that isn't there.
class AppGate extends ConsumerWidget {
  const AppGate({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Started together with the engine so Ollama warms up while the engine starts.
    final ollama = ref.watch(ollamaStartupProvider);
    if (ref.watch(managedBackendEnabledProvider)) {
      final backend = ref.watch(managedBackendProvider);
      if (backend.isLoading) return const EngineStartingView();
      if (backend.hasError) return EngineStartingView(error: backend.error);
    }

    final config = ref.watch(connectionConfigProvider);
    if (!config.isConfigured) {
      return const ConnectionSetupView();
    }

    // Make sure Ollama is answering before the engine is judged unavailable.
    if (ollama.isLoading) {
      return const EngineStartingView(message: 'Starting Ollama…', offerLibrary: true);
    }

    final health = ref.watch(engineHealthProvider);
    return health.when(
      data: (h) => h.isHealthy ? const AppShell() : const EngineUnavailableView(),
      loading: () => const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (_, _) => const EngineUnavailableView(),
    );
  }
}
