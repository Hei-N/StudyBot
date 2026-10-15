import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../../core/backend/backend_launcher.dart';

/// Whether this run starts the engine itself. Off by default (and in tests);
/// `main.dart` turns it on for development runs.
final managedBackendEnabledProvider = Provider<bool>((ref) => false);

final backendLauncherProvider = Provider<BackendLauncher>(
  (ref) => BackendLauncher(
    resolver: BackendResolver(allowDevelopment: !kReleaseMode, appSupportDirectory: getApplicationSupportDirectory),
  ),
);

/// The engine this app started, or null when the app is not managing one.
/// Stopped when the provider is disposed (the app closing).
final managedBackendProvider = FutureProvider<BackendHandle?>((ref) async {
  if (!ref.watch(managedBackendEnabledProvider)) return null;
  final handle = await ref.watch(backendLauncherProvider).start();
  ref.onDispose(() => handle.stop());
  return handle;
});
