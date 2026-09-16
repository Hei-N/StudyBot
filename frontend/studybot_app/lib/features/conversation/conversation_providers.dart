import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/chat_stream_event.dart';
import '../../core/models/message.dart';
import '../chats/chats_providers.dart';
import '../connection/connection_providers.dart';

/// The active chat's message history plus whatever is currently streaming
/// in. `streamingText` is the accumulated delta buffer for an in-flight
/// assistant reply — it is replaced by the real persisted message (appended
/// to [messages]) the moment `message_completed` arrives, per
/// API_CONTRACT.md; it is never itself treated as a persisted message.
class ConversationState {
  const ConversationState({required this.messages, this.streamingText, this.isSending = false});

  final List<ChatMessage> messages;
  final String? streamingText;

  /// True from the moment [ConversationNotifier.send] is called until the
  /// stream completes or errors — drives "disable sending another message
  /// while streaming".
  final bool isSending;

  bool get isStreaming => streamingText != null;

  ConversationState copyWith({
    List<ChatMessage>? messages,
    String? streamingText,
    bool clearStreamingText = false,
    bool? isSending,
  }) {
    return ConversationState(
      messages: messages ?? this.messages,
      streamingText: clearStreamingText ? null : (streamingText ?? this.streamingText),
      isSending: isSending ?? this.isSending,
    );
  }
}

/// Drives the message list for [activeChatIdProvider] and the WebSocket
/// send/stream lifecycle. Rebuilds (refetching full history) whenever the
/// active chat changes; the single WebSocket event subscription is set up
/// once and lives for the notifier's lifetime.
class ConversationNotifier extends AsyncNotifier<ConversationState> {
  bool _listening = false;
  String? _chatId;

  @override
  Future<ConversationState> build() async {
    final chatId = ref.watch(activeChatIdProvider);
    _chatId = chatId;

    if (!_listening) {
      _listening = true;
      final subscription = ref.read(chatWebSocketClientProvider).events.listen(_handleEvent);
      ref.onDispose(subscription.cancel);
    }

    if (chatId == null) return const ConversationState(messages: []);
    return ConversationState(messages: await _fetchMessages(chatId));
  }

  Future<void> refresh() async {
    final chatId = _chatId;
    if (chatId == null) return;
    state = await AsyncValue.guard(() async {
      return ConversationState(messages: await _fetchMessages(chatId));
    });
  }

  /// Per API_CONTRACT.md's "Lazy persistence": a chat with no messages yet
  /// may not have a database row at all, so `GET .../messages` 404s with
  /// `CHAT_NOT_FOUND` — that's a normal empty chat here, not a real error.
  Future<List<ChatMessage>> _fetchMessages(String chatId) async {
    try {
      return await ref.read(studyBotApiProvider).getChatMessages(chatId);
    } on ApiException catch (e) {
      if (e.code == ApiErrorCode.chatNotFound) return const [];
      rethrow;
    }
  }

  /// Sends [content] on the active chat. No-ops on blank input or while a
  /// reply is already streaming — the composer disables itself for the
  /// latter, but this guard keeps the notifier correct regardless of caller.
  Future<void> send(String content) async {
    final chatId = _chatId;
    final current = state.value;
    final trimmed = content.trim();
    if (chatId == null || current == null || current.isSending || trimmed.isEmpty) return;

    final optimisticUser = ChatMessage.pending(role: MessageRole.user, content: trimmed);
    state = AsyncValue.data(
      current.copyWith(messages: [...current.messages, optimisticUser], isSending: true, streamingText: ''),
    );

    try {
      await ref.read(chatWebSocketClientProvider).sendMessage(chatId: chatId, content: trimmed);
    } on ApiException catch (e) {
      _failStreaming(e);
    }
  }

  void _handleEvent(ChatStreamEvent event) {
    final current = state.value;
    // Ignore events that arrive while this chat isn't the one sending —
    // e.g. the user switched chats mid-stream. The reply is still being
    // persisted server-side and will simply appear on the next full fetch.
    if (current == null || !current.isSending) return;

    switch (event) {
      case StreamStarted():
        break;
      case StreamDelta(:final content):
        state = AsyncValue.data(current.copyWith(streamingText: (current.streamingText ?? '') + content));
      case StreamCompleted(:final message):
        final messages = [...current.messages];
        if (message != null) messages.add(message);
        state = AsyncValue.data(ConversationState(messages: messages));
      case StreamError(:final code, :final message):
        _failStreaming(ApiException(code: code, message: message));
      case StreamDisconnected():
        _failStreaming(ApiException.disconnected());
    }
  }

  void _failStreaming(ApiException error) {
    final current = state.value;
    if (current != null) {
      state = AsyncValue.data(current.copyWith(isSending: false, clearStreamingText: true));
    }
    ref.read(conversationErrorProvider.notifier).set(error);
  }
}

final conversationProvider = AsyncNotifierProvider<ConversationNotifier, ConversationState>(
  ConversationNotifier.new,
);

/// A transient, one-shot error from the last send/stream attempt (e.g. a
/// dropped connection or `MODEL_ERROR`). The UI surfaces it once (a
/// snackbar/banner) and clears it via `set(null)` — this is not persisted
/// conversation state.
class ConversationErrorNotifier extends Notifier<ApiException?> {
  @override
  ApiException? build() => null;

  void set(ApiException? error) => state = error;
}

final conversationErrorProvider = NotifierProvider<ConversationErrorNotifier, ApiException?>(
  ConversationErrorNotifier.new,
);
