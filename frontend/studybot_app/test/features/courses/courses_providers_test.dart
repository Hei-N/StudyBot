import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/courses/courses_providers.dart';

import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';

Course _course(String id, String name) =>
    Course(id: id, name: name, code: null, term: null, description: null, createdAt: 'now', updatedAt: 'now');

void main() {
  test('coursesProvider loads the initial list from the API', () async {
    final api = FakeStudyBotApi(courses: [_course('c1', 'Physics I')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    final courses = await container.read(coursesProvider.future);
    expect(courses, hasLength(1));
    expect(courses.single.name, 'Physics I');
  });

  test('create() adds a course and refreshes the list', () async {
    final api = FakeStudyBotApi();
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(coursesProvider.future);
    await container.read(coursesProvider.notifier).create(name: 'New Course');

    final courses = container.read(coursesProvider).value!;
    expect(courses, hasLength(1));
    expect(courses.single.name, 'New Course');
  });

  test('delete() removes the course after the backend confirms', () async {
    final api = FakeStudyBotApi(courses: [_course('c1', 'Physics I')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(coursesProvider.future);
    await container.read(coursesProvider.notifier).delete('c1');

    expect(container.read(coursesProvider).value, isEmpty);
  });

  test('activeCourseIdProvider defaults to null (General) and is purely local UI state', () {
    final container = ProviderContainer(retry: kNoRetry);
    addTearDown(container.dispose);

    expect(container.read(activeCourseIdProvider), isNull);
    container.read(activeCourseIdProvider.notifier).select('c1');
    expect(container.read(activeCourseIdProvider), 'c1');
  });

  test('activeCourseProvider resolves the full Course object for the active id', () async {
    final api = FakeStudyBotApi(courses: [_course('c1', 'Physics I'), _course('c2', 'Chemistry')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(coursesProvider.future);
    container.read(activeCourseIdProvider.notifier).select('c2');

    expect(container.read(activeCourseProvider)?.name, 'Chemistry');
  });

  test('activeCourseProvider is null for General (no active id)', () async {
    final api = FakeStudyBotApi(courses: [_course('c1', 'Physics I')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(coursesProvider.future);
    expect(container.read(activeCourseProvider), isNull);
  });
}
