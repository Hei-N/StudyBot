import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/core/models/message.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/courses/courses_providers.dart';
import 'package:studybot_app/features/conversation/conversation_view.dart';
import 'package:studybot_app/features/memory/memory_edit_dialog.dart';

import '../../support/fake_chat_websocket_client.dart';
import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';

Chat _chat({String? courseId}) => Chat(
  id: 'chat1',
  title: 'Chat',
  courseId: courseId,
  teachingMode: 'teach',
  reasoningMode: 'fast',
  createdAt: 'now',
  updatedAt: 'now',
);

Future<ProviderContainer> _pump(WidgetTester tester, FakeStudyBotApi api, {String? activeCourseId}) async {
  final container = ProviderContainer(
    overrides: [studyBotApiProvider.overrideWithValue(api), chatWebSocketClientProvider.overrideWithValue(FakeChatWebSocketClient())],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  if (activeCourseId != null) container.read(activeCourseIdProvider.notifier).select(activeCourseId);
  container.read(activeChatIdProvider.notifier).select('chat1');
  await container.read(chatsProvider.future);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: Scaffold(body: SizedBox(width: 800, child: ConversationView()))),
    ),
  );
  await tester.pumpAndSettle();
  return container;
}

void main() {
  testWidgets('a persisted assistant message shows a Save to Learning Memory action', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()]);
    api.messagesByChat['chat1'] = [
      ChatMessage(id: 1, role: MessageRole.user, content: 'Explain vectors', createdAt: 'now'),
      ChatMessage(id: 2, role: MessageRole.assistant, content: 'A vector has magnitude and direction.', createdAt: 'now'),
    ];

    await _pump(tester, api);

    expect(find.text('Save to Learning Memory'), findsNWidgets(2)); // one per persisted message
  });

  testWidgets('tapping Save to Learning Memory opens the memory dialog', (tester) async {
    final api = FakeStudyBotApi(courses: [], chats: [_chat()]);
    api.messagesByChat['chat1'] = [
      ChatMessage(id: 1, role: MessageRole.assistant, content: 'A vector has magnitude and direction.', createdAt: 'now'),
    ];

    await _pump(tester, api);
    await tester.tap(find.text('Save to Learning Memory').first);
    await tester.pumpAndSettle();

    expect(find.byType(MemoryEditDialog), findsOneWidget);
    expect(find.text('New learning memory'), findsOneWidget);
    // Pre-filled from the message content.
    final summaryField = tester.widget<TextField>(find.widgetWithText(TextField, 'Summary'));
    expect(summaryField.controller!.text, 'A vector has magnitude and direction.');
  });

  testWidgets('saving from chat defaults course scope to the chat\'s own course', (tester) async {
    final physics = Course(
      id: 'physics',
      name: 'Physics',
      code: null,
      term: null,
      description: null,
      createdAt: 'now',
      updatedAt: 'now',
    );
    final api = FakeStudyBotApi(courses: [physics], chats: [_chat(courseId: 'physics')]);
    api.messagesByChat['chat1'] = [
      ChatMessage(id: 1, role: MessageRole.assistant, content: 'Reply text', createdAt: 'now'),
    ];

    await _pump(tester, api, activeCourseId: 'physics');
    await tester.tap(find.text('Save to Learning Memory').first);
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Topic'), 'Vectors');
    await tester.tap(find.text('Create'));
    await tester.pumpAndSettle();

    final created = api.memories.single;
    expect(created.courseId, 'physics');
    expect(created.sourceChatId, 'chat1');
  });
}
