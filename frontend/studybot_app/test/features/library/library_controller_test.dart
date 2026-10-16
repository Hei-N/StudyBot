import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/library_source.dart';
import 'package:studybot_app/core/platform/folder_authorization.dart';
import 'package:studybot_app/features/connection/connection_providers.dart';
import 'package:studybot_app/features/library/library_providers.dart';

import '../../support/fake_folder_authorization.dart';
import '../../support/fake_studybot_api.dart';
import '../../support/no_retry_container.dart';

const _folder = SelectedFolder(path: '/lib/PHY215', displayName: 'PHY215', bookmark: 'bm-1');

({ProviderContainer container, FakeStudyBotApi api, FakeFolderAuthorization folders}) _setup() {
  final api = FakeStudyBotApi();
  final folders = FakeFolderAuthorization();
  final container = ProviderContainer(
    overrides: [studyBotApiProvider.overrideWithValue(api), folderAuthorizationProvider.overrideWithValue(folders)],
    retry: kNoRetry,
  );
  addTearDown(container.dispose);
  return (container: container, api: api, folders: folders);
}

Future<List<LibrarySourceEntry>> _load(ProviderContainer c) => c.read(libraryControllerProvider.future);

LibrarySource _source(String id, String locator) => LibrarySource(
  id: id,
  courseId: null,
  kind: 'local_folder',
  displayName: id,
  locator: locator,
  hasAuthorization: true,
);

void main() {
  test('starts empty and reads no folders', () async {
    final s = _setup();

    expect(await _load(s.container), isEmpty);
    expect(s.folders.startCount, 0);
  });

  test('cancelling the picker creates nothing', () async {
    final s = _setup();
    await _load(s.container);

    final result = await s.container.read(libraryControllerProvider.notifier).addFolder();

    expect(result, AddFolderResult.cancelled);
    expect(s.api.librarySources, isEmpty);
    expect(s.api.calls, isNot(contains('authorizeLocalFolder')));
  });

  test('picking a folder creates the source and activates access', () async {
    final s = _setup();
    await _load(s.container);
    s.folders.picks.add(_folder);

    final result = await s.container.read(libraryControllerProvider.notifier).addFolder();

    final entries = s.container.read(libraryControllerProvider).value!;
    expect(result, AddFolderResult.added);
    expect(entries.single.source.displayName, 'PHY215');
    expect(entries.single.access, SourceAccess.authorized);
    expect(s.api.libraryAuthorizations.values.single, 'bm-1');
    expect(s.folders.activeLeases, hasLength(1));
  });

  test('a picker failure is reported without touching the backend', () async {
    final s = _setup();
    await _load(s.container);
    s.folders.pickError = const FolderAccessException('failed');

    final result = await s.container.read(libraryControllerProvider.notifier).addFolder();

    expect(result, AddFolderResult.failed);
    expect(s.api.librarySources, isEmpty);
  });

  test('selecting the same folder again does not duplicate the source', () async {
    final s = _setup();
    await _load(s.container);
    final controller = s.container.read(libraryControllerProvider.notifier);
    s.folders.picks.add(_folder);
    await controller.addFolder();
    s.folders.picks.add(const SelectedFolder(path: '/lib/PHY215/', displayName: 'PHY215', bookmark: 'bm-2'));

    await controller.addFolder();

    expect(s.api.librarySources, hasLength(1));
    expect(s.api.libraryAuthorizations.values.single, 'bm-2');
    expect(s.folders.activeLeases, hasLength(1)); // the old lease was released, not leaked
  });

  test('restores access for stored sources after a restart', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));
    s.api.libraryAuthorizations['s1'] = 'bm-1';

    final entries = await _load(s.container);

    expect(entries.single.access, SourceAccess.authorized);
    expect(s.folders.startCount, 1);
    expect(s.api.calls, isNot(contains('authorizeLocalFolder')));
  });

  test('a new controller over the same data restores the same source', () async {
    final first = _setup();
    await _load(first.container);
    first.folders.picks.add(_folder);
    await first.container.read(libraryControllerProvider.notifier).addFolder();
    first.container.dispose();

    final folders = FakeFolderAuthorization();
    final restarted = ProviderContainer(
      overrides: [
        studyBotApiProvider.overrideWithValue(first.api),
        folderAuthorizationProvider.overrideWithValue(folders),
      ],
      retry: kNoRetry,
    );
    addTearDown(restarted.dispose);

    final entries = await _load(restarted);

    expect(entries.single.source.id, first.api.librarySources.single.id);
    expect(entries.single.access, SourceAccess.authorized);
    expect(folders.startCount, 1);
  });

  test('a stale bookmark is refreshed and persisted', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));
    s.api.libraryAuthorizations['s1'] = 'old';
    s.folders.stale['old'] = 'fresh';

    final entries = await _load(s.container);

    expect(entries.single.access, SourceAccess.authorized);
    expect(s.api.libraryAuthorizations['s1'], 'fresh');
  });

  test('an unresolvable bookmark needs access and never falls back to the path', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));
    s.api.libraryAuthorizations['s1'] = 'revoked';
    s.folders.unresolvable.add('revoked');

    final entries = await _load(s.container);

    expect(entries.single.access, SourceAccess.needsAccess);
    expect(s.folders.activeLeases, isEmpty);
    expect(s.folders.startCount, 1); // one attempt with the bookmark; no second path-based attempt
    expect(entries.single.source.id, 's1'); // the source is kept
  });

  test('a source without a stored authorization needs access', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));

    final entries = await _load(s.container);

    expect(entries.single.access, SourceAccess.needsAccess);
    expect(s.folders.startCount, 0);
  });

  test('another start failure is shown as unable to check, not as access', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));
    s.api.libraryAuthorizations['s1'] = 'weird';
    s.folders.broken.add('weird');

    expect((await _load(s.container)).single.access, SourceAccess.failed);
  });

  test('reauthorizing the same folder keeps the source id and restores access', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));
    s.api.libraryAuthorizations['s1'] = 'revoked';
    s.folders.unresolvable.add('revoked');
    final entries = await _load(s.container);
    s.folders.picks.add(const SelectedFolder(path: '/lib/PHY215', displayName: 'PHY215', bookmark: 'new'));

    final result = await s.container.read(libraryControllerProvider.notifier).reauthorize(entries.single.source);

    final after = s.container.read(libraryControllerProvider).value!;
    expect(result, ReauthorizeResult.restored);
    expect(after.single.source.id, 's1');
    expect(after.single.access, SourceAccess.authorized);
    expect(s.api.libraryAuthorizations['s1'], 'new');
  });

  test('reauthorizing with a different folder is refused and changes nothing', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));
    s.api.libraryAuthorizations['s1'] = 'revoked';
    s.folders.unresolvable.add('revoked');
    final entries = await _load(s.container);
    s.folders.picks.add(const SelectedFolder(path: '/lib/OTHER', displayName: 'OTHER', bookmark: 'other'));

    final result = await s.container.read(libraryControllerProvider.notifier).reauthorize(entries.single.source);

    expect(result, ReauthorizeResult.mismatch);
    expect(s.api.libraryAuthorizations['s1'], 'revoked');
    expect(s.api.librarySources.single.locator, '/lib/PHY215');
  });

  test('cancelling reauthorization changes nothing', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));
    final entries = await _load(s.container);

    final result = await s.container.read(libraryControllerProvider.notifier).reauthorize(entries.single.source);

    expect(result, ReauthorizeResult.cancelled);
    expect(s.api.calls, isNot(contains('replaceLibraryAuthorization:s1')));
  });

  test('removing a source releases its access once and deletes only metadata', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));
    s.api.libraryAuthorizations['s1'] = 'bm-1';
    await _load(s.container);
    expect(s.folders.activeLeases, hasLength(1));

    final removed = await s.container.read(libraryControllerProvider.notifier).remove('s1');

    expect(removed, isTrue);
    expect(s.folders.activeLeases, isEmpty);
    expect(s.folders.stopCount, 1);
    expect(s.api.librarySources, isEmpty);
    expect(s.api.libraryAuthorizations, isEmpty);
    expect(s.container.read(libraryControllerProvider).value, isEmpty);
  });

  test('disposing the controller releases every lease exactly once', () async {
    final s = _setup();
    s.api.librarySources.addAll([_source('a', '/lib/a'), _source('b', '/lib/b')]);
    s.api.libraryAuthorizations.addAll({'a': 'bm-a', 'b': 'bm-b'});
    await _load(s.container);
    expect(s.folders.activeLeases, hasLength(2));

    s.container.dispose();
    await Future<void>.delayed(Duration.zero);

    expect(s.folders.activeLeases, isEmpty);
    expect(s.folders.stopCount, 2);
  });

  test('refreshing keeps existing leases instead of starting new ones', () async {
    final s = _setup();
    s.api.librarySources.add(_source('s1', '/lib/PHY215'));
    s.api.libraryAuthorizations['s1'] = 'bm-1';
    await _load(s.container);

    await s.container.read(libraryControllerProvider.notifier).refresh();

    expect(s.folders.startCount, 1);
    expect(s.folders.activeLeases, hasLength(1));
  });
}
