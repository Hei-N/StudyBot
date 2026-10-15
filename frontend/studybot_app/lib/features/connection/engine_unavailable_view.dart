import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_spacing.dart';
import '../status/status_providers.dart';
import 'connection_setup_view.dart';

/// Shown when a connection is configured but the engine can't be reached
/// (stopped, restarting, wrong token). Offers Retry first and "Edit
/// connection" as a fallback, so a restart recovers with one tap; the poll in
/// [EngineHealthNotifier] also recovers on its own.
class EngineUnavailableView extends ConsumerWidget {
  const EngineUnavailableView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.cloud_off_outlined, size: 36, color: theme.colorScheme.onSurfaceVariant),
              const SizedBox(height: AppSpacing.md),
              Text('Engine unavailable', style: theme.textTheme.titleMedium),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'Study Bot can\'t reach the engine right now.',
                style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: AppSpacing.lg),
              FilledButton(
                onPressed: () => ref.read(engineHealthProvider.notifier).refresh(),
                child: const Text('Retry'),
              ),
              const SizedBox(height: AppSpacing.sm),
              TextButton(
                onPressed: () => Navigator.of(
                  context,
                ).push(MaterialPageRoute(builder: (_) => const ConnectionSetupView())),
                child: const Text('Edit connection…'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
