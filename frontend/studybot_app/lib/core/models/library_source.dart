/// A study-library source as returned by `GET /api/v1/library/sources`.
///
/// [locator] is private local data used only to match a re-selected folder; it
/// is never shown prominently or logged. Authorization bytes are not part of
/// this model.
class LibrarySource {
  const LibrarySource({
    required this.id,
    required this.courseId,
    required this.kind,
    required this.displayName,
    required this.locator,
    required this.hasAuthorization,
  });

  factory LibrarySource.fromJson(Map<String, dynamic> json) {
    return LibrarySource(
      id: json['id'] as String,
      courseId: json['courseId'] as String?,
      kind: json['kind'] as String,
      displayName: json['displayName'] as String,
      locator: json['locator'] as String,
      hasAuthorization: json['hasAuthorization'] as bool,
    );
  }

  final String id;
  final String? courseId;
  final String kind;
  final String displayName;
  final String locator;
  final bool hasAuthorization;
}

/// The opaque access grant stored for a source (Base64 of a security-scoped bookmark on macOS).
class LibraryAuthorization {
  const LibraryAuthorization({
    required this.sourceId,
    required this.platform,
    required this.kind,
    required this.payload,
  });

  factory LibraryAuthorization.fromJson(Map<String, dynamic> json) {
    return LibraryAuthorization(
      sourceId: json['sourceId'] as String,
      platform: json['platform'] as String,
      kind: json['kind'] as String,
      payload: json['payload'] as String,
    );
  }

  final String sourceId;
  final String platform;
  final String kind;
  final String payload;
}

/// A file recorded under a source: metadata and processing state only (never text or paths).
class LibraryFile {
  const LibraryFile({
    required this.id,
    required this.sourceId,
    required this.relativePath,
    required this.displayName,
    required this.processingState,
    required this.failureCode,
    required this.pageCount,
    required this.textPageCount,
  });

  factory LibraryFile.fromJson(Map<String, dynamic> json) {
    return LibraryFile(
      id: json['id'] as String,
      sourceId: json['sourceId'] as String,
      relativePath: json['relativePath'] as String,
      displayName: json['displayName'] as String,
      processingState: json['processingState'] as String,
      failureCode: json['failureCode'] as String?,
      pageCount: json['pageCount'] as int?,
      textPageCount: json['textPageCount'] as int?,
    );
  }

  final String id;
  final String sourceId;
  final String relativePath;
  final String displayName;
  final String processingState;
  final String? failureCode;
  final int? pageCount;
  final int? textPageCount;
}

/// The outcome of one PDF import request.
class PdfImportResult {
  const PdfImportResult({required this.outcome, required this.file});

  factory PdfImportResult.fromJson(Map<String, dynamic> json) {
    return PdfImportResult(
      outcome: json['outcome'] as String,
      file: LibraryFile.fromJson(json['file'] as Map<String, dynamic>),
    );
  }

  /// `imported`, `unchanged` or `failed`.
  final String outcome;
  final LibraryFile file;
}

/// The outcome of one direct upload: `uploaded`, `duplicate` or `failed`.
class UploadPdfResult {
  const UploadPdfResult({required this.outcome, required this.file, required this.failureCode});

  factory UploadPdfResult.fromJson(Map<String, dynamic> json) {
    final file = json['file'] as Map<String, dynamic>?;
    return UploadPdfResult(
      outcome: json['outcome'] as String,
      file: file == null ? null : LibraryFile.fromJson(file),
      failureCode: json['failureCode'] as String?,
    );
  }

  final String outcome;
  final LibraryFile? file;
  final String? failureCode;
}
