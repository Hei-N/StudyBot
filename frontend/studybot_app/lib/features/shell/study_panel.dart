import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/widgets/section_header.dart';
import '../../core/widgets/status_dot.dart';
import '../chats/chats_providers.dart';
import '../courses/courses_providers.dart';
import '../memory/memory_management_view.dart';
import '../memory/memory_providers.dart';
import '../modes/modes_providers.dart';
import '../modes/reasoning_providers.dart';
import '../status/status_providers.dart';

/// The right-hand panel: current course, code/term, teaching mode, reasoning
/// mode, a compact learning-memory summary, and engine status.
class StudyPanel extends ConsumerWidget {
  const StudyPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final course = ref.watch(activeCourseProvider);
    final chat = ref.watch(activeChatProvider);
    final modesAsync = ref.watch(modeCatalogProvider);
    final reasoningModesAsync = ref.watch(reasoningModeCatalogProvider);
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
          const SectionHeader('Reasoning mode'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: chat == null
                ? Text('No chat open', style: theme.textTheme.bodySmall)
                : reasoningModesAsync.when(
                    data: (modes) {
                      final mode = modes.where((m) => m.id == chat.reasoningMode).firstOrNull;
                      return Text(mode?.displayName ?? chat.reasoningMode, style: theme.textTheme.bodyMedium);
                    },
                    loading: () => const SizedBox(height: 16),
                    error: (_, _) => Text(chat.reasoningMode, style: theme.textTheme.bodyMedium),
                  ),
          ),
          const SizedBox(height: AppSpacing.md),
          const _LearningMemorySection(),
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

/// A compact summary of the active course's active learning memories
/// (course-specific plus global), grouped by kind ("Needs review",
/// "Understands", ...) and showing topics only. Empty groups are hidden.
/// "View all" opens the full management view.
class _LearningMemorySection extends ConsumerWidget {
  const _LearningMemorySection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final memories = ref.watch(activeCourseMemoriesProvider);
    final kindsAsync = ref.watch(memoryKindCatalogProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(
          'Learning memory',
          trailing: TextButton(
            style: TextButton.styleFrom(padding: EdgeInsets.zero, minimumSize: const Size(0, 0)),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const MemoryManagementView())),
            child: const Text('View all'),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
          child: memories.isEmpty
              ? Text(
                  'No learning memory yet for this course.',
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                )
              : kindsAsync.when(
                  loading: () => const SizedBox(height: 16),
                  error: (_, _) => const SizedBox.shrink(),
                  data: (kinds) {
                    final order = [for (final k in kinds) k.id];
                    final byKind = <String, List<String>>{};
                    for (final memory in memories) {
                      (byKind[memory.kind] ??= []).add(memory.topic);
                    }
                    final kindLabel = {for (final k in kinds) k.id: k.displayName};

                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (final kindId in order)
                          if (byKind[kindId] case final topics? when topics.isNotEmpty)
                            Padding(
                              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    kindLabel[kindId] ?? kindId,
                                    style: theme.textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w600),
                                  ),
                                  for (final topic in topics)
                                    Padding(
                                      padding: const EdgeInsets.only(left: AppSpacing.xs),
                                      child: Text('•  $topic', style: theme.textTheme.bodySmall),
                                    ),
                                ],
                              ),
                            ),
                      ],
                    );
                  },
                ),
        ),
      ],
    );
  }
}
