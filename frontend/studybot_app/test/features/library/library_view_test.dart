import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/library_source.dart';
import 'package:studybot_app/core/platform/folder_authorization.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/library/library_providers.dart';
import 'package:studybot_app/features/library/library_view.dart';

import '../../support/fake_folder_authorization.dart';
import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';

LibrarySource _source(String id, String name, String locator) => LibrarySource(
  id: id,
  courseId: null,
  kind: 'local_folder',
  displayName: name,
  locator: locator,
  hasAuthorization: true,
);

Future<({FakeStudyBotApi api, FakeFolderAuthorization folders})> _pump(
  WidgetTester tester, {
  void Function(FakeStudyBotApi api, FakeFolderAuthorization folders)? seed,
}) async {
  final api = FakeStudyBotApi();
  final folders = FakeFolderAuthorization();
  seed?.call(api, folders);
  final container = ProviderContainer(
    overrides: [studyBotApiProvider.overrideWithValue(api), folderAuthorizationProvider.overrideWithValue(folders)],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: LibraryView()),
    ),
  );
  await tester.pumpAndSettle();
  return (api: api, folders: folders);
}

void main() {
  testWidgets('empty state shows the Add Folder button and no sources', (tester) async {
    await _pump(tester);

    expect(find.text('Study Library'), findsOneWidget);
    expect(find.text('Add Folder'), findsOneWidget);
    expect(find.text('No folders yet'), findsOneWidget);
  });

  testWidgets('adding a folder lists it as authorized', (tester) async {
    final s = await _pump(
      tester,
      seed: (api, folders) {
        folders.picks.add(const SelectedFolder(path: '/private/School/PHY215', displayName: 'PHY215', bookmark: 'bm'));
      },
    );

    await tester.tap(find.text('Add Folder'));
    await tester.pumpAndSettle();

    expect(find.text('PHY215'), findsOneWidget);
    expect(find.text('Authorized'), findsOneWidget);
    expect(find.textContaining('/private/School'), findsNothing); // no full path shown
    expect(s.api.librarySources, hasLength(1));
  });

  testWidgets('cancelling the picker changes nothing and shows no error', (tester) async {
    final s = await _pump(tester);

    await tester.tap(find.text('Add Folder'));
    await tester.pumpAndSettle();

    expect(find.text('No folders yet'), findsOneWidget);
    expect(find.byType(SnackBar), findsNothing);
    expect(s.api.librarySources, isEmpty);
  });

  testWidgets('a failed authorization shows a short message without raw details', (tester) async {
    await _pump(tester, seed: (api, folders) => folders.pickError = const FolderAccessException('failed'));

    await tester.tap(find.text('Add Folder'));
    await tester.pumpAndSettle();

    expect(find.text("Couldn't authorize that folder. Please try again."), findsOneWidget);
    expect(find.textContaining('Exception'), findsNothing);
  });

  testWidgets('a source that lost access shows Needs access and Reauthorize', (tester) async {
    await _pump(
      tester,
      seed: (api, folders) {
        api.librarySources.add(_source('s1', 'PHY215', '/lib/PHY215'));
        api.libraryAuthorizations['s1'] = 'revoked';
        folders.unresolvable.add('revoked');
      },
    );

    expect(find.text('PHY215'), findsOneWidget);
    expect(find.textContaining('Needs access'), findsOneWidget);
    expect(find.text('Reauthorize'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('reauthorizing with the original folder restores access', (tester) async {
    await _pump(
      tester,
      seed: (api, folders) {
        api.librarySources.add(_source('s1', 'PHY215', '/lib/PHY215'));
        api.libraryAuthorizations['s1'] = 'revoked';
        folders.unresolvable.add('revoked');
        folders.picks.add(const SelectedFolder(path: '/lib/PHY215', displayName: 'PHY215', bookmark: 'new'));
      },
    );

    await tester.tap(find.text('Reauthorize'));
    await tester.pumpAndSettle();

    expect(find.text('Authorized'), findsOneWidget);
    expect(find.text('Reauthorize'), findsNothing);
  });

  testWidgets('reauthorizing with a different folder explains the mismatch', (tester) async {
    await _pump(
      tester,
      seed: (api, folders) {
        api.librarySources.add(_source('s1', 'PHY215', '/lib/PHY215'));
        api.libraryAuthorizations['s1'] = 'revoked';
        folders.unresolvable.add('revoked');
        folders.picks.add(const SelectedFolder(path: '/lib/OTHER', displayName: 'OTHER', bookmark: 'x'));
      },
    );

    await tester.tap(find.text('Reauthorize'));
    await tester.pumpAndSettle();

    expect(find.textContaining("isn't the same folder"), findsOneWidget);
    expect(find.textContaining('Needs access'), findsOneWidget);
  });

  testWidgets('removing asks for confirmation in non-destructive wording', (tester) async {
    final s = await _pump(
      tester,
      seed: (api, folders) {
        api.librarySources.add(_source('s1', 'PHY215', '/lib/PHY215'));
        api.libraryAuthorizations['s1'] = 'bm';
      },
    );

    await tester.tap(find.text('Remove'));
    await tester.pumpAndSettle();

    expect(find.text('Remove from StudyBot?'), findsOneWidget);
    expect(find.textContaining('not deleted'), findsOneWidget);
    expect(find.textContaining('Delete'), findsNothing);

    await tester.tap(find.widgetWithText(FilledButton, 'Remove'));
    await tester.pumpAndSettle();

    expect(find.text('No folders yet'), findsOneWidget);
    expect(s.api.librarySources, isEmpty);
    expect(s.folders.activeLeases, isEmpty);
  });

  testWidgets('cancelling the removal keeps the source', (tester) async {
    final s = await _pump(
      tester,
      seed: (api, folders) {
        api.librarySources.add(_source('s1', 'PHY215', '/lib/PHY215'));
        api.libraryAuthorizations['s1'] = 'bm';
      },
    );

    await tester.tap(find.text('Remove'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(find.text('PHY215'), findsOneWidget);
    expect(s.api.librarySources, hasLength(1));
  });

  testWidgets('an authorization failure at load does not crash the page', (tester) async {
    await _pump(
      tester,
      seed: (api, folders) {
        api.librarySources.add(_source('s1', 'PHY215', '/lib/PHY215'));
        api.libraryAuthorizations['s1'] = 'weird';
        folders.broken.add('weird');
      },
    );

    expect(find.textContaining("Couldn't check access"), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
