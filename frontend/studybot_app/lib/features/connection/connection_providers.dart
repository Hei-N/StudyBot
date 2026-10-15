import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/chat_websocket_client.dart';
import '../../core/api/connection_config.dart';
import '../../core/api/studybot_api.dart';
import 'managed_backend.dart';

/// The user's engine connection settings (base URL + token). Loaded from
/// local storage on first read; edited from Settings. Nothing here is
/// hardcoded. A development run that started its own engine uses that
/// engine's address and token instead (see [managedBackendProvider]).
class ConnectionConfigNotifier extends Notifier<ConnectionConfig> {
  @override
  ConnectionConfig build() {
    final managed = ref.watch(managedBackendProvider).value;
    if (managed != null) return managed.config;
    _restore();
    return const ConnectionConfig(baseUrl: ConnectionConfig.defaultBaseUrl, token: '');
  }

  Future<void> _restore() async {
    state = await ConnectionConfig.load();
  }

  Future<void> update({String? baseUrl, String? token}) async {
    final next = state.copyWith(baseUrl: baseUrl, token: token);
    state = next;
    await next.save();
  }
}

final connectionConfigProvider = NotifierProvider<ConnectionConfigNotifier, ConnectionConfig>(
  ConnectionConfigNotifier.new,
);

/// Rebuilt automatically whenever [connectionConfigProvider] changes (e.g.
/// the user edits the token in Settings), so every request always uses the
/// current configuration.
final studyBotApiProvider = Provider<StudyBotApi>((ref) {
  final config = ref.watch(connectionConfigProvider);
  final api = StudyBotApi(config);
  ref.onDispose(api.close);
  return api;
});

/// One shared WebSocket client for the whole app session, reused across
/// chats and messages per API_CONTRACT.md. Recreated (and the old
/// connection closed) whenever the connection config changes.
final chatWebSocketClientProvider = Provider<ChatWebSocketClient>((ref) {
  final config = ref.watch(connectionConfigProvider);
  final client = ChatWebSocketClient(config);
  ref.onDispose(client.close);
  return client;
});
