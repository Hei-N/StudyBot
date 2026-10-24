import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/ollama/ollama_lifecycle.dart';
import '../../core/platform/ollama_launcher.dart';
import '../status/status_providers.dart';

/// Whether this run starts Ollama itself when it is down. Off by default (and in tests);
/// `main.dart` turns it on for the macOS app.
final ollamaAutostartEnabledProvider = Provider<bool>((ref) => false);

final ollamaLifecycleProvider = Provider<OllamaLifecycle>(
  (ref) => OllamaLifecycle(
    launcher: MacOSOllamaLauncher(),
    host: Platform.environment['STUDYBOT_OLLAMA_HOST'] ?? OllamaLifecycle.defaultHost,
  ),
);

/// The result of the Ollama check made when the app starts, and again on Retry.
class OllamaStartupNotifier extends AsyncNotifier<OllamaStartup?> {
  @override
  Future<OllamaStartup?> build() async {
    if (!ref.watch(ollamaAutostartEnabledProvider)) return null;
    return ref.read(ollamaLifecycleProvider).ensureRunning();
  }

  /// Tries again (launching Ollama once more if it is still down), then refreshes health.
  Future<void> retry() async {
    if (!ref.read(ollamaAutostartEnabledProvider)) return;
    state = const AsyncLoading();
    state = await AsyncValue.guard(() => ref.read(ollamaLifecycleProvider).ensureRunning());
    await ref.read(engineHealthProvider.notifier).refresh();
  }
}

final ollamaStartupProvider = AsyncNotifierProvider<OllamaStartupNotifier, OllamaStartup?>(OllamaStartupNotifier.new);
