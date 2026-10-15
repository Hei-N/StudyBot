import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/api/api_exception.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/core/models/learning_memory.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/memory/memory_management_view.dart';
import 'package:studybot_app/features/memory/memory_providers.dart';

import '../../support/fake_studybot_api.dart';

LearningMemory _memory({
  required String id,
  String? courseId,
  required String topic,
  String kind = 'needs_review',
  String status = 'active',
  String summary = 'A summary.',
}) => LearningMemory(
  id: id,
  courseId: courseId,
  sourceChatId: null,
  topic: topic,
  kind: kind,
  summary: summary,
  status: status,
  createdAt: 'now',
  updatedAt: 'now',
);

Future<ProviderContainer> _pump(WidgetTester tester, FakeStudyBotApi api) async {
  final container = ProviderContainer(
    overrides: [studyBotApiProvider.overrideWithValue(api)],
    retry: (_, _) => null,
  );
  addTearDown(container.dispose);
  await container.read(memoriesProvider.future);

  await tester.pumpWidget(
    UncontrolledProviderScope(container: container, child: const MaterialApp(home: MemoryManagementView())),
  );
  await tester.pumpAndSettle();
  return container;
}

void main() {
  testWidgets('shows empty state when there are no memories', (tester) async {
    final api = FakeStudyBotApi();
    await _pump(tester, api);

    expect(find.text('No learning memory yet'), findsOneWidget);
  });

  testWidgets('lists memories with topic and kind', (tester) async {
    final api = FakeStudyBotApi(memories: [_memory(id: 'm1', topic: 'Vector components', kind: 'needs_review')]);
    await _pump(tester, api);

    expect(find.text('Vector components'), findsOneWidget);
    expect(find.text('Needs review'), findsOneWidget);
  });

  testWidgets('never shows a raw kind identifier or a mastery percentage', (tester) async {
    final api = FakeStudyBotApi(memories: [_memory(id: 'm1', topic: 'Vector components', kind: 'needs_review')]);
    await _pump(tester, api);

    expect(find.text('needs_review'), findsNothing);
    expect(find.textContaining('%'), findsNothing);
  });

  testWidgets('creating a memory via the dialog adds it to the list', (tester) async {
    final api = FakeStudyBotApi();
    await _pump(tester, api);

    await tester.tap(find.byIcon(Icons.add));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Topic'), 'Newton\'s Laws');
    await tester.enterText(find.widgetWithText(TextField, 'Summary'), 'Wants to review these.');
    await tester.tap(find.text('Create'));
    await tester.pumpAndSettle();

    expect(find.text('Newton\'s Laws'), findsOneWidget);
    expect(api.calls.any((c) => c.startsWith('createMemory:')), isTrue);
  });

  testWidgets('editing a memory updates its topic', (tester) async {
    final api = FakeStudyBotApi(memories: [_memory(id: 'm1', topic: 'Old topic')]);
    await _pump(tester, api);

    await tester.tap(find.byIcon(Icons.more_horiz));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Edit'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextField, 'Topic'), 'New topic');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    expect(find.text('New topic'), findsOneWidget);
    expect(find.text('Old topic'), findsNothing);
  });

  testWidgets('archiving a memory removes it from the default active view', (tester) async {
    final api = FakeStudyBotApi(memories: [_memory(id: 'm1', topic: 'Vectors')]);
    await _pump(tester, api);

    await tester.tap(find.byIcon(Icons.more_horiz));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Archive'));
    await tester.pumpAndSettle();

    expect(find.text('Vectors'), findsNothing); // default filter is "Active"
    expect(api.memories.single.status, 'archived');
  });

  testWidgets('switching the status filter to Archived shows the archived memory and offers Restore', (
    tester,
  ) async {
    final api = FakeStudyBotApi(memories: [_memory(id: 'm1', topic: 'Vectors', status: 'archived')]);
    await _pump(tester, api);

    await tester.tap(find.text('Active')); // opens the status dropdown
    await tester.pumpAndSettle();
    await tester.tap(find.text('Archived').last);
    await tester.pumpAndSettle();

    expect(find.text('Vectors'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.more_horiz));
    await tester.pumpAndSettle();
    expect(find.text('Restore'), findsOneWidget);

    await tester.tap(find.text('Restore'));
    await tester.pumpAndSettle();

    expect(api.memories.single.status, 'active');
  });

  testWidgets('deleting a memory asks for confirmation and then removes it', (tester) async {
    final api = FakeStudyBotApi(memories: [_memory(id: 'm1', topic: 'Vectors')]);
    await _pump(tester, api);

    await tester.tap(find.byIcon(Icons.more_horiz));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();

    expect(find.textContaining('permanently deletes'), findsOneWidget);

    await tester.tap(find.text('Delete').last);
    await tester.pumpAndSettle();

    expect(find.text('Vectors'), findsNothing);
    expect(api.memories, isEmpty);
  });

  testWidgets('canceling delete keeps the memory', (tester) async {
    final api = FakeStudyBotApi(memories: [_memory(id: 'm1', topic: 'Vectors')]);
    await _pump(tester, api);

    await tester.tap(find.byIcon(Icons.more_horiz));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(find.text('Vectors'), findsOneWidget);
    expect(api.memories, isNotEmpty);
  });

  testWidgets('filters by course', (tester) async {
    final physics = Course(
      id: 'physics',
      name: 'Physics',
      code: null,
      term: null,
      description: null,
      createdAt: 'now',
      updatedAt: 'now',
    );
    final api = FakeStudyBotApi(
      courses: [physics],
      memories: [
        _memory(id: 'm1', courseId: 'physics', topic: 'Vectors'),
        _memory(id: 'm2', courseId: null, topic: 'General topic'),
      ],
    );
    await _pump(tester, api);

    expect(find.text('Vectors'), findsOneWidget);
    expect(find.text('General topic'), findsOneWidget);

    await tester.tap(find.text('All courses'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Physics').last);
    await tester.pumpAndSettle();

    expect(find.text('Vectors'), findsOneWidget);
    expect(find.text('General topic'), findsNothing);
  });

  // --- memories orphaned by a course deletion (archived + global) -----------------------

  testWidgets('a memory archived and unassigned by a course deletion shows correctly under Archived/General', (
    tester,
  ) async {
    // Simulates what the backend does to a course's memories on course deletion
    // (archived, courseId set to null); the app just displays what it returns.
    final api = FakeStudyBotApi(
      memories: [_memory(id: 'm1', courseId: null, topic: 'Stoichiometry', status: 'archived')],
    );
    await _pump(tester, api);

    await tester.tap(find.text('Active')); // status dropdown
    await tester.pumpAndSettle();
    await tester.tap(find.text('Archived').last);
    await tester.pumpAndSettle();

    expect(find.text('Stoichiometry'), findsOneWidget);

    await tester.tap(find.text('All courses'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('General only').last);
    await tester.pumpAndSettle();

    expect(find.text('Stoichiometry'), findsOneWidget);
  });

  testWidgets('an orphaned archived memory can be restored, becoming active and global', (tester) async {
    final api = FakeStudyBotApi(
      memories: [_memory(id: 'm1', courseId: null, topic: 'Stoichiometry', status: 'archived')],
    );
    await _pump(tester, api);
    await tester.tap(find.text('Active'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Archived').last);
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.more_horiz));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Restore'));
    await tester.pumpAndSettle();

    expect(api.memories.single.status, 'active');
    expect(api.memories.single.courseId, isNull);
  });

  testWidgets('an orphaned archived memory can be reassigned to a different course while still archived', (
    tester,
  ) async {
    final calculus = Course(
      id: 'calc',
      name: 'Calculus',
      code: null,
      term: null,
      description: null,
      createdAt: 'now',
      updatedAt: 'now',
    );
    final api = FakeStudyBotApi(
      courses: [calculus],
      memories: [_memory(id: 'm1', courseId: null, topic: 'Related topic', status: 'archived')],
    );
    await _pump(tester, api);
    await tester.tap(find.text('Active'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Archived').last);
    await tester.pumpAndSettle();

    await tester.tap(find.byIcon(Icons.more_horiz));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Edit'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('General (no course)'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Calculus').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    final updated = api.memories.single;
    expect(updated.id, 'm1');
    expect(updated.courseId, 'calc');
    expect(updated.status, 'archived'); // reassigning alone does not restore it
  });

  testWidgets('shows an error view when the list fails to load', (tester) async {
    final api = FakeStudyBotApi()
      ..nextError = const ApiException(code: ApiErrorCode.internalError, message: 'boom');
    final container = ProviderContainer(
      overrides: [studyBotApiProvider.overrideWithValue(api)],
      retry: (_, _) => null,
    );
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const MaterialApp(home: MemoryManagementView())),
    );
    await tester.pumpAndSettle();

    expect(find.text('boom'), findsOneWidget);
  });
}
