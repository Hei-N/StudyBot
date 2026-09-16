import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:studybot_app/core/api/api_exception.dart';
import 'package:studybot_app/core/api/connection_config.dart';
import 'package:studybot_app/core/api/studybot_api.dart';

const _config = ConnectionConfig(baseUrl: 'http://127.0.0.1:8765', token: 'test-token');

StudyBotApi _apiWith(http.Client client) => StudyBotApi(_config, client: client);

void main() {
  test('attaches the bearer token and hits the versioned path', () async {
    late http.Request captured;
    final api = _apiWith(
      MockClient((request) async {
        captured = request;
        return http.Response(jsonEncode([]), 200);
      }),
    );

    await api.listCourses();

    expect(captured.url.path, '/api/v1/courses');
    expect(captured.headers['Authorization'], 'Bearer test-token');
  });

  test('parses a successful courses list', () async {
    final api = _apiWith(
      MockClient((request) async {
        return http.Response(
          jsonEncode([
            {
              'id': 'c1',
              'name': 'Physics I',
              'code': null,
              'term': null,
              'description': null,
              'createdAt': '2026-01-01T00:00:00Z',
              'updatedAt': '2026-01-01T00:00:00Z',
            },
          ]),
          200,
        );
      }),
    );

    final courses = await api.listCourses();
    expect(courses, hasLength(1));
    expect(courses.single.name, 'Physics I');
  });

  test('a structured {code,message} error body becomes an ApiException', () async {
    final api = _apiWith(
      MockClient((request) async {
        return http.Response(jsonEncode({'code': 'COURSE_NOT_FOUND', 'message': 'No such course.'}), 404);
      }),
    );

    await expectLater(
      api.listCourses(),
      throwsA(
        isA<ApiException>()
            .having((e) => e.code, 'code', ApiErrorCode.courseNotFound)
            .having((e) => e.message, 'message', 'No such course.'),
      ),
    );
  });

  test('a network failure becomes ApiErrorCode.disconnected', () async {
    final api = _apiWith(MockClient((request) async => throw const SocketException('connection refused')));

    await expectLater(
      api.listCourses(),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', ApiErrorCode.disconnected)),
    );
  });

  test('listChats omits the query parameter when courseId is null', () async {
    late http.Request captured;
    final api = _apiWith(
      MockClient((request) async {
        captured = request;
        return http.Response(jsonEncode([]), 200);
      }),
    );

    await api.listChats();
    expect(captured.url.queryParameters.containsKey('course_id'), isFalse);

    await api.listChats(courseId: 'none');
    expect(captured.url.queryParameters['course_id'], 'none');
  });

  test('createChat sends camelCase courseId in the body', () async {
    late String body;
    final api = _apiWith(
      MockClient((request) async {
        body = request.body;
        return http.Response(
          jsonEncode({
            'id': 'chat1',
            'title': null,
            'courseId': 'c1',
            'teachingMode': 'teach',
            'createdAt': '2026-01-01T00:00:00Z',
            'updatedAt': '2026-01-01T00:00:00Z',
          }),
          200,
        );
      }),
    );

    await api.createChat(courseId: 'c1');
    expect(jsonDecode(body), {'courseId': 'c1'});
  });
}
