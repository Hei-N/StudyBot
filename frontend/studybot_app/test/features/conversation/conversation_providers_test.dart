import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/api/api_exception.dart';
import 'package:studybot_app/core/api/chat_stream_event.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/message.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/conversation/conversation_providers.dart';

import '../../support/fake_chat_websocket_client.dart';
import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';

Chat _chat(String id) =>
    Chat(id: id, title: null, courseId: null, teachingMode: 'teach', createdAt: 'now', updatedAt: 'now');

/// [FakeChatWebSocketClient.emit] delivers over a broadcast [StreamController],
/// which dispatches to listeners on a microtask rather than synchronously —
/// so tests must yield back to the event loop before asserting on state
/// that [ConversationNotifier] updates from its stream subscription.
Future<void> _flush() => Future<void>.delayed(Duration.zero);

void main() {
  late FakeStudyBotApi api;
  late FakeChatWebSocketClient ws;
  late ProviderContainer container;

  setUp(() {
    api = FakeStudyBotApi(chats: [_chat('chat1')]);
    ws = FakeChatWebSocketClient();
    container = ProviderContainer(
      overrides: [studyBotApiProvider.overrideWithValue(api), chatWebSocketClientProvider.overrideWithValue(ws)],
      retry: kNoRetry,
    );
    container.read(activeChatIdProvider.notifier).select('chat1');
  });

  tearDown(() => container.dispose());

  test('loads persisted history for the active chat', () async {
    api.messagesByChat['chat1'] = [
      ChatMessage.fromJson({'id': 1, 'role': 'user', 'content': 'Hi', 'createdAt': 'now'}),
    ];

    final state = await container.read(conversationProvider.future);
    expect(state.messages, hasLength(1));
    expect(state.isStreaming, isFalse);
    expect(state.isSending, isFalse);
  });

  test(
    'treats CHAT_NOT_FOUND from an unpersisted (never-messaged) chat as an empty '
    'chat, not an error — API_CONTRACT.md "Lazy persistence"',
    () async {
      // Regression test: found via real end-to-end verification against the
      // running API server — GET .../messages 404s with CHAT_NOT_FOUND for a
      // chat that has no messages yet, which is a completely normal state
      // for a freshly created chat, not a real failure to surface as an
      // error screen.
      api.phantomChatIds.add('chat1');

      final state = await container.read(conversationProvider.future);
      expect(state.messages, isEmpty);
    },
  );

  test('other API errors (not CHAT_NOT_FOUND) still surface as a real error', () async {
    api.nextError = const ApiException(code: ApiErrorCode.disconnected, message: 'No route to host.');

    await expectLater(container.read(conversationProvider.future), throwsA(isA<ApiException>()));
  });

  test('send() optimistically adds the user message and marks isSending', () async {
    await container.read(conversationProvider.future);

    await container.read(conversationProvider.notifier).send('Explain derivatives');

    final state = container.read(conversationProvider).value!;
    expect(state.isSending, isTrue);
    expect(state.messages.single.isPending, isTrue);
    expect(state.messages.single.content, 'Explain derivatives');
    expect(ws.sentMessages.single.content, 'Explain derivatives');
  });

  test('ignores blank/whitespace-only input', () async {
    await container.read(conversationProvider.future);

    await container.read(conversationProvider.notifier).send('   ');

    expect(ws.sentMessages, isEmpty);
    expect(container.read(conversationProvider).value!.messages, isEmpty);
  });

  test('does not send a second message while one is already streaming', () async {
    await container.read(conversationProvider.future);
    final notifier = container.read(conversationProvider.notifier);

    await notifier.send('first');
    await notifier.send('second');

    expect(ws.sentMessages, hasLength(1));
    expect(ws.sentMessages.single.content, 'first');
  });

  test('accumulates delta events into the streaming buffer', () async {
    await container.read(conversationProvider.future);
    await container.read(conversationProvider.notifier).send('hi');

    ws.emit(const StreamStarted('chat1'));
    ws.emit(const StreamDelta('The '));
    ws.emit(const StreamDelta('answer '));
    ws.emit(const StreamDelta('is 42.'));
    await _flush();

    final state = container.read(conversationProvider).value!;
    expect(state.streamingText, 'The answer is 42.');
    expect(state.isStreaming, isTrue);
    expect(state.isSending, isTrue);
  });

  test('replaces the streaming buffer with the final persisted message on completion', () async {
    await container.read(conversationProvider.future);
    await container.read(conversationProvider.notifier).send('hi');

    ws.emit(const StreamDelta('partial'));
    ws.emit(
      StreamCompleted(
        ChatMessage.fromJson({'id': 5, 'role': 'assistant', 'content': 'partial and final', 'createdAt': 'now'}),
      ),
    );
    await _flush();

    final state = container.read(conversationProvider).value!;
    expect(state.isStreaming, isFalse);
    expect(state.isSending, isFalse);
    // The optimistic user turn plus the one persisted assistant turn — no
    // duplicate assistant bubble left over from the streaming buffer.
    expect(state.messages, hasLength(2));
    expect(state.messages.last.content, 'partial and final');
    expect(state.messages.last.isPending, isFalse);
  });

  test('a StreamError clears streaming state and surfaces via conversationErrorProvider', () async {
    await container.read(conversationProvider.future);
    await container.read(conversationProvider.notifier).send('hi');

    ws.emit(const StreamError(code: 'MODEL_ERROR', message: 'The model crashed.'));
    await _flush();

    final state = container.read(conversationProvider).value!;
    expect(state.isStreaming, isFalse);
    expect(state.isSending, isFalse);
    expect(container.read(conversationErrorProvider)?.code, 'MODEL_ERROR');
  });

  test('a StreamDisconnected event clears streaming state and surfaces a disconnected error', () async {
    await container.read(conversationProvider.future);
    await container.read(conversationProvider.notifier).send('hi');

    ws.emit(const StreamDisconnected());
    await _flush();

    final state = container.read(conversationProvider).value!;
    expect(state.isSending, isFalse);
    expect(container.read(conversationErrorProvider)?.code, 'DISCONNECTED');
  });

  test('stream events are ignored once nothing is being sent (no stray state changes)', () async {
    await container.read(conversationProvider.future);

    ws.emit(const StreamDelta('should be ignored'));
    await _flush();

    final state = container.read(conversationProvider).value!;
    expect(state.isStreaming, isFalse);
    expect(state.messages, isEmpty);
  });

  test('switching the active chat loads that chat\'s own history', () async {
    api.chats.add(_chat('chat2'));
    api.messagesByChat['chat2'] = [
      ChatMessage.fromJson({'id': 9, 'role': 'user', 'content': 'From chat 2', 'createdAt': 'now'}),
    ];

    await container.read(conversationProvider.future);
    container.read(activeChatIdProvider.notifier).select('chat2');

    final state = await container.read(conversationProvider.future);
    expect(state.messages.single.content, 'From chat 2');
  });
}
