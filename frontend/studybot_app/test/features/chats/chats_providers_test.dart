import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/courses/courses_providers.dart';

import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';

Chat _chat(String id, {String? courseId, String mode = 'teach', String reasoningMode = 'fast', String? title}) =>
    Chat(
      id: id,
      title: title,
      courseId: courseId,
      teachingMode: mode,
      reasoningMode: reasoningMode,
      createdAt: 'now',
      updatedAt: 'now',
    );

void main() {
  test('chatsProvider requests General (course_id=none) when no course is active', () async {
    final api = FakeStudyBotApi(chats: [_chat('chat1'), _chat('chat2', courseId: 'c1')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    final chats = await container.read(chatsProvider.future);
    expect(chats.map((c) => c.id), ['chat1']);
    expect(api.calls, contains('listChats:none'));
  });

  test('chatsProvider refetches when the active course changes', () async {
    final api = FakeStudyBotApi(chats: [_chat('chat1'), _chat('chat2', courseId: 'c1')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(chatsProvider.future);
    container.read(activeCourseIdProvider.notifier).select('c1');

    final chats = await container.read(chatsProvider.future);
    expect(chats.map((c) => c.id), ['chat2']);
  });

  test('create() adds a chat under the active course and it appears in the list', () async {
    final api = FakeStudyBotApi();
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    container.read(activeCourseIdProvider.notifier).select('c1');
    await container.read(chatsProvider.future);
    final created = await container.read(chatsProvider.notifier).create();

    expect(created.courseId, 'c1');
    expect(container.read(chatsProvider).value!.map((c) => c.id), contains(created.id));
  });

  test(
    'a freshly created (unpersisted) chat stays visible even though the backend '
    'would not list it yet — API_CONTRACT.md "Lazy persistence"',
    () async {
      // Regression test: found via real end-to-end verification against the
      // running API server — a brand-new chat has no database row until its
      // first message completes, so GET /chats excludes it. create() must
      // not blindly refresh() afterward, or the chat the user just made
      // would disappear immediately.
      final api = FakeStudyBotApi();
      final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
      addTearDown(container.dispose);

      await container.read(chatsProvider.future);
      final created = await container.read(chatsProvider.notifier).create();
      api.phantomChatIds.add(created.id);

      // The real backend's GET /chats would exclude this id entirely right
      // now — confirm the fake agrees, then confirm our provider still
      // shows it because it patched state locally instead of refreshing.
      expect(await api.listChats(), isNot(contains(created)));
      expect(container.read(chatsProvider).value!.map((c) => c.id), contains(created.id));
    },
  );

  test('renaming or setting the mode of an unpersisted chat keeps it visible locally', () async {
    final api = FakeStudyBotApi();
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(chatsProvider.future);
    final created = await container.read(chatsProvider.notifier).create();
    api.phantomChatIds.add(created.id);

    await container.read(chatsProvider.notifier).rename(created.id, 'New title');
    await container.read(chatsProvider.notifier).setMode(created.id, 'quick');

    final chat = container.read(chatsProvider).value!.singleWhere((c) => c.id == created.id);
    expect(chat.title, 'New title');
    expect(chat.teachingMode, 'quick');
  });

  test('rename() and delete() go through the API and refresh the list', () async {
    final api = FakeStudyBotApi(chats: [_chat('chat1', title: 'Old')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(chatsProvider.future);
    await container.read(chatsProvider.notifier).rename('chat1', 'New title');
    expect(container.read(chatsProvider).value!.single.title, 'New title');

    await container.read(chatsProvider.notifier).delete('chat1');
    expect(container.read(chatsProvider).value, isEmpty);
  });

  group('activeChatIdProvider auto-selection', () {
    test('selects the first (most recent) chat once the list loads, if nothing is selected', () async {
      final api = FakeStudyBotApi(chats: [_chat('chat1'), _chat('chat2')]);
      final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
      addTearDown(container.dispose);

      container.listen(activeChatIdProvider, (_, _) {});
      await container.read(chatsProvider.future);
      // Allow the ref.listen callback (registered in build()) to run.
      await Future<void>.delayed(Duration.zero);

      expect(container.read(activeChatIdProvider), 'chat1');
    });

    test('falls back to another chat when the selected one is deleted', () async {
      final api = FakeStudyBotApi(chats: [_chat('chat1'), _chat('chat2')]);
      final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
      addTearDown(container.dispose);

      container.listen(activeChatIdProvider, (_, _) {});
      await container.read(chatsProvider.future);
      await Future<void>.delayed(Duration.zero);
      container.read(activeChatIdProvider.notifier).select('chat2');

      await container.read(chatsProvider.notifier).delete('chat2');
      await Future<void>.delayed(Duration.zero);

      expect(container.read(activeChatIdProvider), 'chat1');
    });

    test('becomes null when the last chat is deleted', () async {
      final api = FakeStudyBotApi(chats: [_chat('chat1')]);
      final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
      addTearDown(container.dispose);

      container.listen(activeChatIdProvider, (_, _) {});
      await container.read(chatsProvider.future);
      await Future<void>.delayed(Duration.zero);

      await container.read(chatsProvider.notifier).delete('chat1');
      await Future<void>.delayed(Duration.zero);

      expect(container.read(activeChatIdProvider), isNull);
    });

    test('keeps a still-valid selection when the list changes', () async {
      final api = FakeStudyBotApi(chats: [_chat('chat1'), _chat('chat2')]);
      final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
      addTearDown(container.dispose);

      container.listen(activeChatIdProvider, (_, _) {});
      await container.read(chatsProvider.future);
      await Future<void>.delayed(Duration.zero);
      container.read(activeChatIdProvider.notifier).select('chat2');

      await container.read(chatsProvider.notifier).refresh();
      await Future<void>.delayed(Duration.zero);

      expect(container.read(activeChatIdProvider), 'chat2');
    });
  });

  test('setMode persists through the API and updates Chat.teachingMode', () async {
    final api = FakeStudyBotApi(
      chats: [_chat('chat1')],
      modes: const [],
    );
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(chatsProvider.future);
    await container.read(chatsProvider.notifier).setMode('chat1', 'quick_answer');

    expect(container.read(chatsProvider).value!.single.teachingMode, 'quick_answer');
    expect(api.calls, contains('setChatMode:chat1:quick_answer'));
  });

  test('setReasoningMode persists through the API and updates Chat.reasoningMode', () async {
    final api = FakeStudyBotApi(chats: [_chat('chat1')], reasoningModes: const []);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(chatsProvider.future);
    await container.read(chatsProvider.notifier).setReasoningMode('chat1', 'deep');

    expect(container.read(chatsProvider).value!.single.reasoningMode, 'deep');
    expect(api.calls, contains('setChatReasoningMode:chat1:deep'));
  });

  test('setReasoningMode does not change teachingMode, and vice versa', () async {
    final api = FakeStudyBotApi(chats: [_chat('chat1', mode: 'homework')]);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(chatsProvider.future);
    await container.read(chatsProvider.notifier).setReasoningMode('chat1', 'deep');

    final chat = container.read(chatsProvider).value!.single;
    expect(chat.teachingMode, 'homework'); // untouched
    expect(chat.reasoningMode, 'deep');

    await container.read(chatsProvider.notifier).setMode('chat1', 'exam');
    final after = container.read(chatsProvider).value!.single;
    expect(after.reasoningMode, 'deep'); // untouched
    expect(after.teachingMode, 'exam');
  });

  test('a freshly created chat defaults to fast reasoning mode', () async {
    final api = FakeStudyBotApi();
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(chatsProvider.future);
    final created = await container.read(chatsProvider.notifier).create();

    expect(created.reasoningMode, 'fast');
  });

  test('switching the active chat shows each chat\'s own reasoning mode (no bleed-through)', () async {
    final api = FakeStudyBotApi(
      chats: [_chat('chat1', reasoningMode: 'deep'), _chat('chat2', reasoningMode: 'fast')],
    );
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(chatsProvider.future);

    container.read(activeChatIdProvider.notifier).select('chat1');
    expect(container.read(activeChatProvider)?.reasoningMode, 'deep');

    container.read(activeChatIdProvider.notifier).select('chat2');
    expect(container.read(activeChatProvider)?.reasoningMode, 'fast');

    container.read(activeChatIdProvider.notifier).select('chat1');
    expect(container.read(activeChatProvider)?.reasoningMode, 'deep');
  });
}
