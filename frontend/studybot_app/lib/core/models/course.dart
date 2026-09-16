/// A course, as returned by `GET/POST/PUT /api/v1/courses...`.
///
/// Mirrors `CourseOut` in API_CONTRACT.md exactly. Study Bot never fakes a
/// database row named "General" — a chat with no course is represented by
/// `Chat.courseId == null`, not by a synthetic `Course`.
class Course {
  const Course({
    required this.id,
    required this.name,
    required this.code,
    required this.term,
    required this.description,
    required this.createdAt,
    required this.updatedAt,
  });

  factory Course.fromJson(Map<String, dynamic> json) {
    return Course(
      id: json['id'] as String,
      name: json['name'] as String,
      code: json['code'] as String?,
      term: json['term'] as String?,
      description: json['description'] as String?,
      createdAt: json['createdAt'] as String,
      updatedAt: json['updatedAt'] as String,
    );
  }

  final String id;
  final String name;
  final String? code;
  final String? term;
  final String? description;
  final String createdAt;
  final String updatedAt;

  /// A short "PHY 215 · Fall 2026"-style subtitle, or null if neither is set.
  String? get subtitle {
    final parts = [code, term].whereType<String>().where((s) => s.isNotEmpty);
    return parts.isEmpty ? null : parts.join(' · ');
  }
}
