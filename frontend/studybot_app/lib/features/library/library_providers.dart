import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/library_source.dart';
import '../../core/platform/folder_authorization.dart';
import '../connection/connection_providers.dart';

/// The platform's folder-authorization implementation; replaced in tests.
final folderAuthorizationProvider = Provider<FolderAuthorization>((ref) => MacOSFolderAuthorization());

/// Live access state of a source. Runtime only; never persisted.
enum SourceAccess { authorized, needsAccess, failed }

class LibrarySourceEntry {
  const LibrarySourceEntry(this.source, this.access);

  final LibrarySource source;
  final SourceAccess access;
}

enum AddFolderResult { added, cancelled, failed }

enum ReauthorizeResult { restored, cancelled, mismatch, failed }

/// Loads library sources, restores their folder access and handles add,
/// reauthorize and remove. Access is restored only for configured sources and
/// never reads folder contents. A source whose authorization cannot be used is
/// shown as needing access; its stored path is never used as a fallback.
class LibraryController extends AsyncNotifier<List<LibrarySourceEntry>> {
  final _leases = <String, AccessLease>{};

  // Cached because providers cannot be read while the controller is being disposed.
  late FolderAuthorization _folders;

  @override
  Future<List<LibrarySourceEntry>> build() {
    _folders = ref.read(folderAuthorizationProvider);
    ref.onDispose(_releaseAll);
    return _load(reactivate: const {});
  }

  /// Fetches sources. Sources already holding a lease keep it unless listed in
  /// [reactivate]; every other source is activated now.
  Future<List<LibrarySourceEntry>> _load({required Set<String> reactivate}) async {
    final sources = await ref.read(studyBotApiProvider).listLibrarySources();
    final known = {for (final id in _leases.keys) id};
    for (final id in known.difference({for (final s in sources) s.id})) {
      await _release(id);
    }
    final entries = <LibrarySourceEntry>[];
    for (final source in sources) {
      if (_leases.containsKey(source.id) && !reactivate.contains(source.id)) {
        entries.add(LibrarySourceEntry(source, SourceAccess.authorized));
      } else {
        entries.add(LibrarySourceEntry(source, await _activate(source)));
      }
    }
    return entries;
  }

  Future<void> refresh() async {
    state = await AsyncValue.guard(() => _load(reactivate: const {}));
  }

  Future<SourceAccess> _activate(LibrarySource source) async {
    await _release(source.id);
    if (!source.hasAuthorization) return SourceAccess.needsAccess;
    try {
      final api = ref.read(studyBotApiProvider);
      final authorization = await api.getLibraryAuthorization(source.id);
      final lease = await _folders.startAccess(authorization.payload);
      _leases[source.id] = lease;
      final refreshed = lease.refreshedBookmark;
      if (refreshed != null) {
        try {
          await api.replaceLibraryAuthorization(source.id, bookmark: refreshed);
        } on ApiException {
          // Access is live; the refreshed bookmark is saved on the next activation.
        }
      }
      return SourceAccess.authorized;
    } on FolderAccessException catch (e) {
      return e.needsAccess ? SourceAccess.needsAccess : SourceAccess.failed;
    } on ApiException {
      return SourceAccess.failed;
    }
  }

  Future<void> _release(String sourceId) async {
    final lease = _leases.remove(sourceId);
    if (lease == null) return;
    try {
      await _folders.stopAccess(lease.id);
    } on FolderAccessException {
      // Nothing more to release.
    }
  }

  void _releaseAll() {
    for (final id in _leases.keys.toList()) {
      _release(id);
    }
  }

  Future<AddFolderResult> addFolder() async {
    try {
      final selection = await _folders.pickFolder();
      if (selection == null) return AddFolderResult.cancelled;
      final source = await ref
          .read(studyBotApiProvider)
          .authorizeLocalFolder(
            displayName: selection.displayName,
            locator: selection.path,
            bookmark: selection.bookmark,
          );
      state = AsyncData(await _load(reactivate: {source.id}));
      return AddFolderResult.added;
    } on FolderAccessException {
      return AddFolderResult.failed;
    } on ApiException {
      return AddFolderResult.failed;
    }
  }

  Future<ReauthorizeResult> reauthorize(LibrarySource source) async {
    try {
      final selection = await _folders.pickFolder();
      if (selection == null) return ReauthorizeResult.cancelled;
      if (_normalize(selection.path) != _normalize(source.locator)) return ReauthorizeResult.mismatch;
      await ref.read(studyBotApiProvider).replaceLibraryAuthorization(source.id, bookmark: selection.bookmark);
      state = AsyncData(await _load(reactivate: {source.id}));
      return ReauthorizeResult.restored;
    } on FolderAccessException {
      return ReauthorizeResult.failed;
    } on ApiException {
      return ReauthorizeResult.failed;
    }
  }

  /// Lets the user pick a PDF inside the source, stages it privately and imports it.
  /// Needs a live lease for the source; the engine only ever receives a staging id.
  Future<ImportPdfResult> importPdf(LibrarySource source) async {
    final lease = _leases[source.id];
    if (lease == null) return ImportPdfResult.needsAccess;
    final importing = ref.read(importingSourcesProvider.notifier);
    try {
      final api = ref.read(studyBotApiProvider);
      final staged = await _folders.pickAndStagePdf(lease.id, await api.getIngestStagingDirectory());
      if (staged == null) return ImportPdfResult.cancelled;
      importing.set(source.id, importing: true);
      final result = await api.importPdf(
        source.id,
        stagingId: staged.stagingId,
        relativePath: staged.relativePath,
        displayName: staged.displayName,
      );
      ref.invalidate(libraryFilesProvider(source.id));
      return switch (result.outcome) {
        'unchanged' => ImportPdfResult.unchanged,
        'failed' => ImportPdfResult.failed,
        _ => ImportPdfResult.imported,
      };
    } on FolderAccessException catch (e) {
      return switch (e.code) {
        'outside_source' => ImportPdfResult.outsideSource,
        'not_pdf' => ImportPdfResult.notPdf,
        'needs_access' || 'unknown_lease' => ImportPdfResult.needsAccess,
        _ => ImportPdfResult.error,
      };
    } on ApiException {
      return ImportPdfResult.error;
    } finally {
      importing.set(source.id, importing: false);
    }
  }

  /// Releases access and removes the source and its stored authorization from
  /// StudyBot. The folder and its files are untouched.
  Future<bool> remove(String sourceId) async {
    try {
      await _release(sourceId);
      await ref.read(studyBotApiProvider).deleteLibrarySource(sourceId);
      ref.invalidate(libraryFilesProvider(sourceId));
      state = AsyncData(await _load(reactivate: const {}));
      return true;
    } on ApiException {
      return false;
    }
  }

  static String _normalize(String path) {
    final collapsed = path.trim().replaceAll(RegExp(r'/{2,}'), '/');
    return collapsed.length > 1 && collapsed.endsWith('/') ? collapsed.substring(0, collapsed.length - 1) : collapsed;
  }
}

final libraryControllerProvider = AsyncNotifierProvider<LibraryController, List<LibrarySourceEntry>>(
  LibraryController.new,
);

/// The files recorded under one source (metadata and state only).
final libraryFilesProvider = FutureProvider.autoDispose.family<List<LibraryFile>, String>((ref, sourceId) {
  return ref.watch(studyBotApiProvider).listLibraryFiles(sourceId);
});

/// Source ids with a PDF import in progress.
class ImportingSources extends Notifier<Set<String>> {
  @override
  Set<String> build() => const {};

  void set(String sourceId, {required bool importing}) {
    state = importing ? {...state, sourceId} : ({...state}..remove(sourceId));
  }
}

final importingSourcesProvider = NotifierProvider<ImportingSources, Set<String>>(ImportingSources.new);

enum ImportPdfResult { imported, unchanged, failed, cancelled, outsideSource, notPdf, needsAccess, error }
