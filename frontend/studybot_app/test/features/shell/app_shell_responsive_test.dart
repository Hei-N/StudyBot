import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/core/models/reasoning_mode.dart';
import 'package:studybot_app/core/models/teaching_mode.dart';
import 'package:studybot_app/features/chats/chats_list_view.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/courses/courses_list_view.dart';
import 'package:studybot_app/features/courses/courses_providers.dart';
import 'package:studybot_app/features/shell/app_shell.dart';
import 'package:studybot_app/features/status/status_providers.dart';

import '../../support/fake_chat_websocket_client.dart';
import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';
import '../../support/static_engine_health_notifier.dart';

Course _course(int i) => Course(
  id: 'c$i',
  name: 'Course number $i',
  code: 'C$i',
  term: null,
  description: null,
  createdAt: 'now',
  updatedAt: 'now',
);

Chat _chat(int i) => Chat(
  id: 'chat$i',
  title: 'Chat number $i',
  courseId: null,
  teachingMode: 'teach',
  reasoningMode: 'fast',
  createdAt: 'now',
  updatedAt: 'now',
);

/// Renders [AppShell] at a given logical width/height with real (fake-backed)
/// data flowing through every region — deliberately with *enough* courses
/// and chats that they cannot all fit on screen, so a broken (non-scrolling)
/// list would leave some unreachable, matching how Bug 2 actually manifested.
Future<ProviderContainer> _pumpShellAt(WidgetTester tester, Size logicalSize, {int courseCount = 20}) async {
  addTearDown(tester.view.reset);
  tester.view.physicalSize = logicalSize * tester.view.devicePixelRatio;

  final api = FakeStudyBotApi(
    courses: List.generate(courseCount, _course),
    chats: List.generate(20, _chat),
    modes: const [
      TeachingModeInfo(id: 'teach', displayName: 'Teach', description: 'Step by step.'),
      TeachingModeInfo(id: 'quick', displayName: 'Quick Answer', description: 'Direct and concise.'),
    ],
    reasoningModes: const [
      ReasoningModeInfo(id: 'fast', displayName: 'Fast', description: 'Answers immediately.'),
      ReasoningModeInfo(id: 'deep', displayName: 'Deep Think', description: 'Reasons before answering.'),
    ],
  );
  for (var i = 0; i < 20; i++) {
    api.messagesByChat['chat$i'] = [];
  }

  final container = ProviderContainer(
    overrides: [
      studyBotApiProvider.overrideWithValue(api),
      chatWebSocketClientProvider.overrideWithValue(FakeChatWebSocketClient()),
      engineHealthProvider.overrideWith(StaticEngineHealthNotifier.new),
    ],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  container.read(activeChatIdProvider.notifier).select('chat0');
  await container.read(chatsProvider.future);
  await container.read(coursesProvider.future);

  await tester.pumpWidget(
    UncontrolledProviderScope(container: container, child: const MaterialApp(home: AppShell())),
  );
  await tester.pumpAndSettle();
  return container;
}

void main() {
  // The user-specified manual macOS window sizes from the Stage 5.6
  // stabilization request, each labeled with which adaptive tier it falls
  // into given AppBreakpoints (compact=600, medium=900, large=1200).
  final sizes = {
    '1600x1000 (large)': const Size(1600, 1000),
    '1300x850 (large)': const Size(1300, 850),
    '1100x750 (medium)': const Size(1100, 750),
    '900x700 (medium)': const Size(900, 700),
    '700x650 (compact)': const Size(700, 650),
    'phone 390x844': const Size(390, 844),
  };

  for (final entry in sizes.entries) {
    testWidgets('renders ${entry.key} with no overflow and key controls present', (tester) async {
      await _pumpShellAt(tester, entry.value);
      expect(tester.takeException(), isNull);

      // The composer must always be reachable, regardless of tier.
      expect(find.byType(TextField), findsWidgets);
      expect(find.byIcon(Icons.arrow_upward), findsOneWidget);
    });
  }

  testWidgets('continuously resizing the window across all tiers never overflows', (tester) async {
    await _pumpShellAt(tester, const Size(1600, 1000));

    for (final size in [
      const Size(1600, 1000),
      const Size(1300, 850),
      const Size(1100, 750),
      const Size(900, 700),
      const Size(700, 650),
      const Size(390, 844),
      const Size(1100, 750),
      const Size(1600, 1000),
    ]) {
      tester.view.physicalSize = size * tester.view.devicePixelRatio;
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull, reason: 'overflow or error at size $size');
    }
  });

  group('at every non-phone tier, the full courses list is reachable by scrolling', () {
    for (final entry in {
      '1600x1000 (large)': const Size(1600, 1000),
      '1100x750 (medium)': const Size(1100, 750),
      '700x650 (compact)': const Size(700, 650),
    }.entries) {
      testWidgets(entry.key, (tester) async {
        // Regression test for Bug 2's root cause: CoursesListView's inner
        // list used to be `shrinkWrap: true` + `NeverScrollableScrollPhysics`
        // inside a `Flexible` — with more courses than fit in the available
        // height (worse at these deliberately short, non-fullscreen sizes),
        // everything past the fold was permanently unreachable. It must now
        // be a plain scrollable list that can reach the last course.
        await _pumpShellAt(tester, entry.value, courseCount: 20);

        // The last course's own tile may not exist in the widget tree yet
        // (ListView only builds visible + cached items) — scrolling the
        // Scrollable that contains it must bring it into view and it must
        // then be genuinely tappable (tester.tap fails if hit-testing is
        // blocked by anything, e.g. a stray overlay). Anchored on
        // CoursesListView specifically, rather than an ordinal
        // find.byType(Scrollable).first, which is fragile once several
        // scrollables exist in the tree.
        final coursesScrollable = find.descendant(
          of: find.byType(CoursesListView),
          matching: find.byType(Scrollable),
        );
        await tester.dragUntilVisible(find.text('Course number 19'), coursesScrollable, const Offset(0, -60));
        // dragUntilVisible stops the moment the finder resolves at all,
        // which can leave the item only just barely inside the viewport
        // edge (a real tap there would be unreliable) — nudge it further
        // in before asserting it's genuinely tappable.
        await tester.drag(coursesScrollable, const Offset(0, -80));
        await tester.pumpAndSettle();
        expect(find.text('Course number 19'), findsOneWidget);
        await tester.tap(find.text('Course number 19'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      });
    }
  });

  group('at every non-phone tier, the full chats list is reachable by scrolling', () {
    for (final entry in {
      '1600x1000 (large)': const Size(1600, 1000),
      '1100x750 (medium)': const Size(1100, 750),
      '700x650 (compact)': const Size(700, 650),
    }.entries) {
      testWidgets(entry.key, (tester) async {
        await _pumpShellAt(tester, entry.value);

        // Anchor on ChatsListView specifically rather than an ordinal
        // find.byType(Scrollable).first/.last, which is fragile once
        // several scrollables exist in the tree (courses, chats,
        // conversation, ...).
        final chatsScrollable = find.descendant(of: find.byType(ChatsListView), matching: find.byType(Scrollable));
        await tester.dragUntilVisible(find.text('Chat number 19'), chatsScrollable, const Offset(0, -60));
        // See the equivalent comment in the courses test above.
        await tester.drag(chatsScrollable, const Offset(0, -80));
        await tester.pumpAndSettle();
        expect(find.text('Chat number 19'), findsOneWidget);
        await tester.tap(find.text('Chat number 19'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      });
    }
  });

  testWidgets('large tier: composer, courses, chats, and settings are all independently tappable', (
    tester,
  ) async {
    await _pumpShellAt(tester, const Size(1600, 1000), courseCount: 3);

    // Composer is reachable and usable in General (which has chats).
    await tester.enterText(find.byType(TextField).first, 'hello from the composer');
    await tester.pump();
    expect(find.text('hello from the composer'), findsOneWidget);

    // Switching to a course with no chats of its own is a real, valid state
    // (an empty-conversation prompt, not a bug) — just confirm it doesn't
    // throw and the course/chat lists themselves keep working.
    await tester.tap(find.text('Course number 1'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    await tester.tap(find.byTooltip('Settings'));
    await tester.pumpAndSettle();
    expect(find.text('Settings'), findsWidgets);
  });

  testWidgets('medium tier: the study panel is hidden and everything else stays reachable', (tester) async {
    await _pumpShellAt(tester, const Size(1100, 750), courseCount: 3);

    expect(find.text('Engine'), findsNothing); // StudyPanel's "Engine" section header
    expect(find.byIcon(Icons.arrow_upward), findsOneWidget);

    await tester.tap(find.text('Course number 1'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('compact tier: the menu button toggles the combined sidebar and both panes stay usable', (
    tester,
  ) async {
    await _pumpShellAt(tester, const Size(700, 650), courseCount: 3);

    // Sidebar starts open — General/course tiles are visible.
    expect(find.text('General'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.menu));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);

    await tester.tap(find.byIcon(Icons.menu));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('General'), findsOneWidget);

    // The composer must remain reachable throughout.
    expect(find.byIcon(Icons.arrow_upward), findsOneWidget);
  });

  testWidgets('phone tier: the drawer opens over the conversation without blocking it permanently', (
    tester,
  ) async {
    await _pumpShellAt(tester, const Size(390, 844), courseCount: 3);

    expect(find.byIcon(Icons.arrow_upward), findsOneWidget);

    await tester.tap(find.byTooltip(MaterialLocalizations.of(tester.element(find.byType(Scaffold).first)).openAppDrawerTooltip));
    await tester.pumpAndSettle();
    expect(find.text('General'), findsOneWidget);

    // Dismiss by tapping the scrim, back to a fully-usable conversation.
    await tester.tapAt(const Offset(380, 400));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byIcon(Icons.arrow_upward), findsOneWidget);
  });
}
