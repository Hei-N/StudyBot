import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/health.dart';
import '../connection/connection_providers.dart';

const _pollInterval = Duration(seconds: 20);

/// Engine/provider health, refreshed on demand and on a slow timer —
/// "do not aggressively poll the backend" per the design brief. A failed
/// fetch (engine unreachable) surfaces as [AsyncValue.error], which the
/// status indicator renders as "Engine unavailable".
class EngineHealthNotifier extends AsyncNotifier<EngineHealth> {
  Timer? _timer;

  @override
  Future<EngineHealth> build() async {
    ref.onDispose(() => _timer?.cancel());
    _timer = Timer.periodic(_pollInterval, (_) => refresh());
    return _fetch();
  }

  Future<EngineHealth> _fetch() => ref.read(studyBotApiProvider).getHealth();

  Future<void> refresh() async {
    state = await AsyncValue.guard(_fetch);
  }
}

final engineHealthProvider = AsyncNotifierProvider<EngineHealthNotifier, EngineHealth>(EngineHealthNotifier.new);
