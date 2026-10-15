/// Display metadata for one reasoning mode, as returned by
/// `GET /api/v1/reasoning-modes` and `GET/PUT /api/v1/chats/{id}/reasoning-mode`.
///
/// Mirrors `ModeInfoOut` in API_CONTRACT.md. It has the same shape as
/// [TeachingModeInfo] but is a distinct concept: teaching mode controls
/// instructional behavior, reasoning mode (Fast/Deep) controls the model's
/// inference-time thinking depth and latency and never affects the system
/// prompt. A chat can use any combination. The modes and their wording are
/// owned by the backend (`core.reasoning_mode`); this is display data only.
class ReasoningModeInfo {
  const ReasoningModeInfo({required this.id, required this.displayName, required this.description});

  factory ReasoningModeInfo.fromJson(Map<String, dynamic> json) {
    return ReasoningModeInfo(
      id: json['id'] as String,
      displayName: json['displayName'] as String,
      description: json['description'] as String,
    );
  }

  /// The stable identifier (`"fast"`, `"deep"`), sent to
  /// `PUT /chats/{id}/reasoning-mode` and stored as `Chat.reasoningMode`.
  final String id;
  final String displayName;
  final String description;
}
