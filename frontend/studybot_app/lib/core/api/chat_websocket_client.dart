import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../models/message.dart';
import 'chat_stream_event.dart';
import 'connection_config.dart';

/// One long-lived WebSocket connection to `/api/v1/ws/chat`, reused across
/// chats and messages exactly as API_CONTRACT.md describes. This is the
/// only place that speaks the `send_message`/`message_started`/`delta`/
/// `message_completed`/`error` JSON protocol — callers get a typed
/// [ChatStreamEvent] stream instead.
///
/// Connection is lazy (established on first [sendMessage]) and is not
/// automatically retried on drop — [StreamDisconnected] is surfaced once
/// and a subsequent [sendMessage] call reconnects. Kept deliberately simple
/// for this foundation stage rather than adding backoff/retry policy.
class ChatWebSocketClient {
  ChatWebSocketClient(this.config);

  final ConnectionConfig config;

  WebSocketChannel? _channel;
  StreamController<ChatStreamEvent>? _controller;
  StreamSubscription<dynamic>? _subscription;

  bool get isConnected => _channel != null;

  Stream<ChatStreamEvent> get events {
    _controller ??= StreamController<ChatStreamEvent>.broadcast();
    return _controller!.stream;
  }

  Future<void> _ensureConnected() async {
    if (_channel != null) return;

    final uri = config.wsBase.replace(
      path: '${config.wsBase.path}/api/v1/ws/chat'.replaceAll('//', '/'),
    );
    final channel = IOWebSocketChannel.connect(uri, headers: {'Authorization': 'Bearer ${config.token}'});
    _channel = channel;

    _controller ??= StreamController<ChatStreamEvent>.broadcast();

    _subscription = channel.stream.listen(
      (raw) => _handleRaw(raw),
      onDone: () => _handleDisconnect(),
      onError: (Object _) => _handleDisconnect(),
      cancelOnError: true,
    );

    // Surface a connection failure (e.g. bad token, engine down) as soon as
    // the handshake actually fails, rather than only on first send.
    try {
      await channel.ready;
    } catch (_) {
      _handleDisconnect();
      rethrow;
    }
  }

  void _handleRaw(dynamic raw) {
    final Map<String, dynamic> json;
    try {
      json = jsonDecode(raw as String) as Map<String, dynamic>;
    } catch (_) {
      return;
    }

    switch (json['type']) {
      case 'message_started':
        _controller?.add(StreamStarted(json['chatId'] as String? ?? ''));
      case 'delta':
        _controller?.add(StreamDelta(json['content'] as String? ?? ''));
      case 'message_completed':
        final messageJson = json['message'] as Map<String, dynamic>?;
        _controller?.add(StreamCompleted(messageJson == null ? null : ChatMessage.fromJson(messageJson)));
      case 'error':
        _controller?.add(
          StreamError(
            code: json['code'] as String? ?? 'INTERNAL_ERROR',
            message: json['message'] as String? ?? 'Something went wrong.',
          ),
        );
    }
  }

  void _handleDisconnect() {
    _channel = null;
    _subscription?.cancel();
    _subscription = null;
    _controller?.add(const StreamDisconnected());
  }

  /// Sends one `send_message` frame, connecting first if necessary.
  Future<void> sendMessage({required String chatId, required String content}) async {
    await _ensureConnected();
    _channel!.sink.add(jsonEncode({'type': 'send_message', 'chat_id': chatId, 'content': content}));
  }

  Future<void> close() async {
    await _subscription?.cancel();
    await _channel?.sink.close();
    await _controller?.close();
    _channel = null;
    _subscription = null;
    _controller = null;
  }
}
