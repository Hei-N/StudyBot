import 'package:flutter/material.dart';

/// Builds the app's [TextTheme] for a given text color pair. Deliberately
/// uses Flutter's default platform font (no bundled/network font) — sized,
/// weighted, and tracked for a clean, restrained hierarchy rather than
/// relying on a decorative typeface.
TextTheme buildAppTextTheme({required Color primary, required Color secondary}) {
  TextStyle style({
    required double size,
    required FontWeight weight,
    double? letterSpacing,
    double? height,
    Color? color,
  }) {
    return TextStyle(
      fontSize: size,
      fontWeight: weight,
      letterSpacing: letterSpacing,
      height: height,
      color: color ?? primary,
    );
  }

  return TextTheme(
    displaySmall: style(size: 28, weight: FontWeight.w700, letterSpacing: -0.4, height: 1.2),
    headlineSmall: style(size: 22, weight: FontWeight.w700, letterSpacing: -0.3, height: 1.25),
    titleLarge: style(size: 18, weight: FontWeight.w600, letterSpacing: -0.2, height: 1.3),
    titleMedium: style(size: 15, weight: FontWeight.w600, letterSpacing: -0.1, height: 1.35),
    titleSmall: style(size: 13, weight: FontWeight.w600, letterSpacing: 0, height: 1.35, color: secondary),
    bodyLarge: style(size: 15, weight: FontWeight.w400, height: 1.5),
    bodyMedium: style(size: 14, weight: FontWeight.w400, height: 1.5),
    bodySmall: style(size: 12.5, weight: FontWeight.w400, height: 1.4, color: secondary),
    labelLarge: style(size: 14, weight: FontWeight.w600, letterSpacing: 0.1),
    labelMedium: style(size: 12, weight: FontWeight.w600, letterSpacing: 0.2, color: secondary),
    labelSmall: style(size: 11, weight: FontWeight.w600, letterSpacing: 0.3, color: secondary),
  );
}
