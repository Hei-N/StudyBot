import 'package:flutter/services.dart';

/// Opens the Ollama desktop app. Implemented natively on macOS through LaunchServices,
/// so Ollama runs outside StudyBot's sandbox; StudyBot never runs an Ollama program.
abstract class OllamaLauncher {
  Future<bool> isInstalled();

  /// Asks the system to open Ollama hidden (menu bar only). Throws if it cannot be opened.
  Future<void> launch();
}

class MacOSOllamaLauncher implements OllamaLauncher {
  MacOSOllamaLauncher({MethodChannel? channel}) : _channel = channel ?? const MethodChannel('studybot/ollama_launcher');

  final MethodChannel _channel;

  @override
  Future<bool> isInstalled() async {
    try {
      return await _channel.invokeMethod<bool>('isInstalled') ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false;
    }
  }

  @override
  Future<void> launch() async {
    await _channel.invokeMethod<bool>('launch');
  }
}
