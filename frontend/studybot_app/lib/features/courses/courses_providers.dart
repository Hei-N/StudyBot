import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/course.dart';
import '../connection/connection_providers.dart';

/// The full course list, fetched from `GET /api/v1/courses`. Mutations
/// (create/update/delete) re-fetch afterward rather than optimistically
/// patching local state — simpler and always consistent with the backend,
/// which remains authoritative.
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

  /// Deletes the course. Per API_CONTRACT.md / Stage 4 semantics, this
  /// never deletes chats or messages — they become General (unassigned).
  Future<void> delete(String courseId) async {
    await ref.read(studyBotApiProvider).deleteCourse(courseId);
    await refresh();
  }
}

final coursesProvider = AsyncNotifierProvider<CoursesNotifier, List<Course>>(CoursesNotifier.new);

/// The course currently selected in the UI. `null` means "General" — there
/// is no server-side "active course" concept for the API to track (each
/// request is explicit by id, per API_CONTRACT.md), so this is purely
/// local UI state and is not persisted across restarts.
class ActiveCourseIdNotifier extends Notifier<String?> {
  @override
  String? build() => null;

  void select(String? courseId) => state = courseId;
}

final activeCourseIdProvider = NotifierProvider<ActiveCourseIdNotifier, String?>(ActiveCourseIdNotifier.new);

/// The [Course] object for [activeCourseIdProvider], or null for General /
/// while courses are still loading.
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
