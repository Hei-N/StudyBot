import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../models/chat.dart';
import '../models/course.dart';
import '../models/health.dart';
import '../models/message.dart';
import '../models/reasoning_mode.dart';
import '../models/teaching_mode.dart';
import 'api_exception.dart';
import 'connection_config.dart';

/// Typed HTTP client for the `/api/v1/...` endpoints in API_CONTRACT.md.
///
/// This is the only place that knows the API's URL shapes and JSON field
/// names — everything above it (providers, widgets) works with the typed
/// models in `core/models/`. Every failure — network-level or a structured
/// `{code, message}` error body — surfaces as an [ApiException], never a
/// raw exception or stack trace.
class StudyBotApi {
  StudyBotApi(this.config, {http.Client? client}) : _client = client ?? http.Client();

  final ConnectionConfig config;
  final http.Client _client;

  static const _timeout = Duration(seconds: 30);

  Uri _uri(String path, [Map<String, String>? query]) {
    final base = config.httpBase;
    return base.replace(
      path: '${base.path}/api/v1$path'.replaceAll('//', '/'),
      queryParameters: query,
    );
  }

  Map<String, String> get _headers => {
    'Authorization': 'Bearer ${config.token}',
    'Content-Type': 'application/json',
  };

  Future<dynamic> _send(Future<http.Response> Function() request) async {
    late http.Response response;
    try {
      response = await request().timeout(_timeout);
    } on TimeoutException {
      throw ApiException.disconnected('The Study Bot engine did not respond in time.');
    } on SocketException {
      throw ApiException.disconnected('Could not reach the Study Bot engine.');
    } on http.ClientException catch (e) {
      throw ApiException.disconnected(e.message);
    }

    final bodyText = response.body;
    final decoded = bodyText.isEmpty ? null : jsonDecode(bodyText);

    if (response.statusCode >= 200 && response.statusCode < 300) {
      return decoded;
    }

    if (decoded is Map<String, dynamic>) {
      throw ApiException.fromJson(decoded, statusCode: response.statusCode);
    }
    throw ApiException(
      code: ApiErrorCode.internalError,
      message: 'Unexpected response (status ${response.statusCode}).',
      statusCode: response.statusCode,
    );
  }

  Future<EngineHealth> getHealth() async {
    final json = await _send(() => _client.get(_uri('/health'), headers: _headers));
    return EngineHealth.fromJson(json as Map<String, dynamic>);
  }

  // --- courses -----------------------------------------------------------------

  Future<List<Course>> listCourses() async {
    final json = await _send(() => _client.get(_uri('/courses'), headers: _headers));
    return (json as List).cast<Map<String, dynamic>>().map(Course.fromJson).toList();
  }

  Future<Course> createCourse({required String name, String? code, String? term, String? description}) async {
    final json = await _send(
      () => _client.post(
        _uri('/courses'),
        headers: _headers,
        body: jsonEncode({'name': name, 'code': code, 'term': term, 'description': description}),
      ),
    );
    return Course.fromJson(json as Map<String, dynamic>);
  }

  Future<Course> updateCourse(
    String courseId, {
    required String name,
    String? code,
    String? term,
    String? description,
  }) async {
    final json = await _send(
      () => _client.put(
        _uri('/courses/$courseId'),
        headers: _headers,
        body: jsonEncode({'name': name, 'code': code, 'term': term, 'description': description}),
      ),
    );
    return Course.fromJson(json as Map<String, dynamic>);
  }

  Future<void> deleteCourse(String courseId) async {
    await _send(() => _client.delete(_uri('/courses/$courseId'), headers: _headers));
  }

  // --- teaching modes ------------------------------------------------------------

  Future<List<TeachingModeInfo>> listModes() async {
    final json = await _send(() => _client.get(_uri('/modes'), headers: _headers));
    return (json as List).cast<Map<String, dynamic>>().map(TeachingModeInfo.fromJson).toList();
  }

  // --- reasoning modes -------------------------------------------------------------

  Future<List<ReasoningModeInfo>> listReasoningModes() async {
    final json = await _send(() => _client.get(_uri('/reasoning-modes'), headers: _headers));
    return (json as List).cast<Map<String, dynamic>>().map(ReasoningModeInfo.fromJson).toList();
  }

  // --- chats ---------------------------------------------------------------------

  Future<List<Chat>> listChats({String? courseId}) async {
    final query = courseId == null ? null : {'course_id': courseId};
    final json = await _send(() => _client.get(_uri('/chats', query), headers: _headers));
    return (json as List).cast<Map<String, dynamic>>().map(Chat.fromJson).toList();
  }

  Future<Chat> createChat({String? courseId}) async {
    final json = await _send(
      () => _client.post(_uri('/chats'), headers: _headers, body: jsonEncode({'courseId': courseId})),
    );
    return Chat.fromJson(json as Map<String, dynamic>);
  }

  Future<Chat> getChat(String chatId) async {
    final json = await _send(() => _client.get(_uri('/chats/$chatId'), headers: _headers));
    return Chat.fromJson(json as Map<String, dynamic>);
  }

  Future<List<ChatMessage>> getChatMessages(String chatId) async {
    final json = await _send(() => _client.get(_uri('/chats/$chatId/messages'), headers: _headers));
    return (json as List).cast<Map<String, dynamic>>().map(ChatMessage.fromJson).toList();
  }

  Future<Chat> renameChat(String chatId, String title) async {
    final json = await _send(
      () => _client.put(_uri('/chats/$chatId/rename'), headers: _headers, body: jsonEncode({'title': title})),
    );
    return Chat.fromJson(json as Map<String, dynamic>);
  }

  Future<Chat> clearChat(String chatId) async {
    final json = await _send(() => _client.post(_uri('/chats/$chatId/clear'), headers: _headers));
    return Chat.fromJson(json as Map<String, dynamic>);
  }

  Future<void> deleteChat(String chatId) async {
    await _send(() => _client.delete(_uri('/chats/$chatId'), headers: _headers));
  }

  Future<Chat> setChatCourse(String chatId, String? courseId) async {
    final json = await _send(
      () => _client.put(
        _uri('/chats/$chatId/course'),
        headers: _headers,
        body: jsonEncode({'courseId': courseId}),
      ),
    );
    return Chat.fromJson(json as Map<String, dynamic>);
  }

  Future<TeachingModeInfo> getChatMode(String chatId) async {
    final json = await _send(() => _client.get(_uri('/chats/$chatId/mode'), headers: _headers));
    return TeachingModeInfo.fromJson(json as Map<String, dynamic>);
  }

  Future<TeachingModeInfo> setChatMode(String chatId, String mode) async {
    final json = await _send(
      () => _client.put(_uri('/chats/$chatId/mode'), headers: _headers, body: jsonEncode({'mode': mode})),
    );
    return TeachingModeInfo.fromJson(json as Map<String, dynamic>);
  }

  Future<ReasoningModeInfo> getChatReasoningMode(String chatId) async {
    final json = await _send(() => _client.get(_uri('/chats/$chatId/reasoning-mode'), headers: _headers));
    return ReasoningModeInfo.fromJson(json as Map<String, dynamic>);
  }

  Future<ReasoningModeInfo> setChatReasoningMode(String chatId, String reasoningMode) async {
    final json = await _send(
      () => _client.put(
        _uri('/chats/$chatId/reasoning-mode'),
        headers: _headers,
        body: jsonEncode({'reasoningMode': reasoningMode}),
      ),
    );
    return ReasoningModeInfo.fromJson(json as Map<String, dynamic>);
  }

  void close() => _client.close();
}
