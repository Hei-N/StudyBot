/// Stable, machine-readable error codes from API_CONTRACT.md.
///
/// Widgets switch on [ApiException.code] and never parse [ApiException.message],
/// which is for display only.
abstract final class ApiErrorCode {
  static const chatNotFound = 'CHAT_NOT_FOUND';
  static const chatBusy = 'CHAT_BUSY';
  static const courseNotFound = 'COURSE_NOT_FOUND';
  static const memoryNotFound = 'MEMORY_NOT_FOUND';
  static const memoryConflict = 'MEMORY_CONFLICT';
  static const invalidMode = 'INVALID_MODE';
  static const invalidReasoningMode = 'INVALID_REASONING_MODE';
  static const invalidMemoryKind = 'INVALID_MEMORY_KIND';
  static const invalidMemoryStatus = 'INVALID_MEMORY_STATUS';
  static const modelError = 'MODEL_ERROR';
  static const validationError = 'VALIDATION_ERROR';
  static const unauthorized = 'UNAUTHORIZED';
  static const internalError = 'INTERNAL_ERROR';

  /// Client-side only: the engine could not be reached (no HTTP response).
  /// Never sent by the Python API; synthesized locally so the UI handles both
  /// cases with one type.
  static const disconnected = 'DISCONNECTED';
}

/// A structured API error: a `{code, message}` body from the engine, or a
/// locally synthesized [ApiErrorCode.disconnected] when it couldn't be reached.
class ApiException implements Exception {
  const ApiException({required this.code, required this.message, this.statusCode});

  factory ApiException.fromJson(Map<String, dynamic> json, {int? statusCode}) {
    return ApiException(
      code: json['code'] as String? ?? ApiErrorCode.internalError,
      message: json['message'] as String? ?? 'Something went wrong.',
      statusCode: statusCode,
    );
  }

  factory ApiException.disconnected([String? detail]) {
    return ApiException(
      code: ApiErrorCode.disconnected,
      message: detail ?? 'Could not reach the Study Bot engine.',
    );
  }

  final String code;
  final String message;
  final int? statusCode;

  @override
  String toString() => 'ApiException($code: $message)';
}
