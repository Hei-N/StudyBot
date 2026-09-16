/// Display metadata for one teaching mode, as returned by
/// `GET /api/v1/modes` and `GET/PUT /api/v1/chats/{id}/mode`.
///
/// Mirrors `ModeInfoOut` in API_CONTRACT.md. The set of modes and their
/// wording are backend-owned (`core.teaching_mode`/`core.mode_prompts` in
/// Python) — nothing here duplicates that as business logic; this is pure
/// display data fetched from the engine.
class TeachingModeInfo {
  const TeachingModeInfo({required this.id, required this.displayName, required this.description});

  factory TeachingModeInfo.fromJson(Map<String, dynamic> json) {
    return TeachingModeInfo(
      id: json['id'] as String,
      displayName: json['displayName'] as String,
      description: json['description'] as String,
    );
  }

  /// The stable identifier (`"teach"`, `"homework"`, ...) — what's sent
  /// back to `PUT /chats/{id}/mode` and stored as `Chat.teachingMode`.
  final String id;
  final String displayName;
  final String description;
}
