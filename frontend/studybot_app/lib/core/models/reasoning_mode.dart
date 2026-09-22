/// Display metadata for one reasoning mode, as returned by
/// `GET /api/v1/reasoning-modes` and `GET/PUT /api/v1/chats/{id}/reasoning-mode`.
///
/// Mirrors `ModeInfoOut` in API_CONTRACT.md — the same shape as
/// [TeachingModeInfo], but a distinct type: reasoning mode is a completely
/// separate concept from teaching mode. Teaching mode
/// (Teach/Homework/Quick/Practice/Exam) controls instructional behavior;
/// reasoning mode (Fast/Deep) controls the model's inference-time
/// "thinking" depth and latency, and never affects the system prompt. A
/// chat can be in any combination of the two. The set of modes and their
/// wording are backend-owned (`core.reasoning_mode` in Python) — nothing
/// here duplicates that as business logic; this is pure display data
/// fetched from the engine.
class ReasoningModeInfo {
  const ReasoningModeInfo({required this.id, required this.displayName, required this.description});

  factory ReasoningModeInfo.fromJson(Map<String, dynamic> json) {
    return ReasoningModeInfo(
      id: json['id'] as String,
      displayName: json['displayName'] as String,
      description: json['description'] as String,
    );
  }

  /// The stable identifier (`"fast"`, `"deep"`) — what's sent back to
  /// `PUT /chats/{id}/reasoning-mode` and stored as `Chat.reasoningMode`.
  final String id;
  final String displayName;
  final String description;
}
