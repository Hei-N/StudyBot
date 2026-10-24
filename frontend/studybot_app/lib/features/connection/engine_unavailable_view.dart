import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_spacing.dart';
import '../status/status_providers.dart';
import '../../core/ollama/ollama_lifecycle.dart';
import '../library/library_view.dart';
import 'connection_setup_view.dart';
import 'ollama_startup.dart';

/// Shown when a connection is configured but the engine can't be reached
/// (stopped, restarting, wrong token). Offers Retry first and "Edit
/// connection" as a fallback, so a restart recovers with one tap; the poll in
/// [EngineHealthNotifier] also recovers on its own.
class EngineUnavailableView extends ConsumerWidget {
  const EngineUnavailableView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final health = ref.watch(engineHealthProvider).value;
    final modelServerDown = health != null && health.providerReachable == false;
    final startup = ref.watch(ollamaStartupProvider).value;
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.cloud_off_outlined, size: 36, color: theme.colorScheme.onSurfaceVariant),
              const SizedBox(height: AppSpacing.md),
              Text(
                modelServerDown ? 'Ollama is not running' : 'Engine unavailable',
                style: theme.textTheme.titleMedium,
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                modelServerDown ? _ollamaMessage(startup) : 'Study Bot can\'t reach the engine right now.',
                style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: AppSpacing.lg),
              FilledButton(
                onPressed: () => modelServerDown
                    ? ref.read(ollamaStartupProvider.notifier).retry()
                    : ref.read(engineHealthProvider.notifier).refresh(),
                child: const Text('Retry'),
              ),
              if (modelServerDown) ...[
                // The engine is up; only answering questions needs Ollama, so the library stays usable.
                const SizedBox(height: AppSpacing.sm),
                OutlinedButton(
                  onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const LibraryView())),
                  child: const Text('Open Study Library'),
                ),
              ],
              const SizedBox(height: AppSpacing.sm),
              TextButton(
                onPressed: () =>
                    Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ConnectionSetupView())),
                child: const Text('Edit connection…'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

String _ollamaMessage(OllamaStartup? startup) => switch (startup) {
  OllamaStartup.notInstalled => "Study Bot couldn't find the Ollama app. Install it from ollama.com, then tap Retry.",
  OllamaStartup.launchFailed ||
  OllamaStartup.timedOut => "Study Bot couldn't start Ollama. Open Ollama yourself, then tap Retry.",
  _ => 'Start Ollama, then tap Retry. Study Bot needs it to answer.',
};
