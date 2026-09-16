import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/features/chats/chats_list_view.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';

import '../../support/fake_studybot_api.dart';

Chat _chat(String id, {String? title}) =>
    Chat(id: id, title: title, courseId: null, teachingMode: 'teach', createdAt: 'now', updatedAt: 'now');

Widget _wrap(FakeStudyBotApi api) {
  return ProviderScope(
    overrides: [studyBotApiProvider.overrideWithValue(api)],
    retry: (_, _) => null,
    child: const MaterialApp(home: Scaffold(body: SizedBox(width: 280, child: ChatsListView()))),
  );
}

void main() {
  testWidgets('renders every chat with a display title, most recent first', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat('c1', title: 'Homework help'), _chat('c2')]);
    await tester.pumpWidget(_wrap(api));
    await tester.pumpAndSettle();

    expect(find.text('Homework help'), findsOneWidget);
    expect(find.text('Untitled'), findsOneWidget);
  });

  testWidgets('shows an empty state with no chats', (tester) async {
    final api = FakeStudyBotApi();
    await tester.pumpWidget(_wrap(api));
    await tester.pumpAndSettle();

    expect(find.text('No chats yet'), findsOneWidget);
  });

  testWidgets('tapping the + button creates a new chat and selects it', (tester) async {
    final api = FakeStudyBotApi();
    late final WidgetRef capturedRef;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [studyBotApiProvider.overrideWithValue(api)],
        retry: (_, _) => null,
        child: MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 280,
              child: Consumer(
                builder: (context, ref, _) {
                  capturedRef = ref;
                  return const ChatsListView();
                },
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('New chat'));
    await tester.pumpAndSettle();

    expect(capturedRef.read(chatsProvider).value, hasLength(1));
    expect(capturedRef.read(activeChatIdProvider), isNotNull);
  });
}
