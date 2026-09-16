/// Engine/provider status, as returned by `GET /api/v1/health`.
///
/// Mirrors `HealthOut` in API_CONTRACT.md.
class EngineHealth {
  const EngineHealth({
    required this.apiVersion,
    required this.status,
    required this.provider,
    required this.model,
    required this.providerReachable,
    required this.modelAvailable,
  });

  factory EngineHealth.fromJson(Map<String, dynamic> json) {
    return EngineHealth(
      apiVersion: json['apiVersion'] as String,
      status: json['status'] as String,
      provider: json['provider'] as String,
      model: json['model'] as String,
      providerReachable: json['providerReachable'] as bool?,
      modelAvailable: json['modelAvailable'] as bool?,
    );
  }

  final String apiVersion;
  final String status;
  final String provider;
  final String model;
  final bool? providerReachable;
  final bool? modelAvailable;

  bool get isHealthy => status == 'ok' && providerReachable != false;
}
