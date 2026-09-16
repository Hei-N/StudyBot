import 'package:flutter/material.dart';

/// Animation durations/curves. Restrained and smooth — motion should
/// clarify state changes (selection, panel open/close, new content), never
/// call attention to itself.
abstract final class AppMotion {
  static const fast = Duration(milliseconds: 120);
  static const normal = Duration(milliseconds: 200);
  static const slow = Duration(milliseconds: 320);

  static const standardCurve = Curves.easeOutCubic;
  static const enterCurve = Curves.easeOut;
  static const exitCurve = Curves.easeIn;
}
