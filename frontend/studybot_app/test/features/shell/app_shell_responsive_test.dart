import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/core/models/teaching_mode.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/shell/app_shell.dart';
import 'package:studybot_app/features/status/status_providers.dart';

import '../../support/fake_chat_websocket_client.dart';
import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';
import '../../support/static_engine_health_notifier.dart';

/// Renders [AppShell] at a given logical width/height with real (fake-backed)
/// data flowing through every region, so the four adaptive tiers are each
/// exercised with content present — not just an empty shell.
Future<void> _pumpShellAt(WidgetTester tester, Size logicalSize) async {
  addTearDown(tester.view.reset);
  tester.view.physicalSize = logicalSize * tester.view.devicePixelRatio;

  final api = FakeStudyBotApi(
    courses: [
      Course(
        id: 'c1',
        name: 'Physics I',
        code: 'PHY 215',
        term: 'Fall 2026',
        description: null,
        createdAt: 'now',
        updatedAt: 'now',
      ),
    ],
    chats: [Chat(id: 'chat1', title: 'Homework help', courseId: null, teachingMode: 'teach', createdAt: 'now', updatedAt: 'now')],
    modes: const [TeachingModeInfo(id: 'teach', displayName: 'Teach', description: 'Step by step.')],
  );
  api.messagesByChat['chat1'] = [];

  final container = ProviderContainer(
    overrides: [
      studyBotApiProvider.overrideWithValue(api),
      chatWebSocketClientProvider.overrideWithValue(FakeChatWebSocketClient()),
      engineHealthProvider.overrideWith(StaticEngineHealthNotifier.new),
    ],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  container.read(activeChatIdProvider.notifier).select('chat1');
  await container.read(chatsProvider.future);

  await tester.pumpWidget(
    UncontrolledProviderScope(container: container, child: const MaterialApp(home: AppShell())),
  );
  await tester.pumpAndSettle();
}

void main() {
  final sizes = {
    'phone (< 600)': const Size(390, 844),
    'compact/tablet (600-900)': const Size(760, 900),
    'medium (900-1200)': const Size(1000, 800),
    'large (>= 1200)': const Size(1400, 900),
  };

  for (final entry in sizes.entries) {
    testWidgets('renders the ${entry.key} tier with no overflow errors', (tester) async {
      await _pumpShellAt(tester, entry.value);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('continuously resizing the window across all tiers never overflows', (tester) async {
    await _pumpShellAt(tester, const Size(1400, 900));

    for (final size in [
      const Size(1400, 900),
      const Size(1000, 800),
      const Size(760, 900),
      const Size(390, 844),
      const Size(900, 700),
      const Size(1300, 750),
    ]) {
      tester.view.physicalSize = size * tester.view.devicePixelRatio;
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull, reason: 'overflow or error at size $size');
    }
  });
}
