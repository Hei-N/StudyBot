import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/confirm_dialog.dart';
import '../../core/widgets/empty_state.dart';
import '../../core/widgets/error_view.dart';
import '../../core/widgets/loading_view.dart';
import '../courses/courses_providers.dart';
import 'library_providers.dart';

/// Minimal source management: authorize folders, see their access status,
/// reauthorize or remove them. It lists no files and reads no folder contents.
class LibraryView extends ConsumerWidget {
  const LibraryView({super.key});

  void _tell(BuildContext context, String message) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _add(BuildContext context, WidgetRef ref) async {
    final result = await ref.read(libraryControllerProvider.notifier).addFolder();
    if (!context.mounted) return;
    if (result == AddFolderResult.failed) {
      _tell(context, "Couldn't authorize that folder. Please try again.");
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sources = ref.watch(libraryControllerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Study Library')),
      body: sources.when(
        loading: () => const LoadingView(),
        error: (error, _) => ErrorView(
          error: error is ApiException ? error : ApiException.disconnected(),
          onRetry: () => ref.read(libraryControllerProvider.notifier).refresh(),
        ),
        data: (entries) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Row(
                children: [
                  Expanded(child: Text('Authorized sources', style: Theme.of(context).textTheme.titleMedium)),
                  FilledButton.icon(
                    onPressed: () => _add(context, ref),
                    icon: const Icon(Icons.create_new_folder_outlined),
                    label: const Text('Add Folder'),
                  ),
                ],
              ),
            ),
            Expanded(
              child: entries.isEmpty
                  ? const EmptyState(
                      icon: Icons.folder_open_outlined,
                      title: 'No folders yet',
                      message: 'Add a folder to let StudyBot read your study materials. StudyBot only reads it.',
                    )
                  : ListView.separated(
                      itemCount: entries.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (context, index) => _SourceTile(entry: entries[index]),
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SourceTile extends ConsumerWidget {
  const _SourceTile({required this.entry});

  final LibrarySourceEntry entry;

  String get _statusLabel => switch (entry.access) {
    SourceAccess.authorized => 'Authorized',
    SourceAccess.needsAccess => 'Needs access',
    SourceAccess.failed => "Couldn't check access",
  };

  Future<void> _reauthorize(BuildContext context, WidgetRef ref) async {
    final result = await ref.read(libraryControllerProvider.notifier).reauthorize(entry.source);
    if (!context.mounted) return;
    final message = switch (result) {
      ReauthorizeResult.mismatch =>
        "That isn't the same folder. Choose the original folder to restore access, or add it as a new source.",
      ReauthorizeResult.failed => "Couldn't authorize that folder. Please try again.",
      _ => null,
    };
    if (message != null) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _remove(BuildContext context, WidgetRef ref) async {
    final confirmed = await showConfirmDialog(
      context,
      title: 'Remove from StudyBot?',
      message: 'StudyBot will stop using "${entry.source.displayName}". Your folder and its files are not deleted.',
      confirmLabel: 'Remove',
    );
    if (!confirmed || !context.mounted) return;
    final removed = await ref.read(libraryControllerProvider.notifier).remove(entry.source.id);
    if (!removed && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Couldn't remove that source.")));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final courses = ref.watch(coursesProvider).value ?? const [];
    final courseName = courses.where((c) => c.id == entry.source.courseId).map((c) => c.name).firstOrNull;
    final ok = entry.access == SourceAccess.authorized;
    return ListTile(
      leading: const Icon(Icons.folder_outlined),
      title: Text(entry.source.displayName),
      subtitle: Text(
        [?courseName, _statusLabel].join(' · '),
        style: TextStyle(color: ok ? null : theme.colorScheme.error),
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (!ok) TextButton(onPressed: () => _reauthorize(context, ref), child: const Text('Reauthorize')),
          TextButton(onPressed: () => _remove(context, ref), child: const Text('Remove')),
        ],
      ),
    );
  }
}
