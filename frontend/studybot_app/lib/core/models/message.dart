/// A persisted chat message, as returned by `GET /api/v1/chats/{id}/messages`
/// and inside a WebSocket `message_completed` event's `message` field.
///
/// Mirrors `MessageOut` in API_CONTRACT.md. Only real user/assistant turns
/// ever appear here — the system prompt, course context, and teaching-mode
/// instructions are internal engine context Flutter never sees.
enum MessageRole { user, assistant }

MessageRole _roleFromString(String value) {
  switch (value) {
    case 'user':
      return MessageRole.user;
    case 'assistant':
      return MessageRole.assistant;
    default:
      throw FormatException('Unknown message role: $value');
  }
}

class ChatMessage {
  const ChatMessage({required this.id, required this.role, required this.content, required this.createdAt});

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    return ChatMessage(
      id: json['id'] as int,
      role: _roleFromString(json['role'] as String),
      content: json['content'] as String,
      createdAt: json['createdAt'] as String,
    );
  }

  /// A client-only identifier for the optimistic bubbles shown while a
  /// message is in flight over the WebSocket, before the server assigns a
  /// real id. Never sent to, or confused with, a persisted message id.
  factory ChatMessage.pending({required MessageRole role, required String content}) {
    return ChatMessage(id: null, role: role, content: content, createdAt: '');
  }

  /// Null only for a not-yet-persisted, optimistic message (see [pending]).
  final int? id;
  final MessageRole role;
  final String content;
  final String createdAt;

  bool get isPending => id == null;

  ChatMessage copyWith({String? content}) {
    return ChatMessage(id: id, role: role, content: content ?? this.content, createdAt: createdAt);
  }
}
