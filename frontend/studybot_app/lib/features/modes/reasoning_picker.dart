import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_radii.dart';
import '../../core/theme/app_spacing.dart';
import '../chats/chats_providers.dart';
import 'reasoning_providers.dart';

/// A small icon for a reasoning mode id — purely presentational, kept
/// separate from the backend-owned display name/description.
IconData _iconFor(String reasoningModeId) => reasoningModeId == 'deep' ? Icons.psychology : Icons.bolt;

/// The compact Reasoning Mode selector, shown next to [ModePicker] in the
/// composer. Shows the active chat's current mode (from
/// [Chat.reasoningMode]) and, on selection, calls
/// [ChatsNotifier.setReasoningMode] — display names/descriptions always
/// come from the backend catalog, never hardcoded here. Deliberately
/// smaller/quieter than the teaching-mode picker so the composer stays
/// uncluttered; defaults to showing "Fast", matching every new chat's
/// actual default.
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
                    // Flexible (not a bare Column) so the description text
                    // wraps within the popup menu's own max width instead
                    // of overflowing — a Row's non-flex children are sized
                    // to their natural/unwrapped width, and this
                    // description is long enough to exceed that.
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
