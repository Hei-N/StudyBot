import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/ollama/ollama_lifecycle.dart';
import 'package:studybot_app/core/platform/ollama_launcher.dart';

class _FakeLauncher implements OllamaLauncher {
  _FakeLauncher({this.installed = true, this.failLaunch = false});

  final bool installed;
  final bool failLaunch;
  int launches = 0;
  void Function()? onLaunch;

  @override
  Future<bool> isInstalled() async => installed;

  @override
  Future<void> launch() async {
    launches++;
    if (failLaunch) throw Exception('cannot open');
    onLaunch?.call();
  }
}

OllamaLifecycle _lifecycle(
  _FakeLauncher launcher,
  bool Function() running, {
  String? host,
  Duration timeout = const Duration(milliseconds: 300),
}) => OllamaLifecycle(
  launcher: launcher,
  probe: () async => running(),
  pollInterval: const Duration(milliseconds: 10),
  timeout: timeout,
  host: host,
);

void main() {
  test('an already-running Ollama is left alone', () async {
    final launcher = _FakeLauncher();

    final result = await _lifecycle(launcher, () => true).ensureRunning();

    expect(result, OllamaStartup.alreadyRunning);
    expect(launcher.launches, 0);
  });

  test('a stopped Ollama is launched once and the wait ends as soon as it answers', () async {
    var running = false;
    final launcher = _FakeLauncher()
      ..onLaunch = () => Future<void>.delayed(const Duration(milliseconds: 60), () => running = true);

    final result = await _lifecycle(launcher, () => running).ensureRunning();

    expect(result, OllamaStartup.started);
    expect(launcher.launches, 1);
  });

  test('concurrent checks share one launch', () async {
    var running = false;
    final launcher = _FakeLauncher()
      ..onLaunch = () => Future<void>.delayed(const Duration(milliseconds: 60), () => running = true);
    final lifecycle = _lifecycle(launcher, () => running);

    final results = await Future.wait([
      lifecycle.ensureRunning(),
      lifecycle.ensureRunning(),
      lifecycle.ensureRunning(),
    ]);

    expect(results, everyElement(OllamaStartup.started));
    expect(launcher.launches, 1);
  });

  test('an Ollama that never answers times out after a bounded wait', () async {
    final launcher = _FakeLauncher();
    final began = DateTime.now();

    final result = await _lifecycle(launcher, () => false, timeout: const Duration(milliseconds: 120)).ensureRunning();

    expect(result, OllamaStartup.timedOut);
    expect(launcher.launches, 1);
    expect(DateTime.now().difference(began), lessThan(const Duration(seconds: 2)));
  });

  test('a missing Ollama app is reported without launching', () async {
    final launcher = _FakeLauncher(installed: false);

    final result = await _lifecycle(launcher, () => false).ensureRunning();

    expect(result, OllamaStartup.notInstalled);
    expect(launcher.launches, 0);
  });

  test('a launch failure is reported and not retried by itself', () async {
    final launcher = _FakeLauncher(failLaunch: true);

    final result = await _lifecycle(launcher, () => false).ensureRunning();

    expect(result, OllamaStartup.launchFailed);
    expect(launcher.launches, 1);
  });

  test('a non-local Ollama address is never launched locally', () async {
    final launcher = _FakeLauncher();

    final result = await _lifecycle(launcher, () => false, host: 'http://192.168.1.20:11434').ensureRunning();

    expect(result, OllamaStartup.external);
    expect(launcher.launches, 0);
  });

  test('a later check after a failure launches again (Retry)', () async {
    var running = false;
    final launcher = _FakeLauncher();
    final lifecycle = _lifecycle(launcher, () => running, timeout: const Duration(milliseconds: 80));

    expect(await lifecycle.ensureRunning(), OllamaStartup.timedOut);
    running = true;
    expect(await lifecycle.ensureRunning(), OllamaStartup.alreadyRunning);
    expect(launcher.launches, 1);
  });

  test('retry after a timeout launches once more', () async {
    var running = false;
    final launcher = _FakeLauncher();
    final lifecycle = _lifecycle(launcher, () => running, timeout: const Duration(milliseconds: 80));

    await lifecycle.ensureRunning();
    launcher.onLaunch = () => running = true;
    final second = await lifecycle.ensureRunning();

    expect(second, OllamaStartup.started);
    expect(launcher.launches, 2);
  });
}
