import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:http/http.dart' as http;

import '../api/connection_config.dart';

/// Why the development backend could not be started.
class BackendLaunchException implements Exception {
  const BackendLaunchException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// A running engine process started by this app.
class BackendHandle {
  BackendHandle._(this._process, this.config, this.source);

  final Process _process;

  /// Which kind of engine this is.
  final BackendSource source;

  /// Where the engine listens and the token only this app and the engine know.
  final ConnectionConfig config;

  /// Asks the engine to exit (closing its stdin is the shutdown signal) and
  /// kills it if it has not exited shortly after.
  Future<void> stop() async {
    try {
      await _process.stdin.close();
    } catch (_) {
      // Already closed.
    }
    final exited = await _process.exitCode.timeout(
      const Duration(seconds: 5),
      onTimeout: () {
        _process.kill(ProcessSignal.sigterm);
        return -1;
      },
    );
    if (exited == -1) {
      await _process.exitCode.timeout(
        const Duration(seconds: 3),
        onTimeout: () {
          _process.kill(ProcessSignal.sigkill);
          return -1;
        },
      );
    }
  }
}

/// Where the engine executable came from.
enum BackendSource { bundled, development }

/// A resolved way to start the engine.
class BackendCommand {
  const BackendCommand({
    required this.source,
    required this.executable,
    this.arguments = const [],
    this.workingDirectory,
    this.environment = const {},
  });

  final BackendSource source;
  final String executable;
  final List<String> arguments;
  final String? workingDirectory;
  final Map<String, String> environment;
}

/// Chooses the engine to start: the one bundled inside the app, else (when
/// allowed) the repository's `.venv`, else fail. It never falls back to a
/// system Python and never searches arbitrary directories.
class BackendResolver {
  const BackendResolver({
    this.executablePath,
    this.allowDevelopment = true,
    this.devLocator = const DevRepoLocator(),
    this.appSupportDirectory = _noAppSupport,
  });

  /// The running app's executable (`.../StudyBot.app/Contents/MacOS/StudyBot`).
  final String? executablePath;

  /// Whether the repository `.venv` may be used when no bundled engine exists.
  final bool allowDevelopment;
  final DevRepoLocator devLocator;

  /// The app's private writable data location, used for a bundled engine.
  final Future<Directory> Function() appSupportDirectory;

  static Future<Directory> _noAppSupport() => throw UnsupportedError('No app support directory');

  /// Relative to `Contents/`, matching `scripts/build_macos_app.sh`.
  static const bundledRelativePath = 'Resources/studybot_backend/studybot-backend';

  /// The bundled engine for the app at [executablePath], if present.
  File? bundledExecutable() {
    final exe = File(executablePath ?? Platform.resolvedExecutable);
    final contents = exe.parent.parent;
    if (contents.uri.pathSegments.where((s) => s.isNotEmpty).last != 'Contents') return null;
    final backend = File('${contents.path}/$bundledRelativePath');
    return backend.existsSync() ? backend : null;
  }

  Future<BackendCommand> resolve() async {
    final bundled = bundledExecutable();
    if (bundled != null) {
      final data = Directory('${(await appSupportDirectory()).path}/data');
      data.createSync(recursive: true);
      return BackendCommand(
        source: BackendSource.bundled,
        executable: bundled.path,
        workingDirectory: data.path,
        environment: {'STUDYBOT_DATA_DIR': data.path},
      );
    }
    if (!allowDevelopment) {
      throw const BackendLaunchException('The StudyBot engine is missing from this app. Reinstall StudyBot.');
    }
    final root = devLocator.locate();
    if (root == null) {
      throw const BackendLaunchException('Could not find the StudyBot repository. Set STUDYBOT_REPO_ROOT to its path.');
    }
    final python = DevRepoLocator.pythonIn(root);
    if (!python.existsSync()) {
      throw BackendLaunchException(
        'No Python environment at ${python.path}. Run: python3 -m venv .venv && '
        '.venv/bin/pip install -e ".[dev]"',
      );
    }
    return BackendCommand(
      source: BackendSource.development,
      executable: python.path,
      arguments: const ['-m', 'studybot.api'],
      workingDirectory: root.path,
    );
  }
}

/// Finds the StudyBot repository this app was built from, so a development
/// run can start the engine from that repository's `.venv`.
///
/// Development-only: a distributable build would bundle its own Python and
/// replace this class, leaving [BackendLauncher]'s lifecycle untouched.
class DevRepoLocator {
  const DevRepoLocator({this.environment, this.executable});

  final Map<String, String>? environment;
  final String? executable;

  static const _rootVariable = 'STUDYBOT_REPO_ROOT';

  /// The repository root, or null when none is found.
  Directory? locate() {
    final env = environment ?? Platform.environment;
    final explicit = env[_rootVariable];
    if (explicit != null && explicit.isNotEmpty) {
      final dir = Directory(explicit);
      return _isRepoRoot(dir) ? dir : null;
    }
    var dir = File(executable ?? Platform.resolvedExecutable).parent;
    for (var i = 0; i < 12; i++) {
      if (_isRepoRoot(dir)) return dir;
      final parent = dir.parent;
      if (parent.path == dir.path) break;
      dir = parent;
    }
    return null;
  }

  static bool _isRepoRoot(Directory dir) =>
      File('${dir.path}/pyproject.toml').existsSync() && Directory('${dir.path}/src/studybot').existsSync();

  static File pythonIn(Directory root) => File('${root.path}/.venv/bin/python');
}

/// Starts and stops the engine for development runs.
///
/// The token is generated here, handed to the engine through its environment
/// (never argv or logs), and used by the app directly. The engine gets an
/// OS-assigned port so it can't collide with a hand-started server, and
/// exits when this app's pipe to it closes, however the app ends.
class BackendLauncher {
  BackendLauncher({
    this.resolver = const BackendResolver(),
    this.startupTimeout = const Duration(seconds: 90),
    this.extraEnvironment = const {},
    this.startProcess = _startProcess,
    this.probeHealth = _probeHealth,
    Random? random,
  }) : _random = random ?? Random.secure();

  final BackendResolver resolver;
  final Duration startupTimeout;

  /// Added to the engine's environment (tests point it at a temporary data directory).
  final Map<String, String> extraEnvironment;

  /// Process and health seams, replaced in tests.
  final Future<Process> Function(BackendCommand command, Map<String, String> environment) startProcess;
  final Future<bool> Function(ConnectionConfig config) probeHealth;
  final Random _random;

  static Future<Process> _startProcess(BackendCommand command, Map<String, String> environment) => Process.start(
    command.executable,
    command.arguments,
    workingDirectory: command.workingDirectory,
    environment: environment,
  );

  static Future<bool> _probeHealth(ConnectionConfig config) async {
    final client = http.Client();
    try {
      final response = await client
          .get(config.httpBase.resolve('/api/v1/health'), headers: {'Authorization': 'Bearer ${config.token}'})
          .timeout(const Duration(seconds: 5));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    } finally {
      client.close();
    }
  }

  static final _pidFile = File('${Directory.systemTemp.path}/studybot-dev-engine.pid');

  Future<BackendHandle> start() async {
    final command = await resolver.resolve();
    if (command.source == BackendSource.development) await _stopLeftoverEngine();

    final token = _newToken();
    final process = await startProcess(command, {
      ...Platform.environment,
      'STUDYBOT_API_TOKEN': token,
      'STUDYBOT_API_PORT': '0',
      'STUDYBOT_EXIT_WHEN_STDIN_CLOSES': '1',
      if (command.source == BackendSource.bundled || !Platform.environment.containsKey('STUDYBOT_MODEL_PROVIDER'))
        'STUDYBOT_MODEL_PROVIDER': 'ollama',
      ...command.environment,
      ...extraEnvironment,
    });
    if (command.source == BackendSource.development) _pidFile.writeAsStringSync('${process.pid}');

    final errorTail = <String>[];
    process.stderr.transform(utf8.decoder).transform(const LineSplitter()).listen((line) {
      errorTail.add(line);
      if (errorTail.length > 20) errorTail.removeAt(0);
    });

    try {
      final port = await _readPort(process).timeout(startupTimeout);
      final config = ConnectionConfig(baseUrl: 'http://127.0.0.1:$port', token: token);
      await _waitForHealth(config).timeout(startupTimeout);
      return BackendHandle._(process, config, command.source);
    } on TimeoutException {
      process.kill(ProcessSignal.sigkill);
      throw const BackendLaunchException('The engine did not become ready in time.');
    } on BackendLaunchException {
      process.kill(ProcessSignal.sigkill);
      rethrow;
    } catch (_) {
      process.kill(ProcessSignal.sigkill);
      final detail = errorTail.isEmpty ? '' : '\n${errorTail.last}';
      throw BackendLaunchException('The engine failed to start.$detail');
    }
  }

  /// The handshake line is the only stdout the engine writes; only the port is
  /// taken from it.
  Future<int> _readPort(Process process) async {
    await for (final line in process.stdout.transform(utf8.decoder).transform(const LineSplitter())) {
      try {
        final event = jsonDecode(line);
        if (event is Map && event['event'] == 'studybot_api_ready') {
          return event['port'] as int;
        }
      } catch (_) {
        continue;
      }
    }
    throw const BackendLaunchException('The engine exited before it was ready.');
  }

  Future<void> _waitForHealth(ConnectionConfig config) async {
    while (!await probeHealth(config)) {
      await Future<void>.delayed(const Duration(milliseconds: 250));
    }
  }

  String _newToken() {
    final bytes = List<int>.generate(32, (_) => _random.nextInt(256));
    return base64Url.encode(bytes).replaceAll('=', '');
  }

  /// A hot restart or crash can leave the previous engine running with no
  /// app attached; stop it so only one engine owns the data directory.
  Future<void> _stopLeftoverEngine() async {
    try {
      if (!_pidFile.existsSync()) return;
      final pid = int.tryParse(_pidFile.readAsStringSync().trim());
      _pidFile.deleteSync();
      if (pid == null) return;
      final result = await Process.run('ps', ['-p', '$pid', '-o', 'command=']);
      if (result.exitCode == 0 && (result.stdout as String).contains('studybot.api')) {
        Process.killPid(pid, ProcessSignal.sigterm);
        await Future<void>.delayed(const Duration(seconds: 1));
      }
    } catch (_) {
      // Best effort.
    }
  }
}
