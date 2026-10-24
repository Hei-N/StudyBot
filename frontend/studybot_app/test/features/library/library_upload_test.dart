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

const _lecture = StagedUpload(stagingId: 'stage-1', displayName: 'Lecture.pdf', sizeBytes: 100);

LibraryFile _upload(String name, {String state = 'ready', int? pages = 2, int? textPages = 2}) => LibraryFile(
  id: 'upload-$name',
  sourceId: 'uploads',
  relativePath: name,
  displayName: name,
  processingState: state,
  failureCode: null,
  pageCount: pages,
  textPageCount: textPages,
);

({FakeStudyBotApi api, FakeFolderAuthorization folders, ProviderContainer container}) _setup() {
  final api = FakeStudyBotApi();
  final folders = FakeFolderAuthorization();
  final container = ProviderContainer(
    overrides: [studyBotApiProvider.overrideWithValue(api), folderAuthorizationProvider.overrideWithValue(folders)],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  return (api: api, folders: folders, container: container);
}

Future<void> _pump(WidgetTester tester, ProviderContainer container) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      key: UniqueKey(),
      container: container,
      child: const MaterialApp(home: LibraryView()),
    ),
  );
  await tester.pumpAndSettle();
}

Future<LibraryController> _controller(ProviderContainer c) async {
  await c.read(libraryControllerProvider.future);
  return c.read(libraryControllerProvider.notifier);
}

void main() {
  group('controller', () {
    test('uploading stages the file and sends only the staging id and display name', () async {
      final s = _setup();
      s.folders.uploadPicks.add(_lecture);
      final controller = await _controller(s.container);

      final outcome = await controller.uploadPdf();

      expect(outcome.kind, UploadKind.uploaded);
      expect(s.api.uploadedStagingIds, ['stage-1']);
      expect(s.folders.stagingDirectories, ['/staging']);
      expect(s.container.read(importingSourcesProvider), isEmpty);
      expect(s.api.librarySources, isEmpty); // no folder source was created
      expect(s.api.calls, isNot(contains('authorizeLocalFolder')));
    });

    test('cancelling uploads nothing', () async {
      final s = _setup();
      final controller = await _controller(s.container);

      final outcome = await controller.uploadPdf();

      expect(outcome.kind, UploadKind.cancelled);
      expect(s.api.calls, isNot(contains('uploadPdf')));
    });

    test('a duplicate is reported without adding a second file', () async {
      final s = _setup();
      s.api.nextUploadOutcome = 'duplicate';
      s.folders.uploadPicks.addAll([
        _lecture,
        const StagedUpload(stagingId: 'stage-2', displayName: 'Lecture.pdf', sizeBytes: 100),
      ]);
      final controller = await _controller(s.container);
      await controller.uploadPdf();

      final second = await controller.uploadPdf();

      expect(second.kind, UploadKind.duplicate);
      expect(s.api.uploads, hasLength(1));
    });

    test('a processing failure carries its code', () async {
      final s = _setup();
      s.api.nextUploadOutcome = 'failed';
      s.api.nextUploadFailure = 'password_required';
      s.folders.uploadPicks.add(_lecture);
      final controller = await _controller(s.container);

      final outcome = await controller.uploadPdf();

      expect(outcome.kind, UploadKind.failed);
      expect(outcome.failureCode, 'password_required');
      expect(s.api.uploads, isEmpty);
    });

    test('native rejections map to notPdf or a generic error', () async {
      final notPdf = _setup()..folders.uploadPickError = const FolderAccessException('not_pdf');
      final failed = _setup()..folders.uploadPickError = const FolderAccessException('staging_failed');

      expect((await (await _controller(notPdf.container)).uploadPdf()).kind, UploadKind.notPdf);
      expect((await (await _controller(failed.container)).uploadPdf()).kind, UploadKind.error);
      expect(notPdf.api.calls, isNot(contains('uploadPdf')));
    });

    test('removing an upload deletes it through the API and refreshes the list', () async {
      final s = _setup();
      s.api.uploads.add(_upload('Lecture.pdf'));
      final controller = await _controller(s.container);

      final removed = await controller.removeUpload('upload-Lecture.pdf');

      expect(removed, isTrue);
      expect(s.api.uploads, isEmpty);
      expect(await s.container.read(uploadedFilesProvider.future), isEmpty);
    });
  });

  group('view', () {
    testWidgets('Upload File and Add Folder are both offered, with no folders needed', (tester) async {
      final s = _setup();
      await _pump(tester, s.container);

      expect(find.text('Upload File'), findsOneWidget);
      expect(find.text('Add Folder'), findsOneWidget);
      expect(find.text('No folders yet'), findsOneWidget);
    });

    testWidgets('uploading shows the file as Uploaded and Ready with no path', (tester) async {
      final s = _setup();
      s.folders.uploadPicks.add(_lecture);
      await _pump(tester, s.container);

      await tester.tap(find.text('Upload File'));
      await tester.pumpAndSettle();

      expect(find.text('Lecture.pdf'), findsOneWidget);
      expect(find.text('Uploaded · Ready · 2 pages'), findsOneWidget);
      expect(find.text('Uploaded files'), findsOneWidget);
      expect(find.textContaining('/Users'), findsNothing);
      expect(find.text('No folders yet'), findsNothing);
    });

    testWidgets('cancelling shows nothing', (tester) async {
      final s = _setup();
      await _pump(tester, s.container);

      await tester.tap(find.text('Upload File'));
      await tester.pumpAndSettle();

      expect(find.byType(SnackBar), findsNothing);
      expect(find.text('No folders yet'), findsOneWidget);
    });

    testWidgets('a duplicate shows the friendly message', (tester) async {
      final s = _setup();
      s.api.nextUploadOutcome = 'duplicate';
      s.api.uploads.add(_upload('Lecture.pdf'));
      s.folders.uploadPicks.add(_lecture);
      await _pump(tester, s.container);

      await tester.tap(find.text('Upload File'));
      await tester.pumpAndSettle();

      expect(find.text('This PDF is already in your library.'), findsOneWidget);
    });

    for (final entry in {
      'password_required': 'This PDF is password protected.',
      'invalid_pdf': 'This file is not a valid PDF.',
      'file_too_large': 'This PDF is too large to import.',
      'something_else': "Couldn't import that PDF. Please try again.",
    }.entries) {
      testWidgets('failure ${entry.key} shows a concise message and adds nothing', (tester) async {
        final s = _setup();
        s.api.nextUploadOutcome = 'failed';
        s.api.nextUploadFailure = entry.key;
        s.folders.uploadPicks.add(_lecture);
        await _pump(tester, s.container);

        await tester.tap(find.text('Upload File'));
        await tester.pumpAndSettle();

        expect(find.text(entry.value), findsOneWidget);
        expect(find.textContaining('Exception'), findsNothing);
        expect(find.text('Lecture.pdf'), findsNothing);
      });
    }

    testWidgets('a non-PDF choice says to choose a PDF', (tester) async {
      final s = _setup();
      s.folders.uploadPickError = const FolderAccessException('not_pdf');
      await _pump(tester, s.container);

      await tester.tap(find.text('Upload File'));
      await tester.pumpAndSettle();

      expect(find.text('Please choose a PDF file.'), findsOneWidget);
    });

    testWidgets('uploaded files appear alongside folder sources', (tester) async {
      final s = _setup();
      s.api.librarySources.add(
        const LibrarySource(
          id: 's1',
          courseId: null,
          kind: 'local_folder',
          displayName: 'PHY215',
          locator: '/lib/PHY215',
          hasAuthorization: true,
        ),
      );
      s.api.libraryAuthorizations['s1'] = 'bm';
      s.api.uploads.add(_upload('Notes.pdf', pages: 1, textPages: 1));
      await _pump(tester, s.container);

      expect(find.text('Notes.pdf'), findsOneWidget);
      expect(find.text('PHY215'), findsOneWidget);
      expect(find.text('Import PDF'), findsOneWidget); // the folder flow is unchanged
    });

    testWidgets('removing an upload asks first and removes only StudyBot copy wording', (tester) async {
      final s = _setup();
      s.api.uploads.add(_upload('Notes.pdf'));
      await _pump(tester, s.container);

      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();

      expect(find.text('Remove from StudyBot?'), findsOneWidget);
      expect(find.textContaining('original file on your Mac is not touched'), findsOneWidget);

      await tester.tap(find.widgetWithText(FilledButton, 'Remove'));
      await tester.pumpAndSettle();

      expect(s.api.uploads, isEmpty);
      expect(find.text('Notes.pdf'), findsNothing);
    });

    testWidgets('cancelling the removal keeps the upload', (tester) async {
      final s = _setup();
      s.api.uploads.add(_upload('Notes.pdf'));
      await _pump(tester, s.container);

      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(find.text('Notes.pdf'), findsOneWidget);
      expect(s.api.uploads, hasLength(1));
    });

    testWidgets('an image-only upload is described honestly', (tester) async {
      final s = _setup();
      s.api.uploads.add(_upload('Scan.pdf', pages: 10, textPages: 0));
      await _pump(tester, s.container);

      expect(find.textContaining('No extractable text · 10 pages'), findsOneWidget);
    });
  });
}
