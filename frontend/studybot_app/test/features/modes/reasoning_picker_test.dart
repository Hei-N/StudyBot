import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/reasoning_mode.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/modes/reasoning_picker.dart';

import '../../support/no_retry_container.dart';
import '../../support/fake_studybot_api.dart';

const _catalog = [
  ReasoningModeInfo(id: 'fast', displayName: 'Fast', description: 'Answers immediately.'),
  ReasoningModeInfo(id: 'deep', displayName: 'Deep Think', description: 'Reasons before answering.'),
];

Chat _chat({String reasoningMode = 'fast'}) => Chat(
  id: 'chat1',
  title: null,
  courseId: null,
  teachingMode: 'teach',
  reasoningMode: reasoningMode,
  createdAt: 'now',
  updatedAt: 'now',
);

Future<ProviderContainer> _pumpPicker(WidgetTester tester, FakeStudyBotApi api) async {
  final container = ProviderContainer(
    overrides: [studyBotApiProvider.overrideWithValue(api)],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  container.read(activeChatIdProvider.notifier).select('chat1');
  await container.read(chatsProvider.future);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: Scaffold(body: ReasoningPicker())),
    ),
  );
  await tester.pumpAndSettle();
  return container;
}

void main() {
  testWidgets('shows Fast by default for a new chat', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()], reasoningModes: _catalog);
    await _pumpPicker(tester, api);

    expect(find.text('Fast'), findsOneWidget);
    expect(find.text('Deep Think'), findsNothing);
  });

  testWidgets('shows Deep Think when the active chat is already in Deep mode', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat(reasoningMode: 'deep')], reasoningModes: _catalog);
    await _pumpPicker(tester, api);

    expect(find.text('Deep Think'), findsOneWidget);
  });

  testWidgets('opening the picker lists both catalog modes with their descriptions', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()], reasoningModes: _catalog);
    await _pumpPicker(tester, api);

    await tester.tap(find.byType(ReasoningPicker));
    await tester.pumpAndSettle();

    expect(find.text('Answers immediately.'), findsOneWidget);
    expect(find.text('Reasons before answering.'), findsOneWidget);
  });

  testWidgets('selecting Deep Think calls the API and updates the displayed mode', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()], reasoningModes: _catalog);
    final container = await _pumpPicker(tester, api);

    await tester.tap(find.byType(ReasoningPicker));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Deep Think').last);
    await tester.pumpAndSettle();

    expect(api.calls, contains('setChatReasoningMode:chat1:deep'));
    expect(container.read(chatsProvider).value!.single.reasoningMode, 'deep');
    expect(find.text('Deep Think'), findsOneWidget);
  });

  testWidgets('renders nothing when there is no active chat', (tester) async {
    final api = FakeStudyBotApi(reasoningModes: _catalog);
    final container = ProviderContainer(overrides: [studyBotApiProvider.overrideWithValue(api)], retry: kNoRetry);
    addTearDown(container.dispose);
    await container.read(chatsProvider.future);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: Scaffold(body: ReasoningPicker())),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(ReasoningPicker), findsOneWidget);
    expect(find.text('Fast'), findsNothing);
    expect(find.text('Deep Think'), findsNothing);
  });
}
