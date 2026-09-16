import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/message.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/empty_state.dart';
import '../../core/widgets/error_view.dart';
import '../../core/widgets/loading_view.dart';
import '../chats/chats_providers.dart';
import 'composer.dart';
import 'conversation_providers.dart';
import 'message_bubble.dart';

/// The main conversation pane: message history plus the in-progress
/// streaming reply (if any) and the composer. Auto-scrolls to the bottom on
/// new content without ever rebuilding the whole message list per token —
/// only the last item (the streaming bubble) changes as deltas arrive.
class ConversationView extends ConsumerStatefulWidget {
  const ConversationView({super.key});

  @override
  ConsumerState<ConversationView> createState() => _ConversationViewState();
}

class _ConversationViewState extends ConsumerState<ConversationView> {
  final _scrollController = ScrollController();

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    if (!_scrollController.hasClients) return;
    _scrollController.animateTo(
      _scrollController.position.maxScrollExtent,
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOut,
    );
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(activeChatProvider);

    ref.listen(conversationErrorProvider, (previous, next) {
      if (next == null) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_friendlyError(next))));
      ref.read(conversationErrorProvider.notifier).set(null);
    });

    if (chat == null) {
      return const EmptyState(
        icon: Icons.forum_outlined,
        title: 'No chat selected',
        message: 'Choose a chat on the left, or start a new one.',
      );
    }

    final conversationAsync = ref.watch(conversationProvider);

    return Column(
      children: [
        Expanded(
          child: conversationAsync.when(
            loading: () => const LoadingView(),
            error: (error, _) => ErrorView(
              error: error is ApiException ? error : ApiException.disconnected(),
              onRetry: () => ref.read(conversationProvider.notifier).refresh(),
            ),
            data: (state) {
              if (state.messages.isEmpty && !state.isStreaming) {
                return const EmptyState(
                  icon: Icons.chat_outlined,
                  title: 'Empty chat',
                  message: 'Send a message to get started.',
                );
              }

              WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());

              final streamingMessage = state.isStreaming
                  ? ChatMessage.pending(role: MessageRole.assistant, content: state.streamingText ?? '')
                  : null;

              return ListView.builder(
                controller: _scrollController,
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.md),
                itemCount: state.messages.length + (streamingMessage == null ? 0 : 1),
                itemBuilder: (context, index) {
                  if (index < state.messages.length) {
                    return MessageBubble(message: state.messages[index]);
                  }
                  return MessageBubble(message: streamingMessage!, isStreaming: true);
                },
              );
            },
          ),
        ),
        const Composer(),
      ],
    );
  }

  String _friendlyError(ApiException error) {
    switch (error.code) {
      case ApiErrorCode.disconnected:
        return 'Connection to the engine was lost.';
      case ApiErrorCode.modelError:
        return 'The model could not respond. Please try again.';
      default:
        return error.message;
    }
  }
}
