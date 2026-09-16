import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';

/// The small "● Local · qwen3:4b" / "○ Engine unavailable" indicator.
/// Purely presentational — callers decide the label and whether the dot is
/// filled (healthy) or hollow (unavailable/unknown).
class StatusDot extends StatelessWidget {
  const StatusDot({super.key, required this.label, required this.healthy});

  final String label;
  final bool healthy;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = healthy ? AppColors.success : theme.colorScheme.onSurface.withValues(alpha: 0.4);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(healthy ? Icons.circle : Icons.circle_outlined, size: 8, color: color),
        const SizedBox(width: AppSpacing.xs),
        Flexible(
          child: Text(
            label,
            style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }
}
