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

const _staged = StagedPdf(
  stagingId: 'stage-1',
  relativePath: 'Week 2/Lecture.pdf',
  displayName: 'Lecture.pdf',
  sizeBytes: 100,
);

LibrarySource _source(String id) => LibrarySource(
  id: id,
  courseId: null,
  kind: 'local_folder',
  displayName: 'PHY215',
  locator: '/lib/PHY215',
  hasAuthorization: true,
);

LibraryFile _file({
  String state = 'ready',
  String? failure,
  int? pages = 2,
  int? textPages = 2,
  String path = 'Week 2/Lecture.pdf',
}) => LibraryFile(
  id: 'file-1',
  sourceId: 's1',
  relativePath: path,
  displayName: path.split('/').last,
  processingState: state,
  failureCode: failure,
  pageCount: pages,
  textPageCount: textPages,
);

({FakeStudyBotApi api, FakeFolderAuthorization folders, ProviderContainer container}) _setup({bool authorized = true}) {
  final api = FakeStudyBotApi();
  final folders = FakeFolderAuthorization();
  api.librarySources.add(_source('s1'));
  if (authorized) api.libraryAuthorizations['s1'] = 'bm';
  final container = ProviderContainer(
    overrides: [studyBotApiProvider.overrideWithValue(api), folderAuthorizationProvider.overrideWithValue(folders)],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  return (api: api, folders: folders, container: container);
}

Future<LibraryController> _controller(ProviderContainer c) async {
  await c.read(libraryControllerProvider.future);
  return c.read(libraryControllerProvider.notifier);
}

Future<void> _pumpView(WidgetTester tester, ProviderContainer container) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: LibraryView()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('controller', () {
    test('picking a PDF stages it and imports by staging id', () async {
      final s = _setup();
      s.folders.pdfPicks.add(_staged);
      final controller = await _controller(s.container);

      final result = await controller.importPdf(_source('s1'));

      expect(result, ImportPdfResult.imported);
      expect(s.api.importedStagingIds, ['stage-1']);
      expect(s.folders.stagingDirectories, ['/staging']);
      expect(s.container.read(importingSourcesProvider), isEmpty);
    });

    test('cancelling the picker stages and imports nothing', () async {
      final s = _setup();
      final controller = await _controller(s.container);

      final result = await controller.importPdf(_source('s1'));

      expect(result, ImportPdfResult.cancelled);
      expect(s.api.calls, isNot(contains('importPdf:s1')));
    });

    test('a source that needs access cannot import', () async {
      final s = _setup(authorized: false);
      s.folders.pdfPicks.add(_staged);
      final controller = await _controller(s.container);

      final result = await controller.importPdf(_source('s1'));

      expect(result, ImportPdfResult.needsAccess);
      expect(s.folders.pdfPicks, hasLength(1)); // the picker was never opened
    });

    test('an unchanged PDF is reported as such', () async {
      final s = _setup();
      s.api.nextImportOutcome = 'unchanged';
      s.folders.pdfPicks.add(_staged);
      final controller = await _controller(s.container);

      expect(await controller.importPdf(_source('s1')), ImportPdfResult.unchanged);
    });

    test('a processing failure is reported without throwing', () async {
      final s = _setup();
      s.api.nextImportOutcome = 'failed';
      s.api.importFileBuilder = (id, path, name) =>
          _file(state: 'failed', failure: 'password_required', pages: null, textPages: null);
      s.folders.pdfPicks.add(_staged);
      final controller = await _controller(s.container);

      expect(await controller.importPdf(_source('s1')), ImportPdfResult.failed);
    });

    test('native rejections map to specific results', () async {
      for (final entry in {
        'outside_source': ImportPdfResult.outsideSource,
        'not_pdf': ImportPdfResult.notPdf,
        'staging_failed': ImportPdfResult.error,
        'needs_access': ImportPdfResult.needsAccess,
      }.entries) {
        final s = _setup();
        s.folders.pdfPickError = FolderAccessException(entry.key);
        final controller = await _controller(s.container);

        expect(await controller.importPdf(_source('s1')), entry.value, reason: entry.key);
        expect(s.api.calls, isNot(contains('importPdf:s1')));
      }
    });

    test('importing keeps the source id and never touches the source record', () async {
      final s = _setup();
      s.folders.pdfPicks.add(_staged);
      final controller = await _controller(s.container);

      await controller.importPdf(_source('s1'));

      expect(s.api.librarySources.single.id, 's1');
      expect(s.api.calls, isNot(contains('authorizeLocalFolder')));
      expect(s.container.read(libraryFilesProvider('s1').future), completion(hasLength(1)));
    });
  });

  group('view', () {
    testWidgets('an authorized source offers Import PDF', (tester) async {
      await _pumpView(tester, _setup().container);

      expect(find.text('Import PDF'), findsOneWidget);
    });

    testWidgets('a needs-access source does not offer Import PDF', (tester) async {
      await _pumpView(tester, _setup(authorized: false).container);

      expect(find.text('Import PDF'), findsNothing);
      expect(find.text('Reauthorize'), findsOneWidget);
    });

    testWidgets('importing shows the file with its page counts and no absolute path', (tester) async {
      final s = _setup();
      s.folders.pdfPicks.add(_staged);
      await _pumpView(tester, s.container);

      await tester.tap(find.text('Import PDF'));
      await tester.pumpAndSettle();

      expect(find.text('Lecture.pdf'), findsOneWidget);
      expect(find.text('Week 2/Lecture.pdf · Ready · 2 pages'), findsOneWidget);
      expect(find.textContaining('/Users'), findsNothing);
      expect(find.text('PHY215'), findsOneWidget); // same source row
    });

    testWidgets('cancelling shows nothing', (tester) async {
      final s = _setup();
      await _pumpView(tester, s.container);

      await tester.tap(find.text('Import PDF'));
      await tester.pumpAndSettle();

      expect(find.byType(SnackBar), findsNothing);
      expect(find.textContaining('Ready'), findsNothing);
    });

    testWidgets('re-importing an unchanged PDF says it is up to date', (tester) async {
      final s = _setup();
      s.api.nextImportOutcome = 'unchanged';
      s.folders.pdfPicks.add(_staged);
      await _pumpView(tester, s.container);

      await tester.tap(find.text('Import PDF'));
      await tester.pumpAndSettle();

      expect(find.text('That PDF is already up to date.'), findsOneWidget);
    });

    testWidgets('a PDF outside the folder shows the guidance message', (tester) async {
      final s = _setup();
      s.folders.pdfPickError = const FolderAccessException('outside_source');
      await _pumpView(tester, s.container);

      await tester.tap(find.text('Import PDF'));
      await tester.pumpAndSettle();

      expect(find.text('Choose a PDF inside this Study Library folder.'), findsOneWidget);
    });

    for (final entry in {
      'password_required': 'Password-protected PDF',
      'invalid_pdf': 'Not a valid PDF',
      'interrupted': 'Import was interrupted',
      'something_new': 'Import failed',
    }.entries) {
      testWidgets('failed file (${entry.key}) is described and can be imported again', (tester) async {
        final s = _setup();
        s.api.libraryFiles['s1'] = [_file(state: 'failed', failure: entry.key, pages: null, textPages: null)];
        await _pumpView(tester, s.container);

        expect(find.textContaining(entry.value), findsOneWidget);
        expect(find.text('Import again'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('a valid PDF with no text is described honestly', (tester) async {
      final s = _setup();
      s.api.libraryFiles['s1'] = [_file(pages: 10, textPages: 0)];
      await _pumpView(tester, s.container);

      expect(find.textContaining('No extractable text · 10 pages'), findsOneWidget);
      expect(find.text('Import again'), findsNothing);
    });

    testWidgets('partial text wording', (tester) async {
      final s = _setup();
      s.api.libraryFiles['s1'] = [_file(pages: 5, textPages: 3, path: 'a.pdf')];
      await _pumpView(tester, s.container);

      expect(find.textContaining('Ready · 5 pages (3 with text)'), findsOneWidget);
    });

    testWidgets('single page wording', (tester) async {
      final s = _setup();
      s.api.libraryFiles['s1'] = [_file(pages: 1, textPages: 1, path: 'b.pdf')];
      await _pumpView(tester, s.container);

      expect(find.textContaining('Ready · 1 page'), findsOneWidget);
    });

    testWidgets('a stale file can be imported again', (tester) async {
      final s = _setup();
      s.api.libraryFiles['s1'] = [_file(state: 'stale', path: 'a.pdf')];
      await _pumpView(tester, s.container);

      expect(find.textContaining('Out of date'), findsOneWidget);
      expect(find.text('Import again'), findsOneWidget);
    });

    testWidgets('an in-progress file shows Importing', (tester) async {
      final s = _setup();
      s.api.libraryFiles['s1'] = [_file(state: 'indexing', pages: null, textPages: null, path: 'b.pdf')];
      await _pumpView(tester, s.container);

      expect(find.textContaining('Importing…'), findsOneWidget);
    });
  });
}
