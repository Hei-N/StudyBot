import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/course.dart';
import '../../core/theme/app_radii.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/confirm_dialog.dart';
import '../../core/widgets/error_view.dart';
import '../../core/widgets/loading_view.dart';
import '../../core/widgets/section_header.dart';
import 'course_edit_dialog.dart';
import 'courses_providers.dart';

/// The course list: General (always present) followed by every real course
/// from the backend. Selecting one sets [activeCourseIdProvider], which the
/// chats list watches to filter its contents.
class CoursesListView extends ConsumerWidget {
  const CoursesListView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final coursesAsync = ref.watch(coursesProvider);
    final activeCourseId = ref.watch(activeCourseIdProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionHeader(
          'Courses',
          trailing: IconButton(
            icon: const Icon(Icons.add, size: 18),
            tooltip: 'New course',
            onPressed: () => showCourseEditDialog(context),
          ),
        ),
        _CourseTile(
          label: 'General',
          subtitle: 'Unassigned chats',
          selected: activeCourseId == null,
          onTap: () => ref.read(activeCourseIdProvider.notifier).select(null),
        ),
        Expanded(
          child: coursesAsync.when(
            loading: () => const LoadingView(),
            error: (error, _) => ErrorView(
              error: error is ApiException ? error : ApiException.disconnected(),
              onRetry: () => ref.read(coursesProvider.notifier).refresh(),
            ),
            data: (courses) {
              if (courses.isEmpty) {
                return const Padding(
                  padding: EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
                  child: Text('No courses yet.'),
                );
              }
              return ListView.builder(
                itemCount: courses.length,
                itemBuilder: (context, index) {
                  final course = courses[index];
                  return _CourseTile(
                    label: course.name,
                    subtitle: course.subtitle,
                    selected: activeCourseId == course.id,
                    onTap: () => ref.read(activeCourseIdProvider.notifier).select(course.id),
                    onEdit: () => showCourseEditDialog(context, course: course),
                    onDelete: () => _confirmDelete(context, ref, course),
                  );
                },
              );
            },
          ),
        ),
      ],
    );
  }

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref, Course course) async {
    final confirmed = await showConfirmDialog(
      context,
      title: 'Delete "${course.name}"?',
      message: 'The course will be removed. Chats will remain and move to General — nothing is deleted.',
    );
    if (!confirmed) return;
    if (ref.read(activeCourseIdProvider) == course.id) {
      ref.read(activeCourseIdProvider.notifier).select(null);
    }
    await ref.read(coursesProvider.notifier).delete(course.id);
  }
}

class _CourseTile extends StatelessWidget {
  const _CourseTile({
    required this.label,
    required this.selected,
    required this.onTap,
    this.subtitle,
    this.onEdit,
    this.onDelete,
  });

  final String label;
  final String? subtitle;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback? onEdit;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final canManage = onEdit != null || onDelete != null;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs, vertical: 2),
      child: Material(
        color: selected ? theme.colorScheme.primary.withValues(alpha: 0.12) : Colors.transparent,
        borderRadius: AppRadii.mdRadius,
        child: InkWell(
          borderRadius: AppRadii.mdRadius,
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        label,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                          color: selected ? theme.colorScheme.primary : theme.colorScheme.onSurface,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                      if (subtitle != null)
                        Text(
                          subtitle!,
                          style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                          overflow: TextOverflow.ellipsis,
                        ),
                    ],
                  ),
                ),
                if (canManage)
                  PopupMenuButton<String>(
                    icon: Icon(Icons.more_horiz, size: 18, color: theme.colorScheme.onSurfaceVariant),
                    onSelected: (value) {
                      if (value == 'edit') onEdit?.call();
                      if (value == 'delete') onDelete?.call();
                    },
                    itemBuilder: (context) => [
                      if (onEdit != null) const PopupMenuItem(value: 'edit', child: Text('Edit')),
                      if (onDelete != null) const PopupMenuItem(value: 'delete', child: Text('Delete')),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
