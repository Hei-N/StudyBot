import '../models/message.dart';

/// One event from the `/api/v1/ws/chat` protocol documented in
/// API_CONTRACT.md. A `sealed` hierarchy so callers get an exhaustiveness
/// check (via `switch`) instead of stringly-typed `event['type']` checks
/// scattered through the UI layer.
sealed class ChatStreamEvent {
  const ChatStreamEvent();
}

class StreamStarted extends ChatStreamEvent {
  const StreamStarted(this.chatId);
  final String chatId;
}

class StreamDelta extends ChatStreamEvent {
  const StreamDelta(this.content);
  final String content;
}

class StreamCompleted extends ChatStreamEvent {
  const StreamCompleted(this.message);

  /// Null only if the server ever sent `"message": null` (an empty chat) —
  /// in normal operation this always carries the final persisted message.
  final ChatMessage? message;
}

class StreamError extends ChatStreamEvent {
  const StreamError({required this.code, required this.message});
  final String code;
  final String message;
}

/// The connection itself dropped (as opposed to an in-protocol [StreamError]
/// event, which arrives *over* a healthy connection). Client-side only.
class StreamDisconnected extends ChatStreamEvent {
  const StreamDisconnected();
}
