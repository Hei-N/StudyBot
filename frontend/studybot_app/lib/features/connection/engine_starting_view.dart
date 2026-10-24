import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_spacing.dart';
import '../library/library_view.dart';
import 'connection_setup_view.dart';
import 'managed_backend.dart';

/// Shown while the app starts its own engine, or when that failed.
class EngineStartingView extends ConsumerWidget {
  const EngineStartingView({super.key, this.error, this.message, this.offerLibrary = false});

  final Object? error;

  /// Replaces the default "Starting Study Bot…" line while waiting on something else (Ollama).
  final String? message;

  /// Shows a shortcut to the Study Library, which works without Ollama.
  final bool offerLibrary;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final failed = error != null;
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (failed)
                Icon(Icons.error_outline, size: 36, color: theme.colorScheme.error)
              else
                const CircularProgressIndicator(),
              const SizedBox(height: AppSpacing.md),
              Text(
                failed ? 'Could not start the engine' : (message ?? 'Starting Study Bot…'),
                style: theme.textTheme.titleMedium,
              ),
              if (offerLibrary && !failed) ...[
                const SizedBox(height: AppSpacing.md),
                OutlinedButton(
                  onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const LibraryView())),
                  child: const Text('Open Study Library'),
                ),
              ],
              if (failed) ...[
                const SizedBox(height: AppSpacing.xs),
                Text(
                  '$error',
                  style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: AppSpacing.lg),
                FilledButton(onPressed: () => ref.invalidate(managedBackendProvider), child: const Text('Try again')),
                const SizedBox(height: AppSpacing.sm),
                TextButton(
                  onPressed: () =>
                      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ConnectionSetupView())),
                  child: const Text('Connect manually…'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
