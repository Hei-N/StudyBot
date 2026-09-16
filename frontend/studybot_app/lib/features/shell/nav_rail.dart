import 'package:flutter/material.dart';

import '../../core/theme/app_spacing.dart';
import '../settings/settings_view.dart';

/// The slim, always-present leftmost rail: app mark at the top, Settings at
/// the bottom. Distinct from the Navigation (courses) column beside it —
/// this rail never scrolls or changes with the active course/chat.
class NavRail extends StatelessWidget {
  const NavRail({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: 56,
      decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
      child: Column(
        children: [
          const SizedBox(height: AppSpacing.md),
          Icon(Icons.auto_awesome, color: theme.colorScheme.primary, size: 24),
          const Spacer(),
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsView())),
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
      ),
    );
  }
}
