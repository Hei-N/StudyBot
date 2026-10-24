import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:studybot_app/app/app.dart';
import 'package:studybot_app/core/api/connection_config.dart';
import 'package:studybot_app/core/models/health.dart';
import 'package:studybot_app/core/ollama/ollama_lifecycle.dart';
import 'package:studybot_app/core/platform/ollama_launcher.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/connection/ollama_startup.dart';
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
    await tester.pumpWidget(
      ProviderScope(
        retry: (_, _) => null,
        child: const MaterialApp(home: AppGate()),
      ),
    );
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
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: AppGate()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Engine unavailable'), findsOneWidget);
    expect(find.text('Open Study Library'), findsNothing); // the engine itself is down
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
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: AppGate()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Ollama is not running'), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
    expect(find.text('Open Study Library'), findsOneWidget);
    expect(find.byType(AppShell), findsNothing);
  });

  testWidgets('the Study Library opens even while Ollama is not running', (tester) async {
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
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: AppGate()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Open Study Library'));
    await tester.pumpAndSettle();

    expect(find.text('Study Library'), findsOneWidget);
    expect(find.text('Upload File'), findsOneWidget);
    expect(find.byType(AppShell), findsNothing);
  });

  testWidgets('shows the app shell once configured and healthy', (tester) async {
    final api = FakeStudyBotApi();
    final container = ProviderContainer(
      overrides: [
        connectionConfigProvider.overrideWith(
          () => _PreconfiguredConnectionNotifier(const ConnectionConfig(baseUrl: 'http://127.0.0.1:8765', token: 't')),
        ),
        studyBotApiProvider.overrideWithValue(api),
        chatWebSocketClientProvider.overrideWithValue(FakeChatWebSocketClient()),
        engineHealthProvider.overrideWith(StaticEngineHealthNotifier.new),
      ],
      retry: kNoRetry,
    );
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: AppGate()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(AppShell), findsOneWidget);
  });

  group('Ollama startup', () {
    var ollamaUp = false;
    late _GateLauncher launcher;

    EngineHealth health({required bool reachable}) => EngineHealth(
      apiVersion: '1',
      status: 'ok',
      provider: 'ollama',
      model: 'qwen3:4b',
      providerReachable: reachable,
      modelAvailable: reachable,
    );

    ProviderContainer container({
      bool installed = true,
      bool launchWorks = true,
      bool healthReachable = true,
      Duration timeout = const Duration(milliseconds: 80),
    }) {
      launcher = _GateLauncher(installed: installed, onLaunch: () => ollamaUp = launchWorks);
      return ProviderContainer(
        overrides: [
          connectionConfigProvider.overrideWith(
            () => _PreconfiguredConnectionNotifier(const ConnectionConfig(baseUrl: 'http://127.0.0.1:9', token: 't')),
          ),
          studyBotApiProvider.overrideWithValue(FakeStudyBotApi()),
          chatWebSocketClientProvider.overrideWithValue(FakeChatWebSocketClient()),
          ollamaAutostartEnabledProvider.overrideWithValue(true),
          ollamaLifecycleProvider.overrideWithValue(
            OllamaLifecycle(
              launcher: launcher,
              probe: () async => ollamaUp,
              pollInterval: const Duration(milliseconds: 5),
              timeout: timeout,
            ),
          ),
          engineHealthProvider.overrideWith(
            () => StaticEngineHealthNotifier(health: health(reachable: healthReachable)),
          ),
        ],
        retry: kNoRetry,
      );
    }

    Future<void> pump(WidgetTester tester, ProviderContainer c) async {
      addTearDown(c.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: c,
          child: const MaterialApp(home: AppGate()),
        ),
      );
      await tester.pumpAndSettle();
    }

    setUp(() => ollamaUp = false);

    testWidgets('a stopped Ollama is launched once and the app continues on its own', (tester) async {
      await pump(tester, container());

      expect(launcher.launches, 1);
      expect(find.byType(AppShell), findsOneWidget);
      expect(find.text('Ollama is not running'), findsNothing);
    });

    testWidgets('a running Ollama is not launched', (tester) async {
      ollamaUp = true;
      await pump(tester, container());

      expect(launcher.launches, 0);
      expect(find.byType(AppShell), findsOneWidget);
    });

    testWidgets('a missing Ollama app explains what to install and keeps the library reachable', (tester) async {
      await pump(tester, container(installed: false, healthReachable: false));

      expect(launcher.launches, 0);
      expect(find.text('Ollama is not running'), findsOneWidget);
      expect(find.textContaining("couldn't find the Ollama app"), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);
      expect(find.text('Open Study Library'), findsOneWidget);
    });

    testWidgets('an Ollama that never answers times out into a Retry state', (tester) async {
      await pump(tester, container(launchWorks: false, healthReachable: false));

      expect(launcher.launches, 1);
      expect(find.textContaining("couldn't start Ollama"), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);
      expect(find.text('Open Study Library'), findsOneWidget);
    });

    testWidgets('Retry launches Ollama once more', (tester) async {
      await pump(tester, container(launchWorks: false, healthReachable: false));
      expect(launcher.launches, 1);

      await tester.tap(find.text('Retry'));
      await tester.pumpAndSettle();

      expect(launcher.launches, 2);
    });
  });
}

class _PreconfiguredConnectionNotifier extends ConnectionConfigNotifier {
  _PreconfiguredConnectionNotifier(this._initial);
  final ConnectionConfig _initial;

  @override
  ConnectionConfig build() => _initial;
}

class _GateLauncher implements OllamaLauncher {
  _GateLauncher({required this.installed, required this.onLaunch});

  final bool installed;
  final void Function() onLaunch;
  int launches = 0;

  @override
  Future<bool> isInstalled() async => installed;

  @override
  Future<void> launch() async {
    launches++;
    onLaunch();
  }
}
