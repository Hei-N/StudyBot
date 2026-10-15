import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/learning_memory.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/confirm_dialog.dart';
import '../../core/widgets/empty_state.dart';
import '../../core/widgets/error_view.dart';
import '../../core/widgets/loading_view.dart';
import '../courses/courses_providers.dart';
import 'memory_edit_dialog.dart';
import 'memory_providers.dart';

const _statusAll = '__all__';
const _kindAll = '__all__';
const _courseAll = '__all__';
const _courseGeneral = '__general__';

/// Full-page learning-memory management: filter by course/kind/status, create,
/// edit, archive/restore and delete. Reachable from the nav rail at every
/// breakpoint and via "View all" in the Study Panel summary. Uses plain-language
/// wording (no raw enum ids).
class MemoryManagementView extends ConsumerStatefulWidget {
  const MemoryManagementView({super.key});

  @override
  ConsumerState<MemoryManagementView> createState() => _MemoryManagementViewState();
}

class _MemoryManagementViewState extends ConsumerState<MemoryManagementView> {
  String _courseFilter = _courseAll;
  String _kindFilter = _kindAll;
  String _statusFilter = 'active';

  @override
  Widget build(BuildContext context) {
    final memoriesAsync = ref.watch(memoriesProvider);
    final kindsAsync = ref.watch(memoryKindCatalogProvider);
    final coursesAsync = ref.watch(coursesProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Learning memory'),
        actions: [
          IconButton(
            tooltip: 'New memory',
            icon: const Icon(Icons.add),
            onPressed: () => showMemoryEditDialog(context),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                coursesAsync.when(
                  loading: () => const SizedBox.shrink(),
                  error: (_, _) => const SizedBox.shrink(),
                  data: (courses) => DropdownButton<String>(
                    value: _courseFilter,
                    items: [
                      const DropdownMenuItem(value: _courseAll, child: Text('All courses')),
                      const DropdownMenuItem(value: _courseGeneral, child: Text('General only')),
                      for (final course in courses) DropdownMenuItem(value: course.id, child: Text(course.name)),
                    ],
                    onChanged: (value) => setState(() => _courseFilter = value ?? _courseAll),
                  ),
                ),
                kindsAsync.when(
                  loading: () => const SizedBox.shrink(),
                  error: (_, _) => const SizedBox.shrink(),
                  data: (kinds) => DropdownButton<String>(
                    value: _kindFilter,
                    items: [
                      const DropdownMenuItem(value: _kindAll, child: Text('All kinds')),
                      for (final kind in kinds) DropdownMenuItem(value: kind.id, child: Text(kind.displayName)),
                    ],
                    onChanged: (value) => setState(() => _kindFilter = value ?? _kindAll),
                  ),
                ),
                DropdownButton<String>(
                  value: _statusFilter,
                  items: const [
                    DropdownMenuItem(value: 'active', child: Text('Active')),
                    DropdownMenuItem(value: 'archived', child: Text('Archived')),
                    DropdownMenuItem(value: _statusAll, child: Text('All statuses')),
                  ],
                  onChanged: (value) => setState(() => _statusFilter = value ?? 'active'),
                ),
              ],
            ),
          ),
          Expanded(
            child: memoriesAsync.when(
              loading: () => const LoadingView(),
              error: (error, _) => ErrorView(
                error: error is ApiException ? error : ApiException.disconnected(),
                onRetry: () => ref.read(memoriesProvider.notifier).refresh(),
              ),
              data: (memories) {
                final filtered = memories.where(_matchesFilters).toList();
                if (filtered.isEmpty) {
                  return const EmptyState(
                    icon: Icons.psychology_alt_outlined,
                    title: 'No learning memory yet',
                    message: 'Add one manually, or save something from a conversation.',
                  );
                }
                return kindsAsync.when(
                  loading: () => const LoadingView(),
                  error: (_, _) => const LoadingView(),
                  data: (kinds) {
                    final kindLabel = {for (final k in kinds) k.id: k.displayName};
                    return ListView.builder(
                      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
                      itemCount: filtered.length,
                      itemBuilder: (context, index) => _MemoryTile(
                        memory: filtered[index],
                        kindLabel: kindLabel[filtered[index].kind] ?? filtered[index].kind,
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  bool _matchesFilters(LearningMemory memory) {
    if (_statusFilter != _statusAll && memory.status != _statusFilter) return false;
    if (_kindFilter != _kindAll && memory.kind != _kindFilter) return false;
    if (_courseFilter == _courseGeneral && memory.courseId != null) return false;
    if (_courseFilter != _courseAll && _courseFilter != _courseGeneral && memory.courseId != _courseFilter) {
      return false;
    }
    return true;
  }
}

class _MemoryTile extends ConsumerWidget {
  const _MemoryTile({required this.memory, required this.kindLabel});

  final LearningMemory memory;
  final String kindLabel;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.sm),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      _KindChip(label: kindLabel),
                      if (memory.isArchived) ...[
                        const SizedBox(width: AppSpacing.xs),
                        Text('Archived', style: theme.textTheme.labelSmall?.copyWith(fontStyle: FontStyle.italic)),
                      ],
                    ],
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(memory.topic, style: theme.textTheme.titleSmall),
                  const SizedBox(height: 2),
                  Text(
                    memory.summary,
                    style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            PopupMenuButton<String>(
              icon: Icon(Icons.more_horiz, size: 18, color: theme.colorScheme.onSurfaceVariant),
              onSelected: (value) => _onSelected(context, ref, value),
              itemBuilder: (context) => [
                const PopupMenuItem(value: 'edit', child: Text('Edit')),
                PopupMenuItem(value: memory.isActive ? 'archive' : 'restore', child: Text(memory.isActive ? 'Archive' : 'Restore')),
                const PopupMenuItem(value: 'delete', child: Text('Delete')),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _onSelected(BuildContext context, WidgetRef ref, String value) async {
    switch (value) {
      case 'edit':
        await showMemoryEditDialog(context, memory: memory);
      case 'archive':
        await ref.read(memoriesProvider.notifier).archive(memory.id);
      case 'restore':
        await ref.read(memoriesProvider.notifier).restore(memory.id);
      case 'delete':
        final confirmed = await showConfirmDialog(
          context,
          title: 'Delete this memory?',
          message: 'This permanently deletes "${memory.topic}". This cannot be undone.',
        );
        if (confirmed) await ref.read(memoriesProvider.notifier).delete(memory.id);
    }
  }
}

class _KindChip extends StatelessWidget {
  const _KindChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs, vertical: 2),
      decoration: BoxDecoration(
        color: theme.colorScheme.primaryContainer,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onPrimaryContainer),
      ),
    );
  }
}
