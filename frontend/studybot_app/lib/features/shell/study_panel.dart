import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/widgets/section_header.dart';
import '../../core/widgets/status_dot.dart';
import '../chats/chats_providers.dart';
import '../courses/courses_providers.dart';
import '../modes/modes_providers.dart';
import '../status/status_providers.dart';

/// The contextual right-hand panel: only real, already-available data —
/// current course, code/term, teaching mode, and engine status. No
/// mastery, key concepts, notes, or progress — none of that exists in the
/// backend yet (deliberately deferred past this stage).
class StudyPanel extends ConsumerWidget {
  const StudyPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final course = ref.watch(activeCourseProvider);
    final chat = ref.watch(activeChatProvider);
    final modesAsync = ref.watch(modeCatalogProvider);
    final healthAsync = ref.watch(engineHealthProvider);

    return Container(
      decoration: BoxDecoration(border: Border(left: BorderSide(color: theme.colorScheme.outlineVariant))),
      child: ListView(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        children: [
          const SectionHeader('Course'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: Text(course?.name ?? 'General', style: theme.textTheme.titleSmall),
          ),
          if (course?.subtitle != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
              child: Text(
                course!.subtitle!,
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ),
          const SizedBox(height: AppSpacing.md),
          const SectionHeader('Teaching mode'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: chat == null
                ? Text('No chat open', style: theme.textTheme.bodySmall)
                : modesAsync.when(
                    data: (modes) {
                      final mode = modes.where((m) => m.id == chat.teachingMode).firstOrNull;
                      return Text(mode?.displayName ?? chat.teachingMode, style: theme.textTheme.bodyMedium);
                    },
                    loading: () => const SizedBox(height: 16),
                    error: (_, _) => Text(chat.teachingMode, style: theme.textTheme.bodyMedium),
                  ),
          ),
          const SizedBox(height: AppSpacing.md),
          const SectionHeader('Engine'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: healthAsync.when(
              data: (health) => StatusDot(
                label: health.isHealthy ? 'Local · ${health.model}' : 'Engine unavailable',
                healthy: health.isHealthy,
              ),
              loading: () => const StatusDot(label: 'Checking…', healthy: false),
              error: (_, _) => const StatusDot(label: 'Engine unavailable', healthy: false),
            ),
          ),
        ],
      ),
    );
  }
}
