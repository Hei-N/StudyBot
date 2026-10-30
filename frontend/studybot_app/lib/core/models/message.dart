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

/// A file attached to a message: metadata only (never page text or paths).
class MessageAttachment {
  const MessageAttachment({
    required this.id,
    required this.fileId,
    required this.displayName,
    required this.pageCount,
    required this.textPageCount,
    required this.processingState,
  });

  factory MessageAttachment.fromJson(Map<String, dynamic> json) {
    return MessageAttachment(
      id: json['id'] as int,
      fileId: json['fileId'] as String,
      displayName: json['displayName'] as String,
      pageCount: json['pageCount'] as int?,
      textPageCount: json['textPageCount'] as int?,
      processingState: json['processingState'] as String,
    );
  }

  final int id;
  final String fileId;
  final String displayName;
  final int? pageCount;
  final int? textPageCount;
  final String processingState;
}

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    required this.content,
    required this.createdAt,
    this.attachments = const [],
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    return ChatMessage(
      id: json['id'] as int,
      role: _roleFromString(json['role'] as String),
      content: json['content'] as String,
      createdAt: json['createdAt'] as String,
      attachments: [
        for (final a in (json['attachments'] as List<dynamic>? ?? const []))
          MessageAttachment.fromJson(a as Map<String, dynamic>),
      ],
    );
  }

  /// A client-only identifier for the optimistic bubbles shown while a
  /// message is in flight over the WebSocket, before the server assigns a
  /// real id. Never sent to, or confused with, a persisted message id.
  factory ChatMessage.pending({
    required MessageRole role,
    required String content,
    List<MessageAttachment> attachments = const [],
  }) {
    return ChatMessage(id: null, role: role, content: content, createdAt: '', attachments: attachments);
  }

  /// Null only for a not-yet-persisted, optimistic message (see [pending]).
  final int? id;
  final MessageRole role;
  final String content;
  final String createdAt;
  final List<MessageAttachment> attachments;

  bool get isPending => id == null;

  ChatMessage copyWith({String? content}) {
    return ChatMessage(
      id: id,
      role: role,
      content: content ?? this.content,
      createdAt: createdAt,
      attachments: attachments,
    );
  }
}
