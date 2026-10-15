import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_radii.dart';
import '../../core/theme/app_spacing.dart';
import '../chats/chats_providers.dart';
import 'reasoning_providers.dart';

/// A small icon for a reasoning mode id; presentational only (display names and
/// descriptions come from the backend).
IconData _iconFor(String reasoningModeId) => reasoningModeId == 'deep' ? Icons.psychology : Icons.bolt;

/// The compact reasoning-mode selector, shown next to [ModePicker] in the
/// composer. Shows the active chat's mode ([Chat.reasoningMode]) and calls
/// [ChatsNotifier.setReasoningMode] on selection. Names and descriptions come
/// from the backend catalog. Defaults to "Fast", the default for new chats.
class ReasoningPicker extends ConsumerWidget {
  const ReasoningPicker({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chat = ref.watch(activeChatProvider);
    final catalogAsync = ref.watch(reasoningModeCatalogProvider);
    final theme = Theme.of(context);

    if (chat == null) return const SizedBox.shrink();

    return catalogAsync.when(
      loading: () => const SizedBox(width: 72, height: 32),
      error: (_, _) => const SizedBox.shrink(),
      data: (modes) {
        final current = modes.where((m) => m.id == chat.reasoningMode).firstOrNull;
        return PopupMenuButton<String>(
          tooltip: 'Reasoning mode',
          initialValue: chat.reasoningMode,
          onSelected: (mode) {
            if (mode == chat.reasoningMode) return;
            ref.read(chatsProvider.notifier).setReasoningMode(chat.id, mode);
          },
          itemBuilder: (context) => [
            for (final mode in modes)
              PopupMenuItem(
                value: mode.id,
                child: Row(
                  children: [
                    Icon(_iconFor(mode.id), size: 16, color: theme.colorScheme.onSurfaceVariant),
                    const SizedBox(width: AppSpacing.xs),
                    // Flexible so the description wraps within the popup's max width; a Row's
                    // non-flex children are sized unwrapped and this text would overflow.
                    Flexible(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(mode.displayName, style: theme.textTheme.bodyMedium),
                          Text(
                            mode.description,
                            style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                            softWrap: true,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
          ],
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs, vertical: AppSpacing.xs),
            decoration: BoxDecoration(
              borderRadius: AppRadii.mdRadius,
              border: Border.all(color: theme.colorScheme.outlineVariant),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(_iconFor(chat.reasoningMode), size: 14, color: theme.colorScheme.onSurfaceVariant),
                const SizedBox(width: AppSpacing.xxs),
                Text(current?.displayName ?? chat.reasoningMode, style: theme.textTheme.labelMedium),
              ],
            ),
          ),
        );
      },
    );
  }
}
