import 'package:shared_preferences/shared_preferences.dart';

/// Where the Study Bot engine is and how to authenticate with it.
///
/// Stage 5.5's Python API is launched separately (see API_CONTRACT.md) and
/// prints its port + bearer token to stdout on startup; there is no
/// auto-launch or discovery here yet, so the user enters both once in
/// Settings and they're remembered for next time. The token is never
/// hardcoded and never bundled with the app.
class ConnectionConfig {
  const ConnectionConfig({required this.baseUrl, required this.token});

  /// Matches the Python API's own default port (see `studybot.api.__main__`).
  static const defaultBaseUrl = 'http://127.0.0.1:8765';

  static const _baseUrlKey = 'studybot.connection.baseUrl';
  static const _tokenKey = 'studybot.connection.token';

  final String baseUrl;
  final String token;

  bool get isConfigured => baseUrl.trim().isNotEmpty && token.trim().isNotEmpty;

  Uri get httpBase => Uri.parse(baseUrl.trim());

  Uri get wsBase {
    final http = httpBase;
    final scheme = http.scheme == 'https' ? 'wss' : 'ws';
    return http.replace(scheme: scheme);
  }

  ConnectionConfig copyWith({String? baseUrl, String? token}) {
    return ConnectionConfig(baseUrl: baseUrl ?? this.baseUrl, token: token ?? this.token);
  }

  static Future<ConnectionConfig> load() async {
    final prefs = await SharedPreferences.getInstance();
    return ConnectionConfig(
      baseUrl: prefs.getString(_baseUrlKey) ?? defaultBaseUrl,
      token: prefs.getString(_tokenKey) ?? '',
    );
  }

  Future<void> save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_baseUrlKey, baseUrl);
    await prefs.setString(_tokenKey, token);
  }
}
