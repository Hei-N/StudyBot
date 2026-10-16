import 'package:studybot_app/core/platform/folder_authorization.dart';

/// A scriptable stand-in for the native folder picker and bookmark layer.
class FakeFolderAuthorization implements FolderAuthorization {
  /// Folders the next picks return, in order. An empty queue means the user cancels.
  final List<SelectedFolder> picks = [];
  Object? pickError;

  /// Bookmarks that can no longer be resolved (permission revoked, folder gone).
  final Set<String> unresolvable = {};

  /// Bookmarks that resolve but are stale; the value is the refreshed bookmark.
  final Map<String, String> stale = {};

  /// Bookmarks whose access start fails for another reason.
  final Set<String> broken = {};

  final Map<String, String> _active = {};
  int _nextLease = 1;
  int startCount = 0;
  int stopCount = 0;
  int pickCount = 0;

  Set<String> get activeLeases => _active.keys.toSet();

  @override
  Future<SelectedFolder?> pickFolder() async {
    pickCount++;
    final error = pickError;
    if (error != null) throw error;
    return picks.isEmpty ? null : picks.removeAt(0);
  }

  @override
  Future<AccessLease> startAccess(String bookmark) async {
    startCount++;
    if (unresolvable.contains(bookmark)) throw const FolderAccessException('needs_access');
    if (broken.contains(bookmark)) throw const FolderAccessException('failed');
    final id = 'lease-${_nextLease++}';
    _active[id] = bookmark;
    return AccessLease(id: id, path: '/resolved', refreshedBookmark: stale[bookmark]);
  }

  @override
  Future<void> stopAccess(String leaseId) async {
    if (_active.remove(leaseId) != null) stopCount++;
  }

  /// PDFs the next [pickAndStagePdf] calls return, in order. Empty means the user cancels.
  final List<StagedPdf> pdfPicks = [];
  Object? pdfPickError;
  final List<String> stagingDirectories = [];

  @override
  Future<StagedPdf?> pickAndStagePdf(String leaseId, String stagingDirectory) async {
    stagingDirectories.add(stagingDirectory);
    if (!_active.containsKey(leaseId)) throw const FolderAccessException('unknown_lease');
    final error = pdfPickError;
    if (error != null) throw error;
    return pdfPicks.isEmpty ? null : pdfPicks.removeAt(0);
  }

  @override
  Future<bool> probeRead(String leaseId, String relativePath) async => _active.containsKey(leaseId);
}
