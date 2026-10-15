import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:studybot_app/core/api/connection_config.dart';
import 'package:studybot_app/core/backend/backend_launcher.dart';

Directory _tempDir(String prefix) {
  final dir = Directory.systemTemp.createTempSync(prefix);
  addTearDown(() => dir.deleteSync(recursive: true));
  return dir;
}

/// A fake `.app` with `Contents/MacOS/StudyBot`, optionally with the bundled engine.
String _fakeApp({required bool withBackend}) {
  final root = _tempDir('studybot_app_bundle');
  Directory('${root.path}/StudyBot.app/Contents/MacOS').createSync(recursive: true);
  if (withBackend) {
    final backend = File('${root.path}/StudyBot.app/Contents/${BackendResolver.bundledRelativePath}');
    backend.createSync(recursive: true);
  }
  return '${root.path}/StudyBot.app/Contents/MacOS/StudyBot';
}

Directory _fakeRepo() {
  final root = _tempDir('studybot_repo');
  File('${root.path}/pyproject.toml').writeAsStringSync('');
  Directory('${root.path}/src/studybot').createSync(recursive: true);
  File('${root.path}/.venv/bin/python').createSync(recursive: true);
  return root;
}

class _FakeProcess implements Process {
  _FakeProcess({this.port = 4321}) {
    final lines = '{"event": "studybot_api_ready", "host": "127.0.0.1", "port": $port, "token": "x"}\n';
    _stdout.add(utf8.encode(lines));
    _stdout.close();
    _stderr.close();
  }

  final int port;
  final _stdout = StreamController<List<int>>();
  final _stderr = StreamController<List<int>>();
  final _exit = Completer<int>();
  final _stdin = _FakeSink();
  final killed = <ProcessSignal>[];

  @override
  int get pid => 4242;
  @override
  Stream<List<int>> get stdout => _stdout.stream;
  @override
  Stream<List<int>> get stderr => _stderr.stream;
  @override
  IOSink get stdin => _stdin;
  @override
  Future<int> get exitCode => _exit.future;
  @override
  bool kill([ProcessSignal signal = ProcessSignal.sigterm]) {
    killed.add(signal);
    if (!_exit.isCompleted) _exit.complete(-15);
    return true;
  }

  /// The engine exits once its stdin is closed, like the real one.
  void exitOnStdinClose() => _stdin.onClose = () {
    if (!_exit.isCompleted) _exit.complete(0);
  };
}

class _FakeSink implements IOSink {
  void Function()? onClose;
  bool closed = false;

  @override
  Future close() async {
    closed = true;
    onClose?.call();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _Spawns {
  final commands = <BackendCommand>[];
  final environments = <Map<String, String>>[];
  final processes = <_FakeProcess>[];

  Future<Process> call(BackendCommand command, Map<String, String> environment) async {
    commands.add(command);
    environments.add(environment);
    final process = _FakeProcess(port: 4000 + processes.length)..exitOnStdinClose();
    processes.add(process);
    return process;
  }
}

BackendLauncher _launcher(BackendResolver resolver, _Spawns spawns, {bool healthy = true}) => BackendLauncher(
  resolver: resolver,
  startProcess: spawns.call,
  probeHealth: (ConnectionConfig _) async => healthy,
  startupTimeout: const Duration(seconds: 2),
);

void main() {
  group('DevRepoLocator', () {
    test('finds the repository by walking up from the executable', () {
      final root = _tempDir('studybot_repo');
      File('${root.path}/pyproject.toml').writeAsStringSync('');
      Directory('${root.path}/src/studybot').createSync(recursive: true);
      final deep = Directory('${root.path}/frontend/app/build/x')..createSync(recursive: true);

      final found = DevRepoLocator(environment: const {}, executable: '${deep.path}/studybot_app').locate();

      expect(found?.path, root.path);
    });

    test('returns null when no repository is above the executable', () {
      final dir = _tempDir('studybot_none');

      expect(DevRepoLocator(environment: const {}, executable: '${dir.path}/app').locate(), isNull);
    });

    test('an explicit root must actually be a repository', () {
      final dir = _tempDir('studybot_bad');

      expect(DevRepoLocator(environment: {'STUDYBOT_REPO_ROOT': dir.path}).locate(), isNull);
    });
  });

  group('BackendResolver', () {
    test('derives the bundled engine path from the app bundle location', () async {
      final exe = _fakeApp(withBackend: true);
      final support = _tempDir('studybot_support');

      final command = await BackendResolver(executablePath: exe, appSupportDirectory: () async => support).resolve();

      expect(command.source, BackendSource.bundled);
      expect(command.executable, endsWith('StudyBot.app/Contents/${BackendResolver.bundledRelativePath}'));
      expect(command.arguments, isEmpty);
    });

    test('passes the app support data directory to the bundled engine', () async {
      final exe = _fakeApp(withBackend: true);
      final support = _tempDir('studybot_support');

      final command = await BackendResolver(executablePath: exe, appSupportDirectory: () async => support).resolve();

      expect(command.environment['STUDYBOT_DATA_DIR'], '${support.path}/data');
      expect(Directory('${support.path}/data').existsSync(), isTrue);
    });

    test('the bundled engine wins over a valid repository', () async {
      final exe = _fakeApp(withBackend: true);
      final repo = _fakeRepo();
      final support = _tempDir('studybot_support');

      final command = await BackendResolver(
        executablePath: exe,
        devLocator: DevRepoLocator(environment: {'STUDYBOT_REPO_ROOT': repo.path}),
        appSupportDirectory: () async => support,
      ).resolve();

      expect(command.source, BackendSource.bundled);
    });

    test('falls back to the repository .venv in development when nothing is bundled', () async {
      final exe = _fakeApp(withBackend: false);
      final repo = _fakeRepo();

      final command = await BackendResolver(
        executablePath: exe,
        devLocator: DevRepoLocator(environment: {'STUDYBOT_REPO_ROOT': repo.path}),
      ).resolve();

      expect(command.source, BackendSource.development);
      expect(command.executable, '${repo.path}/.venv/bin/python');
      expect(command.arguments, ['-m', 'studybot.api']);
      expect(command.environment.containsKey('STUDYBOT_DATA_DIR'), isFalse);
    });

    test('a packaged build with no bundled engine fails and never uses a repository or system Python', () async {
      final exe = _fakeApp(withBackend: false);
      final repo = _fakeRepo();

      final resolver = BackendResolver(
        executablePath: exe,
        allowDevelopment: false,
        devLocator: DevRepoLocator(environment: {'STUDYBOT_REPO_ROOT': repo.path}),
      );

      await expectLater(resolver.resolve(), throwsA(isA<BackendLaunchException>()));
    });

    test('fails cleanly when nothing is bundled and no repository exists', () async {
      final exe = _fakeApp(withBackend: false);
      final resolver = BackendResolver(
        executablePath: exe,
        devLocator: DevRepoLocator(environment: const {}, executable: exe),
      );

      await expectLater(resolver.resolve(), throwsA(isA<BackendLaunchException>()));
    });
  });

  group('BackendLauncher (fake process)', () {
    late BackendResolver bundled;

    setUp(() {
      final exe = _fakeApp(withBackend: true);
      final support = _tempDir('studybot_support');
      bundled = BackendResolver(executablePath: exe, appSupportDirectory: () async => support);
    });

    test('starts the bundled engine with a private token, a free port and the data directory', () async {
      final spawns = _Spawns();

      final handle = await _launcher(bundled, spawns).start();

      final env = spawns.environments.single;
      expect(handle.source, BackendSource.bundled);
      expect(env['STUDYBOT_API_PORT'], '0');
      expect(env['STUDYBOT_EXIT_WHEN_STDIN_CLOSES'], '1');
      expect(env['STUDYBOT_MODEL_PROVIDER'], 'ollama');
      expect(env['STUDYBOT_DATA_DIR'], endsWith('/data'));
      expect(env['STUDYBOT_API_TOKEN'], handle.config.token);
      expect(handle.config.baseUrl, 'http://127.0.0.1:4000');
      expect(spawns.commands.single.executable, contains('studybot_backend'));
      await handle.stop();
    });

    test('every start gets a new token and its own process', () async {
      final spawns = _Spawns();
      final launcher = _launcher(bundled, spawns);

      final first = await launcher.start();
      final second = await launcher.start();

      expect(first.config.token, isNot(second.config.token));
      expect(first.config.token.length, greaterThanOrEqualTo(40));
      expect(spawns.processes, hasLength(2));
      await first.stop();
      await second.stop();
    });

    test('the token is not written to disk by the launcher', () async {
      final spawns = _Spawns();
      final before = Directory.systemTemp.listSync().length;

      final handle = await _launcher(bundled, spawns).start();
      await handle.stop();

      final after = Directory.systemTemp.listSync();
      expect(after.length, before);
      for (final entity in after.whereType<File>().where((f) => f.path.contains('studybot'))) {
        expect(entity.readAsStringSync(), isNot(contains(handle.config.token)));
      }
    });

    test('stop closes stdin and does not kill an engine that exits by itself', () async {
      final spawns = _Spawns();

      final handle = await _launcher(bundled, spawns).start();
      await handle.stop();

      final process = spawns.processes.single;
      expect((process.stdin as _FakeSink).closed, isTrue);
      expect(process.killed, isEmpty);
    });

    test('an engine that never answers health is killed and reported', () async {
      final spawns = _Spawns();

      await expectLater(_launcher(bundled, spawns, healthy: false).start(), throwsA(isA<BackendLaunchException>()));

      expect(spawns.processes.single.killed, contains(ProcessSignal.sigkill));
    });

    test('retry after a failed start spawns a fresh engine', () async {
      final spawns = _Spawns();
      var healthy = false;
      final launcher = BackendLauncher(
        resolver: bundled,
        startProcess: spawns.call,
        probeHealth: (_) async => healthy,
        startupTimeout: const Duration(milliseconds: 600),
      );

      await expectLater(launcher.start(), throwsA(isA<BackendLaunchException>()));
      healthy = true;
      final handle = await launcher.start();

      expect(spawns.processes, hasLength(2));
      expect(handle.config.baseUrl, 'http://127.0.0.1:4001');
      await handle.stop();
    });

    test('a missing bundled engine in a packaged build fails without spawning anything', () async {
      final spawns = _Spawns();
      final launcher = _launcher(
        BackendResolver(executablePath: _fakeApp(withBackend: false), allowDevelopment: false),
        spawns,
      );

      await expectLater(launcher.start(), throwsA(isA<BackendLaunchException>()));

      expect(spawns.processes, isEmpty);
    });
  });

  group('BackendLauncher with the real development engine', () {
    final root = DevRepoLocator(environment: const {}, executable: '${Directory.current.path}/test_runner').locate();
    final canRun = root != null && DevRepoLocator.pythonIn(root).existsSync();

    test('starts, answers with its private token, and exits on stop', () async {
      final data = _tempDir('studybot_data');
      final launcher = BackendLauncher(
        resolver: BackendResolver(devLocator: DevRepoLocator(environment: {'STUDYBOT_REPO_ROOT': root!.path})),
        extraEnvironment: {'STUDYBOT_DATA_DIR': data.path, 'STUDYBOT_MODEL_PROVIDER': 'mock'},
      );

      final handle = await launcher.start();
      final url = handle.config.httpBase.resolve('/api/v1/health');
      final ok = await http.get(url, headers: {'Authorization': 'Bearer ${handle.config.token}'});
      final denied = await http.get(url);
      await handle.stop();

      expect(handle.source, BackendSource.development);
      expect(ok.statusCode, 200);
      expect(denied.statusCode, 401);
      await expectLater(http.get(url).timeout(const Duration(seconds: 3)), throwsA(anything));
    }, skip: canRun ? false : 'no .venv in this checkout');
  });
}
