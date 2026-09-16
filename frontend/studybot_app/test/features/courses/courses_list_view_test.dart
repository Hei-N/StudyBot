import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/courses/courses_list_view.dart';
import 'package:studybot_app/features/courses/courses_providers.dart';

import '../../support/fake_studybot_api.dart';

Course _course(String id, String name) =>
    Course(id: id, name: name, code: 'C$id', term: null, description: null, createdAt: 'now', updatedAt: 'now');

Widget _wrap(Widget child, FakeStudyBotApi api) {
  return ProviderScope(
    overrides: [studyBotApiProvider.overrideWithValue(api)],
    retry: (_, _) => null,
    child: MaterialApp(home: Scaffold(body: SizedBox(width: 260, child: child))),
  );
}

void main() {
  testWidgets('renders General plus every real course, General selected by default', (tester) async {
    final api = FakeStudyBotApi(courses: [_course('1', 'Physics I'), _course('2', 'Chemistry')]);
    await tester.pumpWidget(_wrap(const CoursesListView(), api));
    await tester.pumpAndSettle();

    expect(find.text('General'), findsOneWidget);
    expect(find.text('Physics I'), findsOneWidget);
    expect(find.text('Chemistry'), findsOneWidget);
  });

  testWidgets('tapping a course selects it as the active course', (tester) async {
    final api = FakeStudyBotApi(courses: [_course('1', 'Physics I')]);

    late final WidgetRef capturedRef;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [studyBotApiProvider.overrideWithValue(api)],
        retry: (_, _) => null,
        child: MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 260,
              child: Consumer(
                builder: (context, ref, _) {
                  capturedRef = ref;
                  return const CoursesListView();
                },
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Physics I'));
    await tester.pumpAndSettle();

    expect(capturedRef.read(activeCourseIdProvider), '1');
  });

  testWidgets('shows "No courses yet" when the list is empty', (tester) async {
    final api = FakeStudyBotApi();
    await tester.pumpWidget(_wrap(const CoursesListView(), api));
    await tester.pumpAndSettle();

    expect(find.text('No courses yet.'), findsOneWidget);
  });
}
