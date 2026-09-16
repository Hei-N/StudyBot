import 'package:flutter/material.dart';

/// Centralized color tokens — dark-first, blue/blue-violet accent,
/// restrained surfaces. Nothing in `features/` should reach for a raw
/// `Color(0x...)`; everything comes from here or from [ColorScheme] derived
/// from it in `app_theme.dart`.
abstract final class AppColors {
  // Brand accent — a blue leaning slightly violet, used for the primary
  // accent across both themes (adjusted for contrast per-brightness below).
  static const accent = Color(0xFF5B6EF5);
  static const accentDark = Color(0xFF7C8CFF); // accent tuned for dark backgrounds
  static const accentSoft = Color(0xFF3D4B8F); // muted accent for subtle fills

  // Semantic status colors (used sparingly: connection dot, destructive actions).
  static const success = Color(0xFF3DD68C);
  static const danger = Color(0xFFEF5B6B);
  static const warning = Color(0xFFF5A623);

  // --- dark theme surfaces ---------------------------------------------------
  static const darkBackground = Color(0xFF0E0F13);
  static const darkSurface = Color(0xFF16181F);
  static const darkSurfaceRaised = Color(0xFF1C1F28);
  static const darkBorder = Color(0xFF2A2E38);
  static const darkBorderSubtle = Color(0xFF20232C);
  static const darkTextPrimary = Color(0xFFF2F3F7);
  static const darkTextSecondary = Color(0xFFA6ABBA);
  static const darkTextTertiary = Color(0xFF6E7383);

  // --- light theme surfaces --------------------------------------------------
  static const lightBackground = Color(0xFFF6F7FB);
  static const lightSurface = Color(0xFFFFFFFF);
  static const lightSurfaceRaised = Color(0xFFFFFFFF);
  static const lightBorder = Color(0xFFE2E4EC);
  static const lightBorderSubtle = Color(0xFFEBEDF3);
  static const lightTextPrimary = Color(0xFF1B1D24);
  static const lightTextSecondary = Color(0xFF5B5F6E);
  static const lightTextTertiary = Color(0xFF8A8EA0);

  // --- message bubbles ---------------------------------------------------------
  static const darkUserBubble = Color(0xFF2B3570);
  static const lightUserBubble = Color(0xFFE8EAFD);
}
