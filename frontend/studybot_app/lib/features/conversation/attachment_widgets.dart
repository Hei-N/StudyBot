import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/message.dart';
import '../../core/platform/file_drop.dart';
import '../../core/theme/app_radii.dart';
import '../../core/theme/app_spacing.dart';
import '../connection/connection_providers.dart';
import 'attachment_providers.dart';

/// A compact chip for a file waiting in the composer: name, status, retry (if it failed) and remove.
class AttachmentChip extends StatelessWidget {
  const AttachmentChip({
    super.key,
    required this.attachment,
    required this.onRemove,
    this.onRetry,
  });

  final PendingAttachment attachment;
  final VoidCallback onRemove;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final failed = attachment.status == AttachmentStatus.failed;
    final status = switch (attachment.status) {
      AttachmentStatus.uploading => 'Processing…',
      AttachmentStatus.ready => 'Ready',
      AttachmentStatus.failed => attachment.failure ?? 'Failed',
    };
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: AppRadii.mdRadius,
        border: Border.all(
          color: failed
              ? theme.colorScheme.error
              : theme.colorScheme.outlineVariant,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.picture_as_pdf_outlined,
            size: 18,
            color: failed ? theme.colorScheme.error : null,
          ),
          const SizedBox(width: AppSpacing.xs),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 180),
            child: Text(
              attachment.displayName,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
          if (attachment.status == AttachmentStatus.uploading)
            const SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          if (attachment.status == AttachmentStatus.uploading)
            const SizedBox(width: AppSpacing.xs),
          Text(
            status,
            style: theme.textTheme.labelSmall?.copyWith(
              color: failed
                  ? theme.colorScheme.error
                  : theme.colorScheme.onSurfaceVariant,
            ),
          ),
          if (failed && onRetry != null)
            TextButton(
              onPressed: onRetry,
              style: TextButton.styleFrom(
                minimumSize: const Size(0, 28),
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
              ),
              child: const Text('Retry'),
            ),
          IconButton(
            tooltip: 'Remove ${attachment.displayName}',
            visualDensity: VisualDensity.compact,
            iconSize: 16,
            onPressed: onRemove,
            icon: const Icon(Icons.close),
          ),
        ],
      ),
    );
  }
}

/// The files of a sent message, shown inside its bubble. Names and page counts only.
class MessageAttachmentList extends StatelessWidget {
  const MessageAttachmentList({super.key, required this.attachments});

  final List<MessageAttachment> attachments;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final a in attachments)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.xs),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.picture_as_pdf_outlined, size: 18),
                const SizedBox(width: AppSpacing.xs),
                Flexible(
                  child: Text(
                    a.displayName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                if (a.pageCount != null) ...[
                  const SizedBox(width: AppSpacing.xs),
                  Text(
                    '${a.pageCount} ${a.pageCount == 1 ? 'page' : 'pages'}',
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ],
            ),
          ),
      ],
    );
  }
}

/// Wraps the conversation: while a chat is open it accepts PDFs dropped on the window, shows a
/// subtle "Drop PDF to attach" cue, and hands staged files to the same upload path as the + button.
class AttachmentDropZone extends ConsumerStatefulWidget {
  const AttachmentDropZone({
    super.key,
    required this.chatId,
    required this.child,
  });

  final String chatId;
  final Widget child;

  @override
  ConsumerState<AttachmentDropZone> createState() => _AttachmentDropZoneState();
}

class _AttachmentDropZoneState extends ConsumerState<AttachmentDropZone> {
  StreamSubscription<DropEvent>? _subscription;
  late final FileDropService _service;
  DragEntered? _dragging;

  @override
  void initState() {
    super.initState();
    _service = ref.read(fileDropServiceProvider);
    _subscription = _service.events.listen(_handle);
    _startAccepting();
  }

  Future<void> _startAccepting() async {
    try {
      final directory = await ref
          .read(studyBotApiProvider)
          .getIngestStagingDirectory();
      if (mounted) {
        await _service.setAccepting(true, stagingDirectory: directory);
      }
    } on ApiException {
      // Dropping stays off; the + button still works.
    }
  }

  @override
  void dispose() {
    _subscription?.cancel();
    _service.setAccepting(false);
    super.dispose();
  }

  void _handle(DropEvent event) {
    if (!mounted) return;
    switch (event) {
      case DragEntered():
        setState(() => _dragging = event);
      case DragExited():
        setState(() => _dragging = null);
      case Dropped(:final items):
        setState(() => _dragging = null);
        ref
            .read(composerAttachmentsProvider.notifier)
            .addDropped(widget.chatId, items);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dragging = _dragging;
    return Stack(
      children: [
        widget.child,
        if (dragging != null)
          Positioned.fill(
            child: IgnorePointer(
              child: Container(
                margin: const EdgeInsets.all(AppSpacing.sm),
                decoration: BoxDecoration(
                  color: theme.colorScheme.primary.withValues(alpha: 0.08),
                  borderRadius: AppRadii.lgRadius,
                  border: Border.all(
                    color: theme.colorScheme.primary,
                    width: 2,
                  ),
                ),
                alignment: Alignment.center,
                child: Text(
                  dragging.valid
                      ? 'Drop PDF to attach'
                      : 'Only PDF files can be attached',
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: theme.colorScheme.primary,
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

/// Chips (horizontally scrollable, so many files never grow the composer) plus a short honest note.
class ComposerAttachmentBar extends ConsumerWidget {
  const ComposerAttachmentBar({
    super.key,
    required this.chatId,
    required this.onChanged,
  });

  final String chatId;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(
      composerAttachmentsProvider.select((all) => all[chatId] ?? const []),
    );
    if (items.isEmpty) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final notifier = ref.read(composerAttachmentsProvider.notifier);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            height: 44,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: items.length,
              separatorBuilder: (_, _) => const SizedBox(width: AppSpacing.xs),
              itemBuilder: (context, index) {
                final a = items[index];
                return Center(
                  child: AttachmentChip(
                    attachment: a,
                    onRemove: () async {
                      await notifier.remove(chatId, a.localId);
                      onChanged();
                    },
                    onRetry: a.status == AttachmentStatus.failed
                        ? () async {
                            await notifier.retry(chatId, a.localId);
                            onChanged();
                          }
                        : null,
                  ),
                );
              },
            ),
          ),
          Text(
            "PDFs are saved with your message. StudyBot can't use them in answers yet.",
            style: theme.textTheme.labelSmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}
