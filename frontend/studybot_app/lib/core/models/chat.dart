/// A chat, as returned by the `/api/v1/chats...` endpoints.
///
/// Mirrors `ChatOut` in API_CONTRACT.md exactly. `courseId == null` means
/// the chat is unassigned ("General") — there is no separate flag for it.
class Chat {
  const Chat({
    required this.id,
    required this.title,
    required this.courseId,
    required this.teachingMode,
    required this.createdAt,
    required this.updatedAt,
  });

  factory Chat.fromJson(Map<String, dynamic> json) {
    return Chat(
      id: json['id'] as String,
      title: json['title'] as String?,
      courseId: json['courseId'] as String?,
      teachingMode: json['teachingMode'] as String,
      createdAt: json['createdAt'] as String,
      updatedAt: json['updatedAt'] as String,
    );
  }

  final String id;
  final String? title;
  final String? courseId;
  final String teachingMode;
  final String createdAt;
  final String updatedAt;

  /// What the CLI would show for an untitled chat — used identically here
  /// so a chat's display name is consistent across both interfaces.
  String get displayTitle => (title == null || title!.trim().isEmpty) ? 'Untitled' : title!;

  Chat copyWith({String? title, String? courseId, bool clearCourseId = false, String? teachingMode}) {
    return Chat(
      id: id,
      title: title ?? this.title,
      courseId: clearCourseId ? null : (courseId ?? this.courseId),
      teachingMode: teachingMode ?? this.teachingMode,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
  }
}
