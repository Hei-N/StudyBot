import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/api/api_exception.dart';

void main() {
  group('ApiException.fromJson', () {
    test('reads code and message from a structured error body', () {
      final error = ApiException.fromJson({'code': 'CHAT_NOT_FOUND', 'message': 'No such chat.'}, statusCode: 404);
      expect(error.code, ApiErrorCode.chatNotFound);
      expect(error.message, 'No such chat.');
      expect(error.statusCode, 404);
    });

    test('falls back to INTERNAL_ERROR and a generic message when fields are missing', () {
      final error = ApiException.fromJson(<String, dynamic>{});
      expect(error.code, ApiErrorCode.internalError);
      expect(error.message, isNotEmpty);
    });
  });

  test('ApiException.disconnected uses the client-only DISCONNECTED code', () {
    final error = ApiException.disconnected('no route to host');
    expect(error.code, ApiErrorCode.disconnected);
    expect(error.message, 'no route to host');
  });

  test('ApiException.disconnected has a default message when none is given', () {
    expect(ApiException.disconnected().message, isNotEmpty);
  });
}
