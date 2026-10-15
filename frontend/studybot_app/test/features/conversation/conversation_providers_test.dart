import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
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
    Chat(id: id, title: null, courseId: null, teachingMode: 'teach', reasoningMode: 'fast', createdAt: 'now', updatedAt: 'now');

/// [FakeChatWebSocketClient.emit] delivers over a broadcast [StreamController],
/// which dispatches on a microtask, so tests must yield to the event loop
/// before asserting on state updated from the stream.
Future<void> _flush() => Future<void>.delayed(Duration.zero);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

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
      // Regression: GET .../messages can 404 with CHAT_NOT_FOUND for a chat with no
      // messages; that is an empty chat, not an error to show.
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

  test(
    'a StreamError clears typing state without inserting a fake completed message',
    () async {
      await container.read(conversationProvider.future);
      await container.read(conversationProvider.notifier).send('hi');
      ws.emit(const StreamDelta('partial thinking...'));
      await _flush();

      ws.emit(const StreamError(code: 'MODEL_ERROR', message: 'The model crashed.'));
      await _flush();

      final state = container.read(conversationProvider).value!;
      expect(state.isStreaming, isFalse);
      expect(state.isSending, isFalse);
      expect(container.read(conversationErrorProvider)?.code, 'MODEL_ERROR');
      // Only the optimistic user turn — no assistant message was fabricated
      // from the partial streamed text.
      expect(state.messages, hasLength(1));
      expect(state.messages.single.role, MessageRole.user);
    },
  );

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

  test('switching away mid-stream does not leak the in-flight reply into the new chat', () async {
    api.chats.add(_chat('chat2'));
    api.messagesByChat['chat2'] = [
      ChatMessage.fromJson({'id': 9, 'role': 'user', 'content': 'From chat 2', 'createdAt': 'now'}),
    ];

    await container.read(conversationProvider.future);
    await container.read(conversationProvider.notifier).send('question in chat1');
    ws.emit(const StreamDelta('partial reply for chat1'));
    await _flush();

    // Switch away before chat1's stream completes.
    container.read(activeChatIdProvider.notifier).select('chat2');
    await container.read(conversationProvider.future);

    // Now the (stale, chat1) completion event arrives — it must not touch
    // chat2's now-active state at all.
    ws.emit(
      StreamCompleted(
        ChatMessage.fromJson({'id': 10, 'role': 'assistant', 'content': 'chat1 reply', 'createdAt': 'now'}),
      ),
    );
    await _flush();

    final state = container.read(conversationProvider).value!;
    expect(state.messages, hasLength(1));
    expect(state.messages.single.content, 'From chat 2');
    expect(state.isStreaming, isFalse);
  });

  test('a reply completed while its chat was inactive is there (exactly once) on return', () async {
    // The completion event itself is dropped while inactive (see the test
    // above) — but the backend persisted it regardless, so a plain refetch
    // on return must show it, and only once.
    api.chats.add(_chat('chat2'));

    await container.read(conversationProvider.future);
    await container.read(conversationProvider.notifier).send('question in chat1');

    container.read(activeChatIdProvider.notifier).select('chat2');
    await container.read(conversationProvider.future);

    // The backend finished and persisted the exchange while chat1 wasn't
    // active — simulate that directly in the fake's persisted store.
    api.messagesByChat['chat1'] = [
      ChatMessage.fromJson({'id': 20, 'role': 'user', 'content': 'question in chat1', 'createdAt': 'now'}),
      ChatMessage.fromJson({'id': 21, 'role': 'assistant', 'content': 'chat1 answer', 'createdAt': 'now'}),
    ];

    container.read(activeChatIdProvider.notifier).select('chat1');
    final state = await container.read(conversationProvider.future);

    expect(state.messages, hasLength(2));
    expect(state.messages.where((m) => m.role == MessageRole.assistant), hasLength(1));
    expect(state.messages.last.content, 'chat1 answer');
    expect(state.isSending, isFalse);
    expect(state.isStreaming, isFalse);
  });

  test(
    're-subscribes when chatWebSocketClientProvider produces a new client instance '
    '(e.g. ConnectionConfigNotifier\'s async restore completing after the first subscription)',
    () async {
      // Regression: chatWebSocketClientProvider rebuilds (a new ChatWebSocketClient)
      // whenever connectionConfigProvider changes, which happens once early when
      // ConnectionConfigNotifier's async restore resolves. If ConversationNotifier
      // stayed subscribed to the old client's stream, later events never reached the
      // UI until the chat was reloaded.
      SharedPreferences.setMockInitialValues({});
      final wsClients = <FakeChatWebSocketClient>[];
      final localApi = FakeStudyBotApi(chats: [_chat('chatX')]);
      final localContainer = ProviderContainer(
        overrides: [
          studyBotApiProvider.overrideWithValue(localApi),
          chatWebSocketClientProvider.overrideWith((ref) {
            ref.watch(connectionConfigProvider); // mirrors the real provider's dependency
            final client = FakeChatWebSocketClient();
            wsClients.add(client);
            return client;
          }),
        ],
        retry: kNoRetry,
      );
      addTearDown(localContainer.dispose);
      // A real ConversationView keeps conversationProvider watched while a chat is
      // open; without a listener, Riverpod would not recompute dependents when
      // connectionConfigProvider changes.
      localContainer.listen(conversationProvider, (_, _) {});
      localContainer.read(activeChatIdProvider.notifier).select('chatX');

      // Subscribes to wsClients[0].
      await localContainer.read(conversationProvider.future);
      expect(wsClients, hasLength(1));

      // Change the connection config after subscribing: this must create a second
      // ChatWebSocketClient, and the notifier must re-subscribe to it on its own.
      await localContainer.read(connectionConfigProvider.notifier).update(token: 'later-token');
      await _flush();
      expect(wsClients, hasLength(2));

      await localContainer.read(conversationProvider.notifier).send('hello');
      // From here on events arrive only on the new client.
      wsClients.last.emit(const StreamDelta('hi there'));
      await _flush();

      final state = localContainer.read(conversationProvider).value!;
      expect(state.streamingText, 'hi there');
    },
  );
}
