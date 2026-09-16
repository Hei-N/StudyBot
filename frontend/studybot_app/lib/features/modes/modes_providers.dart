import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/teaching_mode.dart';
import '../connection/connection_providers.dart';

/// The backend's teaching-mode catalog (id/name/description) — fetched
/// once per connection and cached. The UI never invents mode names or
/// descriptions; everything shown comes from this list.
final modeCatalogProvider = FutureProvider<List<TeachingModeInfo>>((ref) {
  return ref.read(studyBotApiProvider).listModes();
});
