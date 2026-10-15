import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:studybot_app/core/backend/backend_launcher.dart';

Directory? _repoRoot() =>
    DevRepoLocator(environment: const {}, executable: '${Directory.current.path}/test_runner').locate();

void main() {
  group('DevRepoLocator', () {
    test('finds the repository by walking up from the executable', () {
      final root = Directory.systemTemp.createTempSync('studybot_repo');
      addTearDown(() => root.deleteSync(recursive: true));
      File('${root.path}/pyproject.toml').writeAsStringSync('');
      Directory('${root.path}/src/studybot').createSync(recursive: true);
      final deep = Directory('${root.path}/frontend/app/build/x')..createSync(recursive: true);

      final found = DevRepoLocator(environment: const {}, executable: '${deep.path}/studybot_app').locate();

      expect(found?.path, root.path);
    });

    test('returns null when no repository is above the executable', () {
      final dir = Directory.systemTemp.createTempSync('studybot_none');
      addTearDown(() => dir.deleteSync(recursive: true));

      expect(DevRepoLocator(environment: const {}, executable: '${dir.path}/app').locate(), isNull);
    });

    test('an explicit root must actually be a repository', () {
      final dir = Directory.systemTemp.createTempSync('studybot_bad');
      addTearDown(() => dir.deleteSync(recursive: true));

      expect(DevRepoLocator(environment: {'STUDYBOT_REPO_ROOT': dir.path}).locate(), isNull);
    });
  });

  group('BackendLauncher with the real engine', () {
    final root = _repoRoot();
    final python = root == null ? null : DevRepoLocator.pythonIn(root);
    final canRun = python != null && python.existsSync();

    test('starts, answers with its private token, and exits on stop', () async {
      final data = Directory.systemTemp.createTempSync('studybot_data');
      addTearDown(() => data.deleteSync(recursive: true));
      final launcher = BackendLauncher(
        locator: DevRepoLocator(environment: {'STUDYBOT_REPO_ROOT': root!.path}),
        extraEnvironment: {'STUDYBOT_DATA_DIR': data.path, 'STUDYBOT_MODEL_PROVIDER': 'mock'},
      );

      final handle = await launcher.start();
      final url = handle.config.httpBase.resolve('/api/v1/health');
      final ok = await http.get(url, headers: {'Authorization': 'Bearer ${handle.config.token}'});
      final denied = await http.get(url);
      await handle.stop();

      expect(ok.statusCode, 200);
      expect(denied.statusCode, 401);
      await expectLater(http.get(url).timeout(const Duration(seconds: 3)), throwsA(anything));
    }, skip: canRun ? false : 'no .venv in this checkout');
  });
}
