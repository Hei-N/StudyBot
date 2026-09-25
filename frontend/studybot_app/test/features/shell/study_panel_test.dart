import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/core/models/learning_memory.dart';
import 'package:studybot_app/features/chats/chats_providers.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/courses/courses_providers.dart';
import 'package:studybot_app/features/memory/memory_management_view.dart';
import 'package:studybot_app/features/shell/study_panel.dart';
import 'package:studybot_app/features/status/status_providers.dart';

import '../../support/fake_studybot_api.dart';
import '../../support/static_engine_health_notifier.dart';

Chat _chat({String? courseId}) => Chat(
  id: 'chat1',
  title: 'Chat',
  courseId: courseId,
  teachingMode: 'teach',
  reasoningMode: 'fast',
  createdAt: 'now',
  updatedAt: 'now',
);

Course _course(String id, String name) =>
    Course(id: id, name: name, code: null, term: null, description: null, createdAt: 'now', updatedAt: 'now');

LearningMemory _memory({
  required String id,
  String? courseId,
  required String topic,
  required String kind,
  String status = 'active',
}) => LearningMemory(
  id: id,
  courseId: courseId,
  sourceChatId: null,
  topic: topic,
  kind: kind,
  summary: 'summary for $topic',
  status: status,
  createdAt: 'now',
  updatedAt: 'now',
);

Future<void> _pump(WidgetTester tester, FakeStudyBotApi api, {String? activeCourseId}) async {
  final container = ProviderContainer(
    overrides: [
      studyBotApiProvider.overrideWithValue(api),
      engineHealthProvider.overrideWith(StaticEngineHealthNotifier.new),
    ],
    retry: (_, _) => null,
  );
  addTearDown(container.dispose);
  container.read(activeChatIdProvider.notifier).select('chat1');
  if (activeCourseId != null) container.read(activeCourseIdProvider.notifier).select(activeCourseId);
  await container.read(chatsProvider.future);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: Scaffold(body: SizedBox(width: 300, child: StudyPanel()))),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('shows "no learning memory yet" when there are none for the course', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()]);

    await _pump(tester, api);

    expect(find.text('LEARNING MEMORY'), findsOneWidget);
    expect(find.text('No learning memory yet for this course.'), findsOneWidget);
  });

  testWidgets('groups active memories by kind for the active course', (tester) async {
    final course = _course('c1', 'Physics');
    final api = FakeStudyBotApi(
      chats: [_chat(courseId: course.id)],
      courses: [course],
      memories: [
        _memory(id: 'm1', courseId: course.id, topic: 'Vector components', kind: 'needs_review'),
        _memory(id: 'm2', courseId: course.id, topic: 'Significant figures', kind: 'understands'),
      ],
    );

    await _pump(tester, api, activeCourseId: course.id);

    expect(find.text('Needs review'), findsOneWidget);
    expect(find.text('•  Vector components'), findsOneWidget);
    expect(find.text('Understands'), findsOneWidget);
    expect(find.text('•  Significant figures'), findsOneWidget);
  });

  testWidgets('a different course\'s memory never appears', (tester) async {
    final physics = _course('physics', 'Physics');
    final calc = _course('calc', 'Calculus');
    final api = FakeStudyBotApi(
      chats: [_chat(courseId: calc.id)],
      courses: [physics, calc],
      memories: [_memory(id: 'm1', courseId: physics.id, topic: 'Vector components', kind: 'needs_review')],
    );

    await _pump(tester, api, activeCourseId: calc.id);

    expect(find.text('Vector components'), findsNothing);
    expect(find.text('No learning memory yet for this course.'), findsOneWidget);
  });

  testWidgets('archived memories are excluded from the panel', (tester) async {
    final course = _course('c1', 'Physics');
    final api = FakeStudyBotApi(
      chats: [_chat(courseId: course.id)],
      courses: [course],
      memories: [_memory(id: 'm1', courseId: course.id, topic: 'Old topic', kind: 'needs_review', status: 'archived')],
    );

    await _pump(tester, api, activeCourseId: course.id);

    expect(find.text('Old topic'), findsNothing);
  });

  testWidgets('global memories appear regardless of active course', (tester) async {
    final course = _course('c1', 'Physics');
    final api = FakeStudyBotApi(
      chats: [_chat(courseId: course.id)],
      courses: [course],
      memories: [_memory(id: 'm1', courseId: null, topic: 'Study habits', kind: 'useful_strategy')],
    );

    await _pump(tester, api, activeCourseId: course.id);

    expect(find.text('•  Study habits'), findsOneWidget);
  });

  testWidgets('never renders a mastery percentage anywhere', (tester) async {
    final course = _course('c1', 'Physics');
    final api = FakeStudyBotApi(
      chats: [_chat(courseId: course.id)],
      courses: [course],
      memories: [_memory(id: 'm1', courseId: course.id, topic: 'Vectors', kind: 'needs_review')],
    );

    await _pump(tester, api, activeCourseId: course.id);

    expect(find.textContaining('%'), findsNothing);
  });

  testWidgets('"View all" opens the memory management view', (tester) async {
    final api = FakeStudyBotApi(chats: [_chat()]);

    await _pump(tester, api);
    await tester.tap(find.text('View all'));
    await tester.pumpAndSettle();

    expect(find.byType(MemoryManagementView), findsOneWidget);
  });
}
