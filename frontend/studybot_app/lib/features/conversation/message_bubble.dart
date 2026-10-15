import 'package:flutter/material.dart';

import '../../core/models/message.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_radii.dart';
import '../../core/theme/app_spacing.dart';
import 'studybot_markdown.dart';

/// One message turn. User messages are right-aligned in a tinted surface;
/// assistant messages are left-aligned, full-width, selectable Markdown.
class MessageBubble extends StatelessWidget {
  const MessageBubble({super.key, required this.message, this.isStreaming = false, this.onSaveToMemory});

  final ChatMessage message;

  /// True only for the in-progress assistant turn; avoids an empty flash before
  /// the first delta arrives.
  final bool isStreaming;

  /// Shows a "Save to Learning Memory" action beneath the message when provided.
  /// Omitted for the in-flight streaming bubble, which has no persisted id to
  /// use as provenance.
  final VoidCallback? onSaveToMemory;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUser = message.role == MessageRole.user;
    final isDark = theme.brightness == Brightness.dark;

    if (isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Container(
                margin: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
                decoration: BoxDecoration(
                  color: isDark ? AppColors.darkUserBubble : AppColors.lightUserBubble,
                  borderRadius: AppRadii.lgRadius,
                ),
                child: SelectableText(message.content, style: theme.textTheme.bodyMedium),
              ),
              if (onSaveToMemory != null) _SaveToMemoryAction(onPressed: onSaveToMemory!),
            ],
          ),
        ),
      );
    }

    return Align(
      alignment: Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
              child: message.content.isEmpty && isStreaming
                  ? const _TypingIndicator()
                  : StudyBotMarkdown(data: message.content, isStreaming: isStreaming),
            ),
            if (onSaveToMemory != null) _SaveToMemoryAction(onPressed: onSaveToMemory!),
          ],
        ),
      ),
    );
  }
}

class _SaveToMemoryAction extends StatelessWidget {
  const _SaveToMemoryAction({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return TextButton.icon(
      onPressed: onPressed,
      icon: Icon(Icons.bookmark_add_outlined, size: 16, color: theme.colorScheme.onSurfaceVariant),
      label: Text(
        'Save to Learning Memory',
        style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
      ),
      style: TextButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
        minimumSize: const Size(0, 28),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
    );
  }
}

class _TypingIndicator extends StatelessWidget {
  const _TypingIndicator();

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.onSurfaceVariant;
    return SizedBox(
      width: 32,
      height: 20,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: List.generate(
          3,
          (i) => Padding(
            padding: const EdgeInsets.symmetric(horizontal: 2),
            child: CircleAvatar(radius: 2.5, backgroundColor: color),
          ),
        ),
      ),
    );
  }
}
