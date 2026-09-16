import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_radii.dart';
import '../../core/theme/app_spacing.dart';
import '../chats/chats_providers.dart';
import 'modes_providers.dart';

/// The Teaching Mode selector used in the composer. Shows the active
/// chat's current mode (from [Chat.teachingMode]) and, on selection, calls
/// [ChatsNotifier.setMode] — display names/descriptions always come from
/// the backend catalog, never hardcoded here.
class ModePicker extends ConsumerWidget {
  const ModePicker({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chat = ref.watch(activeChatProvider);
    final catalogAsync = ref.watch(modeCatalogProvider);
    final theme = Theme.of(context);

    if (chat == null) return const SizedBox.shrink();

    return catalogAsync.when(
      loading: () => const SizedBox(width: 120, height: 36),
      error: (_, _) => const SizedBox.shrink(),
      data: (modes) {
        final current = modes.where((m) => m.id == chat.teachingMode).firstOrNull;
        return PopupMenuButton<String>(
          tooltip: 'Teaching mode',
          initialValue: chat.teachingMode,
          onSelected: (mode) {
            if (mode == chat.teachingMode) return;
            ref.read(chatsProvider.notifier).setMode(chat.id, mode);
          },
          itemBuilder: (context) => [
            for (final mode in modes)
              PopupMenuItem(
                value: mode.id,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(mode.displayName, style: theme.textTheme.bodyMedium),
                    Text(
                      mode.description,
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                    ),
                  ],
                ),
              ),
          ],
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
            decoration: BoxDecoration(
              borderRadius: AppRadii.mdRadius,
              border: Border.all(color: theme.colorScheme.outlineVariant),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(current?.displayName ?? chat.teachingMode, style: theme.textTheme.labelLarge),
                const SizedBox(width: AppSpacing.xxs),
                Icon(Icons.expand_more, size: 16, color: theme.colorScheme.onSurfaceVariant),
              ],
            ),
          ),
        );
      },
    );
  }
}
