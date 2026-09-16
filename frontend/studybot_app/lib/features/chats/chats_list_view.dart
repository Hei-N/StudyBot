import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/chat.dart';
import '../../core/theme/app_radii.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/confirm_dialog.dart';
import '../../core/widgets/empty_state.dart';
import '../../core/widgets/error_view.dart';
import '../../core/widgets/loading_view.dart';
import '../../core/widgets/section_header.dart';
import '../courses/courses_providers.dart';
import 'chats_providers.dart';
import 'rename_chat_dialog.dart';

/// Chats for the currently selected course (or General), most recently
/// updated first. Selecting one opens it in the conversation view.
class ChatsListView extends ConsumerWidget {
  const ChatsListView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chatsAsync = ref.watch(chatsProvider);
    final activeChatId = ref.watch(activeChatIdProvider);
    final activeCourse = ref.watch(activeCourseProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SectionHeader(
          activeCourse?.name ?? 'General',
          trailing: IconButton(
            icon: const Icon(Icons.add_comment_outlined, size: 18),
            tooltip: 'New chat',
            onPressed: () async {
              final chat = await ref.read(chatsProvider.notifier).create();
              ref.read(activeChatIdProvider.notifier).select(chat.id);
            },
          ),
        ),
        Expanded(
          child: chatsAsync.when(
            loading: () => const LoadingView(),
            error: (error, _) => ErrorView(
              error: error is ApiException ? error : ApiException.disconnected(),
              onRetry: () => ref.read(chatsProvider.notifier).refresh(),
            ),
            data: (chats) {
              if (chats.isEmpty) {
                return const EmptyState(
                  icon: Icons.chat_bubble_outline,
                  title: 'No chats yet',
                  message: 'Start a new chat to begin.',
                );
              }
              return ListView.builder(
                itemCount: chats.length,
                itemBuilder: (context, index) {
                  final chat = chats[index];
                  return _ChatTile(
                    chat: chat,
                    selected: chat.id == activeChatId,
                    onTap: () => ref.read(activeChatIdProvider.notifier).select(chat.id),
                    onRename: () => showRenameChatDialog(context, chat),
                    onDelete: () => _confirmDelete(context, ref, chat),
                  );
                },
              );
            },
          ),
        ),
      ],
    );
  }

  Future<void> _confirmDelete(BuildContext context, WidgetRef ref, Chat chat) async {
    final confirmed = await showConfirmDialog(
      context,
      title: 'Delete "${chat.displayTitle}"?',
      message: 'This permanently deletes the chat and its messages. This cannot be undone.',
    );
    if (!confirmed) return;
    await ref.read(chatsProvider.notifier).delete(chat.id);
  }
}

class _ChatTile extends StatelessWidget {
  const _ChatTile({
    required this.chat,
    required this.selected,
    required this.onTap,
    required this.onRename,
    required this.onDelete,
  });

  final Chat chat;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback onRename;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
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
                  child: Text(
                    chat.displayTitle,
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
                      color: selected ? theme.colorScheme.primary : theme.colorScheme.onSurface,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                PopupMenuButton<String>(
                  icon: Icon(Icons.more_horiz, size: 18, color: theme.colorScheme.onSurfaceVariant),
                  onSelected: (value) {
                    if (value == 'rename') onRename();
                    if (value == 'delete') onDelete();
                  },
                  itemBuilder: (context) => const [
                    PopupMenuItem(value: 'rename', child: Text('Rename')),
                    PopupMenuItem(value: 'delete', child: Text('Delete')),
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
