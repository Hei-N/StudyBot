import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/conversation/composer.dart';
import 'package:studybot_app/features/conversation/conversation_providers.dart';

import '../../support/fake_chat_websocket_client.dart';
import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';

Chat _chat() =>
    Chat(id: 'chat1', title: null, courseId: null, teachingMode: 'teach', reasoningMode: 'fast', createdAt: 'now', updatedAt: 'now');

Future<ProviderContainer> _pumpComposer(WidgetTester tester, FakeStudyBotApi api, FakeChatWebSocketClient ws) async {
  final container = ProviderContainer(
    overrides: [studyBotApiProvider.overrideWithValue(api), chatWebSocketClientProvider.overrideWithValue(ws)],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  container.read(activeChatIdProvider.notifier).select('chat1');
  await container.read(chatsProvider.future);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: Scaffold(body: Align(alignment: Alignment.bottomCenter, child: Composer()))),
    ),
  );
  await tester.pumpAndSettle();
  return container;
}

final _sendButton = find.widgetWithIcon(IconButton, Icons.arrow_upward);

void main() {
  testWidgets('the send button is disabled for blank input and enabled once text is entered', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()]);
    await _pumpComposer(tester, api, FakeChatWebSocketClient());

    final sendButton = tester.widget<IconButton>(_sendButton);
    expect(sendButton.onPressed, isNull);

    await tester.enterText(find.byType(TextField), 'Hello');
    await tester.pumpAndSettle();

    final enabledButton = tester.widget<IconButton>(_sendButton);
    expect(enabledButton.onPressed, isNotNull);
  });

  testWidgets('does not send whitespace-only text', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()]);
    final ws = FakeChatWebSocketClient();
    await _pumpComposer(tester, api, ws);

    await tester.enterText(find.byType(TextField), '   ');
    await tester.pumpAndSettle();

    final button = tester.widget<IconButton>(_sendButton);
    expect(button.onPressed, isNull);
    expect(ws.sentMessages, isEmpty);
  });

  testWidgets('Enter sends the message and clears the field', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()]);
    final ws = FakeChatWebSocketClient();
    await _pumpComposer(tester, api, ws);

    await tester.enterText(find.byType(TextField), 'Hello there');
    await tester.pumpAndSettle();
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();

    expect(ws.sentMessages.single.content, 'Hello there');
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, isEmpty);
  });

  testWidgets('Shift+Enter inserts a newline instead of sending', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()]);
    final ws = FakeChatWebSocketClient();
    await _pumpComposer(tester, api, ws);

    await tester.enterText(find.byType(TextField), 'Line one');
    await tester.pumpAndSettle();

    await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
    await tester.pumpAndSettle();

    expect(ws.sentMessages, isEmpty);
  });

  testWidgets('the composer is disabled while a reply is streaming', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()]);
    final ws = FakeChatWebSocketClient();
    final container = await _pumpComposer(tester, api, ws);

    await container.read(conversationProvider.future);
    await container.read(conversationProvider.notifier).send('first message');
    await tester.pumpAndSettle();

    final textField = tester.widget<TextField>(find.byType(TextField));
    expect(textField.enabled, isFalse);
  });
}
