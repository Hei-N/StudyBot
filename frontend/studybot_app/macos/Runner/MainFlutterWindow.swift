import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  private let libraryAuthorization = LibraryAuthorizationChannel()
  private let ollamaLauncher = OllamaLauncherChannel()
  private let fileDrop = FileDropChannel(authorization: FolderAuthorization())

  override func awakeFromNib() {
    let flutterViewController = FlutterViewController()
    let windowFrame = self.frame
    self.contentViewController = flutterViewController
    self.setFrame(windowFrame, display: true)

    RegisterGeneratedPlugins(registry: flutterViewController)
    libraryAuthorization.register(with: flutterViewController.engine.binaryMessenger)
    ollamaLauncher.register(with: flutterViewController.engine.binaryMessenger)
    fileDrop.register(with: flutterViewController.engine.binaryMessenger, over: flutterViewController.view)

    super.awakeFromNib()
  }
}
