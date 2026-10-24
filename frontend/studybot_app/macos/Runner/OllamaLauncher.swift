import Cocoa
#if canImport(FlutterMacOS)
import FlutterMacOS
#endif

/// Opens the Ollama desktop app through LaunchServices. The app then runs independently of
/// StudyBot's sandbox; StudyBot never runs an Ollama program itself.
enum OllamaLauncher {
  static let bundleIdentifier = "com.electron.ollama"

  static func isInstalled() -> Bool {
    NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleIdentifier) != nil
  }

  /// Launches Ollama.app hidden (menu-bar only, no window), without activating it.
  /// If it is already running, macOS reuses that instance.
  static func launch(completion: @escaping (Bool) -> Void) {
    guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleIdentifier) else {
      return completion(false)
    }
    let configuration = NSWorkspace.OpenConfiguration()
    configuration.activates = false
    configuration.addsToRecentItems = false
    configuration.hides = true
    configuration.arguments = ["hidden"]
    NSWorkspace.shared.openApplication(at: url, configuration: configuration) { _, error in
      completion(error == nil)
    }
  }
}

#if canImport(FlutterMacOS)
/// Registers the `studybot/ollama_launcher` channel.
final class OllamaLauncherChannel {
  func register(with messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: "studybot/ollama_launcher", binaryMessenger: messenger)
    channel.setMethodCallHandler { call, result in
      switch call.method {
      case "isInstalled":
        result(OllamaLauncher.isInstalled())
      case "launch":
        OllamaLauncher.launch { launched in
          DispatchQueue.main.async {
            result(launched ? true : FlutterError(code: "launch_failed", message: nil, details: nil))
          }
        }
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }
}
#endif
