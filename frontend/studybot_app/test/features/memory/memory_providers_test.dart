import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/learning_memory.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/courses/courses_providers.dart';
import 'package:studybot_app/features/memory/memory_providers.dart';

import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';

LearningMemory _memory(String id, {String? courseId, String topic = 'Topic', String kind = 'needs_review'}) =>
    LearningMemory(
      id: id,
      courseId: courseId,
      sourceChatId: null,
      topic: topic,
      kind: kind,
      summary: 'summary',
      status: 'active',
      createdAt: 'now',
      updatedAt: 'now',
    );

void main() {
  test('memoriesProvider fetches every memory', () async {
    final api = FakeStudyBotApi(memories: [_memory('m1'), _memory('m2')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    final memories = await container.read(memoriesProvider.future);

    expect(memories.map((m) => m.id), containsAll(['m1', 'm2']));
  });

  test('create() persists through the API and appears in the list', () async {
    final api = FakeStudyBotApi();
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);
    await container.read(memoriesProvider.future);

    final created = await container
        .read(memoriesProvider.notifier)
        .create(topic: 'Vectors', kind: 'needs_review', summary: 'Mixes x/y.');

    expect(created.topic, 'Vectors');
    expect(container.read(memoriesProvider).value!.map((m) => m.id), contains(created.id));
  });

  test('edit() updates topic/kind/summary', () async {
    final api = FakeStudyBotApi(memories: [_memory('m1', topic: 'Old')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);
    await container.read(memoriesProvider.future);

    await container.read(memoriesProvider.notifier).edit('m1', topic: 'New', kind: 'understands', summary: 'S2');

    final memory = container.read(memoriesProvider).value!.single;
    expect(memory.topic, 'New');
    expect(memory.kind, 'understands');
    expect(memory.summary, 'S2');
  });

  test('edit() with setCourseId unassigns to General', () async {
    final api = FakeStudyBotApi(memories: [_memory('m1', courseId: 'c1')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);
    await container.read(memoriesProvider.future);

    await container
        .read(memoriesProvider.notifier)
        .edit('m1', topic: 'Topic', kind: 'needs_review', summary: 'summary', setCourseId: true, courseId: null);

    expect(container.read(memoriesProvider).value!.single.courseId, isNull);
  });

  test('archive() then restore() round-trips status', () async {
    final api = FakeStudyBotApi(memories: [_memory('m1')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);
    await container.read(memoriesProvider.future);

    await container.read(memoriesProvider.notifier).archive('m1');
    expect(container.read(memoriesProvider).value!.single.status, 'archived');

    await container.read(memoriesProvider.notifier).restore('m1');
    expect(container.read(memoriesProvider).value!.single.status, 'active');
  });

  test('delete() removes it from the list', () async {
    final api = FakeStudyBotApi(memories: [_memory('m1')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);
    await container.read(memoriesProvider.future);

    await container.read(memoriesProvider.notifier).delete('m1');

    expect(container.read(memoriesProvider).value, isEmpty);
  });

  group('activeCourseMemoriesProvider', () {
    test('includes course-specific and global active memories', () async {
      final api = FakeStudyBotApi(
        memories: [_memory('m1', courseId: 'physics'), _memory('m2', courseId: null), _memory('m3', courseId: 'calc')],
      );
      final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
      addTearDown(container.dispose);
      await container.read(memoriesProvider.future);
      container.read(activeCourseIdProvider.notifier).select('physics');

      final visible = container.read(activeCourseMemoriesProvider).map((m) => m.id).toSet();

      expect(visible, {'m1', 'm2'});
      expect(visible, isNot(contains('m3')));
    });

    test('excludes archived memories', () async {
      final api = FakeStudyBotApi(memories: [_memory('m1', courseId: 'physics')]);
      final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
      addTearDown(container.dispose);
      await container.read(memoriesProvider.future);
      container.read(activeCourseIdProvider.notifier).select('physics');
      await container.read(memoriesProvider.notifier).archive('m1');

      expect(container.read(activeCourseMemoriesProvider), isEmpty);
    });
  });
}
