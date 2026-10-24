import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  private let libraryAuthorization = LibraryAuthorizationChannel()
  private let ollamaLauncher = OllamaLauncherChannel()

  override func awakeFromNib() {
    let flutterViewController = FlutterViewController()
    let windowFrame = self.frame
    self.contentViewController = flutterViewController
    self.setFrame(windowFrame, display: true)

    RegisterGeneratedPlugins(registry: flutterViewController)
    libraryAuthorization.register(with: flutterViewController.engine.binaryMessenger)
    ollamaLauncher.register(with: flutterViewController.engine.binaryMessenger)

    super.awakeFromNib()
  }
}
