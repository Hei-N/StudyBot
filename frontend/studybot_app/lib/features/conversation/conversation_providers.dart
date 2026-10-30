import 'dart:async';
import 'dart:developer' as developer;

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/chat_stream_event.dart';
import '../../core/api/chat_websocket_client.dart';
import '../../core/models/message.dart';
import '../chats/chats_providers.dart';
import '../connection/connection_providers.dart';

/// Structural-only debug logging for the streaming pipeline (chat id, event
/// type, message count, state transition; never message content). Compiled out
/// of release builds via [kDebugMode].
void _debugLog(String message) {
  if (kDebugMode) developer.log(message, name: 'conversation');
}

/// The active chat's message history plus the reply currently streaming in.
/// `streamingText` buffers the deltas of an in-flight reply and is replaced by
/// the persisted message (appended to [messages]) when `message_completed`
/// arrives; it is never treated as persisted itself.
class ConversationState {
  const ConversationState({
    required this.messages,
    this.streamingText,
    this.isSending = false,
  });

  final List<ChatMessage> messages;
  final String? streamingText;

  /// True from [ConversationNotifier.send] until the stream completes or errors;
  /// disables sending another message while streaming.
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
      streamingText: clearStreamingText
          ? null
          : (streamingText ?? this.streamingText),
      isSending: isSending ?? this.isSending,
    );
  }
}

/// Drives the message list for [activeChatIdProvider] and the WebSocket
/// send/stream lifecycle. Rebuilds (refetching history) when the active chat
/// changes.
///
/// The event subscription uses `ref.listen` (not a one-time `ref.read`) so it
/// follows every new [ChatWebSocketClient] that [chatWebSocketClientProvider]
/// produces, e.g. when [connectionConfigProvider] changes after saved settings
/// are restored asynchronously. A one-time subscription would stay attached to
/// the old client's orphaned stream and never see another event.
class ConversationNotifier extends AsyncNotifier<ConversationState> {
  StreamSubscription<ChatStreamEvent>? _wsSubscription;
  String? _chatId;

  @override
  Future<ConversationState> build() async {
    final chatId = ref.watch(activeChatIdProvider);
    _chatId = chatId;
    _debugLog('build: chatId=$chatId');

    ref.listen<ChatWebSocketClient>(
      chatWebSocketClientProvider,
      (previous, next) => _resubscribe(next),
      fireImmediately: true,
    );
    ref.onDispose(() => _wsSubscription?.cancel());

    if (chatId == null) return const ConversationState(messages: []);
    final messages = await _fetchMessages(chatId);
    _debugLog('build: chatId=$chatId loaded messageCount=${messages.length}');
    return ConversationState(messages: messages);
  }

  void _resubscribe(ChatWebSocketClient client) {
    _debugLog('resubscribe: chatId=$_chatId client=${client.hashCode}');
    _wsSubscription?.cancel();
    _wsSubscription = client.events.listen(_handleEvent);
  }

  Future<void> refresh() async {
    final chatId = _chatId;
    if (chatId == null) return;
    state = await AsyncValue.guard(() async {
      return ConversationState(messages: await _fetchMessages(chatId));
    });
  }

  /// Treats `CHAT_NOT_FOUND` as an empty history instead of surfacing an error.
  Future<List<ChatMessage>> _fetchMessages(String chatId) async {
    try {
      return await ref.read(studyBotApiProvider).getChatMessages(chatId);
    } on ApiException catch (e) {
      if (e.code == ApiErrorCode.chatNotFound) return const [];
      rethrow;
    }
  }

  /// Sends [content] on the active chat. Ignored for blank input or while a reply
  /// is streaming (the composer also disables itself; this keeps the notifier
  /// correct for any caller).
  Future<void> send(
    String content, {
    List<MessageAttachment> attachments = const [],
  }) async {
    final chatId = _chatId;
    final current = state.value;
    final trimmed = content.trim();
    if (chatId == null ||
        current == null ||
        current.isSending ||
        trimmed.isEmpty) {
      return;
    }

    _debugLog('send: chatId=$chatId isSending->true');
    final optimisticUser = ChatMessage.pending(
      role: MessageRole.user,
      content: trimmed,
      attachments: attachments,
    );
    state = AsyncValue.data(
      current.copyWith(
        messages: [...current.messages, optimisticUser],
        isSending: true,
        streamingText: '',
      ),
    );

    try {
      await ref
          .read(chatWebSocketClientProvider)
          .sendMessage(
            chatId: chatId,
            content: trimmed,
            attachmentIds: [for (final a in attachments) a.fileId],
          );
    } on ApiException catch (e) {
      _failStreaming(e);
    }
  }

  void _handleEvent(ChatStreamEvent event) {
    final current = state.value;
    // Ignore events for a chat that isn't the one sending (e.g. the user switched
    // chats mid-stream); the reply is still persisted server-side and appears on
    // the next full fetch.
    if (current == null || !current.isSending) {
      _debugLog(
        'event ignored: chatId=$_chatId type=${event.runtimeType} (not currently sending)',
      );
      return;
    }

    switch (event) {
      case StreamStarted():
        _debugLog('event: chatId=$_chatId type=StreamStarted');
      case StreamDelta(:final content):
        state = AsyncValue.data(
          current.copyWith(
            streamingText: (current.streamingText ?? '') + content,
          ),
        );
      case StreamCompleted(:final message):
        final messages = [...current.messages];
        if (message != null) messages.add(message);
        _debugLog(
          'event: chatId=$_chatId type=StreamCompleted hasMessage=${message != null} '
          'messageCount=${current.messages.length}->${messages.length} isSending->false',
        );
        state = AsyncValue.data(ConversationState(messages: messages));
      case StreamError(:final code, :final message):
        _debugLog(
          'event: chatId=$_chatId type=StreamError code=$code isSending->false',
        );
        _failStreaming(ApiException(code: code, message: message));
      case StreamDisconnected():
        _debugLog(
          'event: chatId=$_chatId type=StreamDisconnected isSending->false',
        );
        _failStreaming(ApiException.disconnected());
    }
  }

  void _failStreaming(ApiException error) {
    final current = state.value;
    if (current != null) {
      state = AsyncValue.data(
        current.copyWith(isSending: false, clearStreamingText: true),
      );
    }
    ref.read(conversationErrorProvider.notifier).set(error);
  }
}

final conversationProvider =
    AsyncNotifierProvider<ConversationNotifier, ConversationState>(
      ConversationNotifier.new,
    );

/// A transient, one-shot error from the last send/stream attempt (e.g. a
/// dropped connection or `MODEL_ERROR`). The UI shows it once and clears it via
/// `set(null)`; it is not persisted state.
class ConversationErrorNotifier extends Notifier<ApiException?> {
  @override
  ApiException? build() => null;

  void set(ApiException? error) => state = error;
}

final conversationErrorProvider =
    NotifierProvider<ConversationErrorNotifier, ApiException?>(
      ConversationErrorNotifier.new,
    );
