import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/reasoning_mode.dart';
import '../connection/connection_providers.dart';

/// The backend's reasoning-mode catalog (Fast/Deep Think) — fetched once
/// per connection and cached, exactly like [modeCatalogProvider]. The UI
/// never invents mode names or descriptions; everything shown comes from
/// this list.
final reasoningModeCatalogProvider = FutureProvider<List<ReasoningModeInfo>>((ref) {
  return ref.read(studyBotApiProvider).listReasoningModes();
});
