/// Catalog entry for `GET /api/v1/memory-kinds` — a stable id plus
/// natural-language display metadata. Always fetched from the backend
/// catalog, never hardcoded — mirrors `TeachingModeInfo`/`ReasoningModeInfo`.
class MemoryKindInfo {
  const MemoryKindInfo({required this.id, required this.displayName, required this.description});

  factory MemoryKindInfo.fromJson(Map<String, dynamic> json) {
    return MemoryKindInfo(
      id: json['id'] as String,
      displayName: json['displayName'] as String,
      description: json['description'] as String,
    );
  }

  final String id;
  final String displayName;
  final String description;
}

/// One durable, course-scoped learning fact, as returned by
/// `GET/POST/PATCH /api/v1/memories...`. Mirrors `LearningMemoryOut` in
/// API_CONTRACT.md. Separate from [ChatMessage]: a memory is a single,
/// deliberately created fact, not a transcript or summary, and carries no
/// mastery score.
class LearningMemory {
  const LearningMemory({
    required this.id,
    required this.courseId,
    required this.sourceChatId,
    required this.topic,
    required this.kind,
    required this.summary,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
  });

  factory LearningMemory.fromJson(Map<String, dynamic> json) {
    return LearningMemory(
      id: json['id'] as String,
      courseId: json['courseId'] as String?,
      sourceChatId: json['sourceChatId'] as String?,
      topic: json['topic'] as String,
      kind: json['kind'] as String,
      summary: json['summary'] as String,
      status: json['status'] as String,
      createdAt: json['createdAt'] as String,
      updatedAt: json['updatedAt'] as String,
    );
  }

  final String id;
  final String? courseId;
  final String? sourceChatId;
  final String topic;
  final String kind;
  final String summary;
  final String status;
  final String createdAt;
  final String updatedAt;

  bool get isActive => status == 'active';
  bool get isArchived => status == 'archived';
}
