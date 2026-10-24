import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/library_source.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/confirm_dialog.dart';
import '../../core/widgets/empty_state.dart';
import '../../core/widgets/error_view.dart';
import '../../core/widgets/loading_view.dart';
import '../courses/courses_providers.dart';
import 'library_providers.dart';

/// Study Library: upload a PDF, or authorize a folder and import PDFs from it. Shows
/// each source's access status and the files StudyBot holds. It reads no folder contents.
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

  Future<void> _upload(BuildContext context, WidgetRef ref) async {
    final outcome = await ref.read(libraryControllerProvider.notifier).uploadPdf();
    if (!context.mounted) return;
    final message = switch (outcome.kind) {
      UploadKind.duplicate => 'This PDF is already in your library.',
      UploadKind.notPdf => 'Please choose a PDF file.',
      UploadKind.error => "Couldn't upload that file. Please try again.",
      UploadKind.failed => switch (outcome.failureCode) {
        'password_required' => 'This PDF is password protected.',
        'invalid_pdf' => 'This file is not a valid PDF.',
        'file_too_large' || 'too_many_pages' || 'text_too_large' => 'This PDF is too large to import.',
        _ => "Couldn't import that PDF. Please try again.",
      },
      UploadKind.uploaded || UploadKind.cancelled => null,
    };
    if (message != null) _tell(context, message);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sources = ref.watch(libraryControllerProvider);
    final uploads = ref.watch(uploadedFilesProvider).value ?? const <LibraryFile>[];
    final uploading = ref.watch(importingSourcesProvider).contains(uploadingKey);
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
              child: Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                alignment: WrapAlignment.end,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  FilledButton.icon(
                    onPressed: uploading ? null : () => _upload(context, ref),
                    icon: const Icon(Icons.upload_file_outlined),
                    label: const Text('Upload File'),
                  ),
                  FilledButton.tonalIcon(
                    onPressed: () => _add(context, ref),
                    icon: const Icon(Icons.create_new_folder_outlined),
                    label: const Text('Add Folder'),
                  ),
                ],
              ),
            ),
            if (uploading)
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: LinearProgressIndicator(),
              ),
            Expanded(
              child: entries.isEmpty && uploads.isEmpty
                  ? const EmptyState(
                      icon: Icons.folder_open_outlined,
                      title: 'No folders yet',
                      message: 'Upload a PDF, or add a folder to let StudyBot read your study materials. StudyBot only reads them.',
                    )
                  : ListView(
                      children: [
                        if (uploads.isNotEmpty) ...[
                          const _SectionLabel('Uploaded files'),
                          for (final file in uploads) _UploadedRow(file: file),
                          const Divider(height: 1),
                        ],
                        if (entries.isNotEmpty) const _SectionLabel('Authorized folders'),
                        for (final entry in entries) ...[_SourceTile(entry: entry), const Divider(height: 1)],
                      ],
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md, AppSpacing.lg, AppSpacing.xs),
      child: Text(text, style: theme.textTheme.labelLarge?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
    );
  }
}

/// One directly uploaded file; Remove deletes StudyBot's own copy only.
class _UploadedRow extends ConsumerWidget {
  const _UploadedRow({required this.file});

  final LibraryFile file;

  Future<void> _remove(BuildContext context, WidgetRef ref) async {
    final confirmed = await showConfirmDialog(
      context,
      title: 'Remove from StudyBot?',
      message:
          'StudyBot will delete its own copy of "${file.displayName}". The original file on your Mac is not touched.',
      confirmLabel: 'Remove',
    );
    if (!confirmed || !context.mounted) return;
    final removed = await ref.read(libraryControllerProvider.notifier).removeUpload(file.id);
    if (!removed && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Couldn't remove that file.")));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _FileRow(
      file: file,
      indent: AppSpacing.lg,
      detail: 'Uploaded · ${_FileRow.describe(file)}',
      canImport: false,
      onImport: () {},
      onRemove: () => _remove(context, ref),
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

  Future<void> _import(BuildContext context, WidgetRef ref) async {
    final result = await ref.read(libraryControllerProvider.notifier).importPdf(entry.source);
    if (!context.mounted) return;
    final message = switch (result) {
      ImportPdfResult.unchanged => 'That PDF is already up to date.',
      ImportPdfResult.failed => "That PDF couldn't be processed. See the file for details.",
      ImportPdfResult.outsideSource => 'Choose a PDF inside this Study Library folder.',
      ImportPdfResult.notPdf => "That file isn't a PDF.",
      ImportPdfResult.needsAccess => 'This folder needs access again. Choose Reauthorize.',
      ImportPdfResult.error => "Couldn't import that PDF. Please try again.",
      ImportPdfResult.imported || ImportPdfResult.cancelled => null,
    };
    if (message != null) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final courses = ref.watch(coursesProvider).value ?? const [];
    final courseName = courses.where((c) => c.id == entry.source.courseId).map((c) => c.name).firstOrNull;
    final ok = entry.access == SourceAccess.authorized;
    final importing = ref.watch(importingSourcesProvider).contains(entry.source.id);
    final files = ref.watch(libraryFilesProvider(entry.source.id)).value ?? const <LibraryFile>[];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ListTile(
          leading: const Icon(Icons.folder_outlined),
          title: Text(entry.source.displayName),
          subtitle: Text(
            [?courseName, _statusLabel].join(' · '),
            style: TextStyle(color: ok ? null : theme.colorScheme.error),
          ),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (ok)
                TextButton(onPressed: importing ? null : () => _import(context, ref), child: const Text('Import PDF')),
              if (!ok) TextButton(onPressed: () => _reauthorize(context, ref), child: const Text('Reauthorize')),
              TextButton(onPressed: () => _remove(context, ref), child: const Text('Remove')),
            ],
          ),
        ),
        if (importing)
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            child: LinearProgressIndicator(),
          ),
        for (final file in files)
          _FileRow(file: file, canImport: ok && !importing, onImport: () => _import(context, ref)),
      ],
    );
  }
}

/// One imported file: name, where it is in the source, and its processing state.
class _FileRow extends StatelessWidget {
  const _FileRow({
    required this.file,
    required this.canImport,
    required this.onImport,
    this.onRemove,
    this.indent,
    this.detail,
  });

  final LibraryFile file;
  final bool canImport;
  final VoidCallback onImport;

  /// Set for uploaded files, which offer Remove instead of Import again.
  final VoidCallback? onRemove;
  final double? indent;

  /// Replaces the default "path · status" line.
  final String? detail;

  static String describe(LibraryFile file) {
    final pages = file.pageCount ?? 0;
    final pageLabel = '$pages ${pages == 1 ? 'page' : 'pages'}';
    switch (file.processingState) {
      case 'ready':
        final withText = file.textPageCount ?? 0;
        if (withText == 0) return 'No extractable text · $pageLabel';
        return withText == pages ? 'Ready · $pageLabel' : 'Ready · $pageLabel ($withText with text)';
      case 'indexing':
        return 'Importing…';
      case 'failed':
        return switch (file.failureCode) {
          'password_required' => 'Password-protected PDF',
          'invalid_pdf' => 'Not a valid PDF',
          'interrupted' => 'Import was interrupted',
          'file_too_large' => 'PDF is too large',
          'too_many_pages' => 'PDF has too many pages',
          'text_too_large' => 'PDF has too much text',
          _ => 'Import failed',
        };
      case 'stale':
        return 'Out of date';
      default:
        return 'Needs retry';
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final state = file.processingState;
    final needsRetry = state == 'failed' || state == 'pending' || state == 'stale';
    final location = file.relativePath == file.displayName ? '' : '${file.relativePath} · ';
    return Padding(
      padding: EdgeInsets.only(
        left: indent ?? AppSpacing.xl + AppSpacing.lg,
        right: AppSpacing.lg,
        top: indent == null ? 0 : AppSpacing.xs,
        bottom: AppSpacing.sm,
      ),
      child: Row(
        children: [
          const Icon(Icons.picture_as_pdf_outlined, size: 20),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(file.displayName, style: theme.textTheme.bodyMedium),
                Text(
                  detail ?? '$location${describe(file)}',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: state == 'failed' ? theme.colorScheme.error : theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          if (onRemove != null)
            TextButton(onPressed: onRemove, child: const Text('Remove'))
          else if (needsRetry)
            TextButton(onPressed: canImport ? onImport : null, child: const Text('Import again')),
        ],
      ),
    );
  }
}
