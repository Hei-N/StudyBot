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
