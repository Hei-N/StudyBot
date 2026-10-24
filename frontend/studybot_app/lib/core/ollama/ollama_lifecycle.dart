import 'dart:async';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../platform/ollama_launcher.dart';

/// How a startup check ended.
enum OllamaStartup {
  /// Ollama was already answering; nothing was launched.
  alreadyRunning,

  /// StudyBot launched Ollama and it became ready.
  started,

  /// Ollama is not reachable and the Ollama app is not installed.
  notInstalled,

  /// macOS could not open the Ollama app.
  launchFailed,

  /// Ollama was launched but its API did not answer in time.
  timedOut,

  /// A non-local Ollama address is configured, so nothing is launched.
  external,
}

/// Makes sure Ollama is answering before StudyBot's engine is judged unavailable.
///
/// Launches the Ollama app at most once per call, never twice at the same time, and never
/// stops it (other apps may use it). The wait is bounded.
class OllamaLifecycle {
  OllamaLifecycle({
    required this.launcher,
    this.probe,
    this.pollInterval = const Duration(milliseconds: 500),
    this.timeout = const Duration(seconds: 60),
    String? host,
  }) : host = host ?? defaultHost;

  static const defaultHost = 'http://127.0.0.1:11434';

  final OllamaLauncher launcher;
  final Duration pollInterval;
  final Duration timeout;
  final String host;

  /// Replaces the HTTP check (tests).
  final Future<bool> Function()? probe;
  Future<OllamaStartup>? _inFlight;

  /// Only the local default address is started by StudyBot.
  bool get _isLocal {
    final uri = Uri.tryParse(host);
    return uri != null && (uri.host == '127.0.0.1' || uri.host == 'localhost') && uri.port == 11434;
  }

  Future<bool> isRunning() => (probe ?? _httpProbe)();

  Future<bool> _httpProbe() async {
    final client = http.Client();
    try {
      final response = await client.get(Uri.parse('$host/api/tags')).timeout(const Duration(seconds: 2));
      return response.statusCode == 200;
    } on TimeoutException {
      return false;
    } on SocketException {
      return false;
    } on http.ClientException {
      return false;
    } finally {
      client.close();
    }
  }

  /// Checks Ollama and, if it is down, launches it once and waits. A second call while one
  /// is in progress shares the same attempt instead of launching again.
  Future<OllamaStartup> ensureRunning() => _inFlight ??= _run().whenComplete(() => _inFlight = null);

  Future<OllamaStartup> _run() async {
    if (await isRunning()) return OllamaStartup.alreadyRunning;
    if (!_isLocal) return OllamaStartup.external;
    if (!await launcher.isInstalled()) return OllamaStartup.notInstalled;
    try {
      await launcher.launch();
    } catch (_) {
      return OllamaStartup.launchFailed;
    }
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      if (await isRunning()) return OllamaStartup.started;
      await Future<void>.delayed(pollInterval);
    }
    return OllamaStartup.timedOut;
  }
}
