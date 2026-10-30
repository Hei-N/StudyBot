import 'dart:async';

import 'package:flutter/services.dart';

/// One file from a drop, already copied by the native layer into StudyBot's private staging
/// area. [error] is set (and [stagingId] null) when the file was rejected.
class DroppedPdf {
  const DroppedPdf({required this.displayName, required this.sizeBytes, this.stagingId, this.error});

  final String displayName;
  final int sizeBytes;
  final String? stagingId;

  /// `not_pdf`, `too_large`, `too_many` or `staging_failed`.
  final String? error;
}

sealed class DropEvent {
  const DropEvent();
}

/// A drag entered the window. [valid] is false when it holds nothing StudyBot can attach.
class DragEntered extends DropEvent {
  const DragEntered({required this.valid, required this.count});

  final bool valid;
  final int count;
}

class DragExited extends DropEvent {
  const DragExited();
}

class Dropped extends DropEvent {
  const Dropped(this.items);

  final List<DroppedPdf> items;
}

/// Receives files dropped on the window. The native side only accepts drags while a chat
/// composer has asked for them, and stages dropped files exactly like the file picker does.
abstract class FileDropService {
  Stream<DropEvent> get events;

  /// Starts or stops accepting drops. Files are staged in [stagingDirectory].
  Future<void> setAccepting(bool accepting, {String? stagingDirectory});
}

/// macOS implementation over the `studybot/file_drop` channel.
class MacOSFileDropService implements FileDropService {
  MacOSFileDropService({MethodChannel? channel}) : _channel = channel ?? const MethodChannel('studybot/file_drop') {
    _channel.setMethodCallHandler(_handle);
  }

  final MethodChannel _channel;
  final _events = StreamController<DropEvent>.broadcast();

  @override
  Stream<DropEvent> get events => _events.stream;

  Future<dynamic> _handle(MethodCall call) async {
    final arguments = call.arguments as Map<Object?, Object?>? ?? const {};
    switch (call.method) {
      case 'dragEntered':
        _events.add(DragEntered(valid: arguments['valid'] as bool? ?? false, count: arguments['count'] as int? ?? 0));
      case 'dragExited':
        _events.add(const DragExited());
      case 'dropped':
        final items = (arguments['items'] as List<Object?>? ?? const []).cast<Map<Object?, Object?>>();
        _events.add(
          Dropped([
            for (final item in items)
              DroppedPdf(
                displayName: item['displayName'] as String? ?? '',
                sizeBytes: item['sizeBytes'] as int? ?? 0,
                stagingId: item['stagingId'] as String?,
                error: item['error'] as String?,
              ),
          ]),
        );
    }
  }

  @override
  Future<void> setAccepting(bool accepting, {String? stagingDirectory}) async {
    try {
      await _channel.invokeMethod<void>('setAccepting', {'accepting': accepting, 'stagingDirectory': stagingDirectory});
    } on PlatformException {
      // Dropping is a convenience; the + button always works.
    } on MissingPluginException {
      // Not running inside the macOS app (tests, other platforms).
    }
  }
}
