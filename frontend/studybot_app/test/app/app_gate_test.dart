import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:studybot_app/app/app.dart';
import 'package:studybot_app/core/api/connection_config.dart';
import 'package:studybot_app/core/models/health.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/shell/app_shell.dart';
import 'package:studybot_app/features/status/status_providers.dart';

import '../support/fake_chat_websocket_client.dart';
import '../support/fake_studybot_api.dart';
import '../support/no_retry_container.dart';
import '../support/static_engine_health_notifier.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('shows the connection setup screen when nothing is configured', (tester) async {
    await tester.pumpWidget(ProviderScope(retry: (_, _) => null, child: const MaterialApp(home: AppGate())));
    await tester.pumpAndSettle();

    expect(find.text('Connect to Study Bot'), findsOneWidget);
    expect(find.byType(AppShell), findsNothing);
  });

  testWidgets('shows "Engine unavailable" when configured but the engine cannot be reached', (tester) async {
    final api = FakeStudyBotApi();
    final container = ProviderContainer(
      overrides: [
        connectionConfigProvider.overrideWith(
          () => _PreconfiguredConnectionNotifier(const ConnectionConfig(baseUrl: 'http://127.0.0.1:9', token: 't')),
        ),
        studyBotApiProvider.overrideWithValue(api),
        chatWebSocketClientProvider.overrideWithValue(FakeChatWebSocketClient()),
        engineHealthProvider.overrideWith(() => StaticEngineHealthNotifier(error: Exception('unreachable'))),
      ],
      retry: kNoRetry,
    );
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const MaterialApp(home: AppGate())),
    );
    await tester.pumpAndSettle();

    expect(find.text('Engine unavailable'), findsOneWidget);
    expect(find.byType(AppShell), findsNothing);
  });

  testWidgets('says Ollama is not running when the engine is up but Ollama is not reachable', (tester) async {
    final api = FakeStudyBotApi();
    final container = ProviderContainer(
      overrides: [
        connectionConfigProvider.overrideWith(
          () => _PreconfiguredConnectionNotifier(const ConnectionConfig(baseUrl: 'http://127.0.0.1:9', token: 't')),
        ),
        studyBotApiProvider.overrideWithValue(api),
        chatWebSocketClientProvider.overrideWithValue(FakeChatWebSocketClient()),
        engineHealthProvider.overrideWith(
          () => StaticEngineHealthNotifier(
            health: const EngineHealth(
              apiVersion: '1',
              status: 'ok',
              provider: 'ollama',
              model: 'qwen3:4b',
              providerReachable: false,
              modelAvailable: null,
            ),
          ),
        ),
      ],
      retry: kNoRetry,
    );
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const MaterialApp(home: AppGate())),
    );
    await tester.pumpAndSettle();

    expect(find.text('Ollama is not running'), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
    expect(find.byType(AppShell), findsNothing);
  });

  testWidgets('shows the app shell once configured and healthy', (tester) async {
    final api = FakeStudyBotApi();
    final container = ProviderContainer(
      overrides: [
        connectionConfigProvider.overrideWith(
          () =>
              _PreconfiguredConnectionNotifier(const ConnectionConfig(baseUrl: 'http://127.0.0.1:8765', token: 't')),
        ),
        studyBotApiProvider.overrideWithValue(api),
        chatWebSocketClientProvider.overrideWithValue(FakeChatWebSocketClient()),
        engineHealthProvider.overrideWith(StaticEngineHealthNotifier.new),
      ],
      retry: kNoRetry,
    );
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const MaterialApp(home: AppGate())),
    );
    await tester.pumpAndSettle();

    expect(find.byType(AppShell), findsOneWidget);
  });
}

class _PreconfiguredConnectionNotifier extends ConnectionConfigNotifier {
  _PreconfiguredConnectionNotifier(this._initial);
  final ConnectionConfig _initial;

  @override
  ConnectionConfig build() => _initial;
}
