/// Width breakpoints driving the adaptive shell layout (see
/// `features/shell/app_shell.dart`). Four tiers:
///
/// - [large]  and up: navigation + chats + conversation + study panel
/// - [medium] to [large]: navigation + chats + conversation (panel hidden)
/// - [compact] to [medium]: collapsible navigation + conversation
/// - below [compact]: conversation-first, courses/chats via a sheet
abstract final class AppBreakpoints {
  static const compact = 600.0;
  static const medium = 900.0;
  static const large = 1200.0;

  static bool isPhoneWidth(double width) => width < compact;
  static bool isCompact(double width) => width < medium;
  static bool isMedium(double width) => width >= medium && width < large;
  static bool isLarge(double width) => width >= large;
}
