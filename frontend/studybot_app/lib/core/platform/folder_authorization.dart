import 'package:flutter/services.dart';

/// A folder the user chose in the native picker, with its security-scoped bookmark.
class SelectedFolder {
  const SelectedFolder({required this.path, required this.displayName, required this.bookmark});

  /// Private local data; compared against a source's locator, never displayed in full.
  final String path;
  final String displayName;

  /// Base64 bookmark data. Sensitive: never log or display it.
  final String bookmark;
}

/// Live access to an authorized folder. Must be released with [FolderAuthorization.stopAccess].
class AccessLease {
  const AccessLease({required this.id, required this.path, this.refreshedBookmark});

  final String id;
  final String path;

  /// Set when the stored bookmark was stale and the native layer refreshed it.
  final String? refreshedBookmark;
}

/// Raised when access could not be granted; the source then needs to be reauthorized.
class FolderAccessException implements Exception {
  const FolderAccessException(this.code);

  final String code;

  bool get needsAccess => code == 'needs_access';

  @override
  String toString() => 'FolderAccessException($code)';
}

/// The platform boundary for user-selected folder access. Implemented natively on
/// macOS; other platforms plug in their own without changing library records.
abstract class FolderAuthorization {
  /// Shows the native folder picker. Returns null if the user cancels.
  Future<SelectedFolder?> pickFolder();

  /// Resolves a stored bookmark and begins access. Throws [FolderAccessException].
  Future<AccessLease> startAccess(String bookmark);

  Future<void> stopAccess(String leaseId);

  /// Whether a tiny read of [relativePath] inside the leased folder succeeds.
  Future<bool> probeRead(String leaseId, String relativePath);
}

/// macOS implementation over the `studybot/library_authorization` channel.
class MacOSFolderAuthorization implements FolderAuthorization {
  MacOSFolderAuthorization({MethodChannel? channel})
    : _channel = channel ?? const MethodChannel('studybot/library_authorization');

  final MethodChannel _channel;

  @override
  Future<SelectedFolder?> pickFolder() async {
    final result = await _invoke<Map<Object?, Object?>>('pickFolder');
    if (result == null) return null;
    return SelectedFolder(
      path: result['path'] as String,
      displayName: result['displayName'] as String,
      bookmark: result['bookmark'] as String,
    );
  }

  @override
  Future<AccessLease> startAccess(String bookmark) async {
    final result = await _invoke<Map<Object?, Object?>>('startAccess', {'bookmark': bookmark});
    if (result == null) throw const FolderAccessException('failed');
    return AccessLease(
      id: result['leaseId'] as String,
      path: result['path'] as String,
      refreshedBookmark: result['refreshedBookmark'] as String?,
    );
  }

  @override
  Future<void> stopAccess(String leaseId) async {
    await _invoke<Object?>('stopAccess', {'leaseId': leaseId});
  }

  @override
  Future<bool> probeRead(String leaseId, String relativePath) async {
    return await _invoke<bool>('probeRead', {'leaseId': leaseId, 'relativePath': relativePath}) ?? false;
  }

  Future<T?> _invoke<T>(String method, [Map<String, Object?>? arguments]) async {
    try {
      return await _channel.invokeMethod<T>(method, arguments);
    } on PlatformException catch (e) {
      throw FolderAccessException(e.code);
    } on MissingPluginException {
      throw const FolderAccessException('unavailable');
    }
  }
}
