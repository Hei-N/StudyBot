import 'dart:async';

import 'package:studybot_app/core/api/chat_stream_event.dart';
import 'package:studybot_app/core/api/chat_websocket_client.dart';
import 'package:studybot_app/core/api/connection_config.dart';

const _testConfig = ConnectionConfig(baseUrl: 'ws://fake', token: 'fake-token');

/// A fake [ChatWebSocketClient] that never opens a real socket. Tests push
/// [ChatStreamEvent]s directly via [emit] to simulate what the server would
/// send, and inspect [sentMessages] to assert what was sent.
class FakeChatWebSocketClient extends ChatWebSocketClient {
  FakeChatWebSocketClient() : super(_testConfig);

  final _controller = StreamController<ChatStreamEvent>.broadcast();
  final List<({String chatId, String content})> sentMessages = [];

  @override
  Stream<ChatStreamEvent> get events => _controller.stream;

  @override
  Future<void> sendMessage({required String chatId, required String content}) async {
    sentMessages.add((chatId: chatId, content: content));
  }

  void emit(ChatStreamEvent event) => _controller.add(event);

  @override
  Future<void> close() async {
    await _controller.close();
  }
}
