import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/course.dart';
import '../connection/connection_providers.dart';

/// The full course list from `GET /api/v1/courses`. Mutations re-fetch instead
/// of patching local state, so the backend stays authoritative.
class CoursesNotifier extends AsyncNotifier<List<Course>> {
  @override
  Future<List<Course>> build() => _fetch();

  Future<List<Course>> _fetch() => ref.read(studyBotApiProvider).listCourses();

  Future<void> refresh() async {
    state = await AsyncValue.guard(_fetch);
  }

  Future<Course> create({required String name, String? code, String? term, String? description}) async {
    final course = await ref
        .read(studyBotApiProvider)
        .createCourse(name: name, code: code, term: term, description: description);
    await refresh();
    return course;
  }

  Future<Course> edit(
    String courseId, {
    required String name,
    String? code,
    String? term,
    String? description,
  }) async {
    final course = await ref
        .read(studyBotApiProvider)
        .updateCourse(courseId, name: name, code: code, term: term, description: description);
    await refresh();
    return course;
  }

  /// Deletes the course. Its chats and messages are kept and become General.
  Future<void> delete(String courseId) async {
    await ref.read(studyBotApiProvider).deleteCourse(courseId);
    await refresh();
  }
}

final coursesProvider = AsyncNotifierProvider<CoursesNotifier, List<Course>>(CoursesNotifier.new);

/// The course selected in the UI; `null` means "General". The API has no
/// active-course concept (requests are explicit by id), so this is local UI
/// state and is not persisted across restarts.
class ActiveCourseIdNotifier extends Notifier<String?> {
  @override
  String? build() => null;

  void select(String? courseId) => state = courseId;
}

final activeCourseIdProvider = NotifierProvider<ActiveCourseIdNotifier, String?>(ActiveCourseIdNotifier.new);

/// The [Course] for [activeCourseIdProvider], or null for General or while
/// courses are loading.
final activeCourseProvider = Provider<Course?>((ref) {
  final courseId = ref.watch(activeCourseIdProvider);
  if (courseId == null) return null;
  final courses = ref.watch(coursesProvider).value;
  if (courses == null) return null;
  for (final course in courses) {
    if (course.id == courseId) return course;
  }
  return null;
});
