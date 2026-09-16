import 'package:studybot_app/core/models/health.dart';
import 'package:studybot_app/features/status/status_providers.dart';

const _healthyDefault = EngineHealth(
  apiVersion: '1',
  status: 'ok',
  provider: 'ollama',
  model: 'qwen3:4b',
  providerReachable: true,
  modelAvailable: true,
);

/// A drop-in replacement for [EngineHealthNotifier] that never starts the
/// real 20-second polling [Timer] — that timer outliving a widget test's
/// [ProviderContainer] trips Flutter test's "pending timer" invariant
/// check, which runs before `addTearDown` callbacks get a chance to
/// dispose the container. Tests that don't care about polling behavior
/// itself should override with this instead.
class StaticEngineHealthNotifier extends EngineHealthNotifier {
  StaticEngineHealthNotifier({this.health = _healthyDefault, this.error});

  final EngineHealth health;
  final Object? error;

  @override
  Future<EngineHealth> build() async {
    final err = error;
    if (err != null) throw err;
    return health;
  }
}
