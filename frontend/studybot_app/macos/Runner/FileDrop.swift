import Cocoa
#if canImport(FlutterMacOS)
import FlutterMacOS
#endif

/// Turns dropped file URLs into private staged copies, using the same staging code as the
/// file picker. Only the file URLs macOS hands over for a drop are read.
enum DroppedFiles {
  static let maxFiles = 5

  struct Item {
    let stagingId: String?
    let displayName: String
    let sizeBytes: Int
    let errorCode: String?

    var dictionary: [String: Any] {
      var result: [String: Any] = ["displayName": displayName, "sizeBytes": sizeBytes]
      if let stagingId { result["stagingId"] = stagingId }
      if let errorCode { result["error"] = errorCode }
      return result
    }
  }

  /// True if the drag holds at least one PDF (by extension; folders do not count).
  static func containsPdf(_ urls: [URL]) -> Bool {
    urls.contains { url in
      var isDirectory: ObjCBool = false
      FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory)
      return !isDirectory.boolValue && url.pathExtension.lowercased() == "pdf"
    }
  }

  static func stage(_ urls: [URL], stagingDirectory: String, using authorization: FolderAuthorization) -> [Item] {
    urls.enumerated().map { index, url in
      let name = url.lastPathComponent
      guard index < maxFiles else { return Item(stagingId: nil, displayName: name, sizeBytes: 0, errorCode: "too_many") }
      do {
        let staged = try authorization.stageUpload(selected: url, stagingDirectory: stagingDirectory)
        return Item(stagingId: staged.stagingId, displayName: staged.displayName, sizeBytes: staged.sizeBytes, errorCode: nil)
      } catch let failure as AuthorizationFailure {
        let code: String
        switch failure {
        case .tooLarge: code = "too_large"
        case .stagingFailed: code = "staging_failed"
        default: code = "not_pdf"
        }
        return Item(stagingId: nil, displayName: name, sizeBytes: 0, errorCode: code)
      } catch {
        return Item(stagingId: nil, displayName: name, sizeBytes: 0, errorCode: "staging_failed")
      }
    }
  }
}

#if canImport(FlutterMacOS)
/// A transparent view over the Flutter view that receives file drops. It never takes mouse
/// events, and it accepts drags only while the chat composer has asked for them.
final class FileDropView: NSView {
  var onEvent: ((String, [String: Any]) -> Void)?
  var acceptingDrops = false
  var stagingDirectory: String?
  private let authorization: FolderAuthorization

  init(authorization: FolderAuthorization) {
    self.authorization = authorization
    super.init(frame: .zero)
    autoresizingMask = [.width, .height]
    registerForDraggedTypes([.fileURL])
  }

  required init?(coder: NSCoder) { fatalError("not used") }

  override func hitTest(_ point: NSPoint) -> NSView? { nil }

  private func fileURLs(_ sender: NSDraggingInfo) -> [URL] {
    let options: [NSPasteboard.ReadingOptionKey: Any] = [.urlReadingFileURLsOnly: true]
    return sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: options) as? [URL] ?? []
  }

  private func operation(for sender: NSDraggingInfo, announce: Bool) -> NSDragOperation {
    guard acceptingDrops else { return [] }
    let urls = fileURLs(sender)
    let valid = DroppedFiles.containsPdf(urls)
    if announce { onEvent?("dragEntered", ["valid": valid, "count": urls.count]) }
    return valid ? .copy : []
  }

  override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation { operation(for: sender, announce: true) }
  override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation { operation(for: sender, announce: false) }
  override func draggingExited(_ sender: NSDraggingInfo?) { onEvent?("dragExited", [:]) }

  override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
    guard acceptingDrops, let directory = stagingDirectory else { return false }
    let items = DroppedFiles.stage(fileURLs(sender), stagingDirectory: directory, using: authorization)
    onEvent?("dropped", ["items": items.map { $0.dictionary }])
    return true
  }
}

/// Registers the `studybot/file_drop` channel and the drop view.
final class FileDropChannel {
  private let dropView: FileDropView
  private var channel: FlutterMethodChannel?

  init(authorization: FolderAuthorization) {
    dropView = FileDropView(authorization: authorization)
  }

  func register(with messenger: FlutterBinaryMessenger, over view: NSView) {
    dropView.frame = view.bounds
    view.addSubview(dropView)
    let channel = FlutterMethodChannel(name: "studybot/file_drop", binaryMessenger: messenger)
    self.channel = channel
    dropView.onEvent = { [weak channel] name, arguments in
      DispatchQueue.main.async { channel?.invokeMethod(name, arguments: arguments) }
    }
    channel.setMethodCallHandler { [weak self] call, result in
      guard call.method == "setAccepting", let arguments = call.arguments as? [String: Any] else {
        return result(FlutterMethodNotImplemented)
      }
      self?.dropView.acceptingDrops = arguments["accepting"] as? Bool ?? false
      self?.dropView.stagingDirectory = arguments["stagingDirectory"] as? String
      result(nil)
    }
  }
}
#endif
