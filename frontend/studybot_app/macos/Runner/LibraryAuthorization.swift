import Cocoa
#if canImport(FlutterMacOS)
import FlutterMacOS
#endif

/// Failures reported to Dart as a short code; never a path or bookmark.
enum AuthorizationFailure: Error {
  case invalidArguments
  case unresolvable
  case accessDenied
  case unknownLease
}

/// Security-scoped, read-only access to folders the user chose in the open panel.
///
/// Holds one live access lease per call to `startAccess`. Only bookmark data created
/// from a user selection is ever resolved; nothing here takes a path as permission.
final class FolderAuthorization {
  struct Selection {
    let path: String
    let displayName: String
    let bookmark: Data
  }

  struct Lease {
    let id: String
    let path: String
    let refreshedBookmark: Data?
  }

  private static let bookmarkOptions: URL.BookmarkCreationOptions = [.withSecurityScope, .securityScopeAllowOnlyReadAccess]
  private static let probeByteLimit = 16

  private var leases: [String: URL] = [:]

  /// Bookmark data for a URL the user selected.
  static func makeBookmark(for url: URL) throws -> Data {
    try url.bookmarkData(options: bookmarkOptions, includingResourceValuesForKeys: nil, relativeTo: nil)
  }

  /// Shows the folder-only open panel. Returns nil if the user cancels.
  @MainActor
  func pickFolder() throws -> Selection? {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.allowsMultipleSelection = false
    panel.canCreateDirectories = false
    panel.message = "Choose a study folder for StudyBot to read."
    panel.prompt = "Authorize"
    guard panel.runModal() == .OK, let url = panel.url else { return nil }
    let bookmark = try Self.makeBookmark(for: url)
    return Selection(path: url.path, displayName: url.lastPathComponent, bookmark: bookmark)
  }

  /// Resolves the bookmark and begins access. A stale bookmark is refreshed when possible.
  func startAccess(bookmark: Data) throws -> Lease {
    var isStale = false
    guard let url = try? URL(
      resolvingBookmarkData: bookmark,
      options: [.withSecurityScope],
      relativeTo: nil,
      bookmarkDataIsStale: &isStale
    ) else { throw AuthorizationFailure.unresolvable }
    guard url.startAccessingSecurityScopedResource() else { throw AuthorizationFailure.accessDenied }

    var refreshed: Data?
    if isStale {
      guard let fresh = try? Self.makeBookmark(for: url) else {
        url.stopAccessingSecurityScopedResource()
        throw AuthorizationFailure.unresolvable
      }
      refreshed = fresh
    }
    let id = UUID().uuidString
    leases[id] = url
    return Lease(id: id, path: url.path, refreshedBookmark: refreshed)
  }

  /// Ends one lease. Calling it twice, or for an unknown lease, does nothing more.
  func stopAccess(leaseId: String) {
    guard let url = leases.removeValue(forKey: leaseId) else { return }
    url.stopAccessingSecurityScopedResource()
  }

  /// Whether a tiny read of `relativePath` inside the leased folder succeeds.
  /// Rejects absolute paths, `..` and anything that resolves outside the folder.
  func probeRead(leaseId: String, relativePath: String) throws -> Bool {
    guard let root = leases[leaseId] else { throw AuthorizationFailure.unknownLease }
    let parts = relativePath.split(separator: "/", omittingEmptySubsequences: true)
    guard !relativePath.hasPrefix("/"), !parts.isEmpty, !parts.contains("..") else { return false }

    let target = parts.reduce(root) { $0.appendingPathComponent(String($1)) }
    let rootPath = root.resolvingSymlinksInPath().path
    let targetPath = target.resolvingSymlinksInPath().path
    guard targetPath.hasPrefix(rootPath + "/") else { return false }

    guard let handle = try? FileHandle(forReadingFrom: target) else { return false }
    defer { try? handle.close() }
    return (try? handle.read(upToCount: Self.probeByteLimit)) != nil
  }

  func stopAll() {
    for id in Array(leases.keys) { stopAccess(leaseId: id) }
  }
}

#if canImport(FlutterMacOS)
/// Registers the `studybot/library_authorization` channel; the only native entry point.
final class LibraryAuthorizationChannel {
  private let authorization = FolderAuthorization()

  func register(with messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: "studybot/library_authorization", binaryMessenger: messenger)
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self else { return result(FlutterMethodNotImplemented) }
      self.handle(call, result)
    }
  }

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    let arguments = call.arguments as? [String: Any]
    do {
      switch call.method {
      case "pickFolder":
        DispatchQueue.main.async {
          do {
            guard let selection = try self.authorization.pickFolder() else { return result(nil) }
            result([
              "path": selection.path,
              "displayName": selection.displayName,
              "bookmark": selection.bookmark.base64EncodedString(),
            ])
          } catch { result(Self.error(error)) }
        }
      case "startAccess":
        guard let encoded = arguments?["bookmark"] as? String, let data = Data(base64Encoded: encoded) else {
          throw AuthorizationFailure.invalidArguments
        }
        let lease = try authorization.startAccess(bookmark: data)
        var response: [String: Any] = ["leaseId": lease.id, "path": lease.path]
        if let refreshed = lease.refreshedBookmark { response["refreshedBookmark"] = refreshed.base64EncodedString() }
        result(response)
      case "stopAccess":
        guard let leaseId = arguments?["leaseId"] as? String else { throw AuthorizationFailure.invalidArguments }
        authorization.stopAccess(leaseId: leaseId)
        result(nil)
      case "probeRead":
        guard let leaseId = arguments?["leaseId"] as? String, let path = arguments?["relativePath"] as? String else {
          throw AuthorizationFailure.invalidArguments
        }
        result(try authorization.probeRead(leaseId: leaseId, relativePath: path))
      default:
        result(FlutterMethodNotImplemented)
      }
    } catch { result(Self.error(error)) }
  }

  private static func error(_ error: Error) -> FlutterError {
    let code: String
    switch error as? AuthorizationFailure {
    case .invalidArguments: code = "invalid_arguments"
    case .unresolvable: code = "needs_access"
    case .accessDenied: code = "needs_access"
    case .unknownLease: code = "unknown_lease"
    case .none: code = "failed"
    }
    return FlutterError(code: code, message: nil, details: nil)
  }
}
#endif
