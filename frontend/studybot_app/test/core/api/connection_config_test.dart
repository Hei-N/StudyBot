import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:studybot_app/core/api/connection_config.dart';

void main() {
  test('isConfigured requires both a non-blank URL and token', () {
    expect(const ConnectionConfig(baseUrl: 'http://x', token: 'abc').isConfigured, isTrue);
    expect(const ConnectionConfig(baseUrl: '', token: 'abc').isConfigured, isFalse);
    expect(const ConnectionConfig(baseUrl: 'http://x', token: '  ').isConfigured, isFalse);
  });

  group('wsBase', () {
    test('derives ws:// from http://', () {
      const config = ConnectionConfig(baseUrl: 'http://127.0.0.1:8765', token: 't');
      expect(config.wsBase.scheme, 'ws');
      expect(config.wsBase.host, '127.0.0.1');
      expect(config.wsBase.port, 8765);
    });

    test('derives wss:// from https://', () {
      const config = ConnectionConfig(baseUrl: 'https://engine.example.com', token: 't');
      expect(config.wsBase.scheme, 'wss');
    });
  });

  test('copyWith replaces only the given fields', () {
    const original = ConnectionConfig(baseUrl: 'http://a', token: 'tok');
    final updated = original.copyWith(baseUrl: 'http://b');
    expect(updated.baseUrl, 'http://b');
    expect(updated.token, 'tok');
  });

  test('load/save round-trip through shared_preferences', () async {
    SharedPreferences.setMockInitialValues({});
    const config = ConnectionConfig(baseUrl: 'http://saved:1234', token: 'secret');
    await config.save();

    final loaded = await ConnectionConfig.load();
    expect(loaded.baseUrl, 'http://saved:1234');
    expect(loaded.token, 'secret');
  });

  test('load defaults to the standard local port with an empty token when nothing is stored', () async {
    SharedPreferences.setMockInitialValues({});
    final loaded = await ConnectionConfig.load();
    expect(loaded.baseUrl, ConnectionConfig.defaultBaseUrl);
    expect(loaded.token, '');
  });
}
