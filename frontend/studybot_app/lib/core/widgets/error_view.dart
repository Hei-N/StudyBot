import 'package:flutter/material.dart';

import '../api/api_exception.dart';
import '../theme/app_spacing.dart';

/// Renders an [ApiException] as a human message — never a raw exception or
/// stack trace. Error codes without a specific mapping fall back to the
/// exception's own `message` (already human-readable, per API_CONTRACT.md).
class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.error, this.onRetry});

  final ApiException error;
  final VoidCallback? onRetry;

  String get _friendlyMessage {
    switch (error.code) {
      case ApiErrorCode.disconnected:
        return 'Could not reach the Study Bot engine. Check that it is running and reachable.';
      case ApiErrorCode.unauthorized:
        return 'The connection token was rejected. Check it in Settings.';
      case ApiErrorCode.modelError:
        return 'The model could not produce a response. You can try again.';
      default:
        return error.message;
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 36, color: theme.colorScheme.error),
            const SizedBox(height: AppSpacing.md),
            Text(_friendlyMessage, style: theme.textTheme.bodyMedium, textAlign: TextAlign.center),
            if (onRetry != null) ...[
              const SizedBox(height: AppSpacing.md),
              OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
            ],
          ],
        ),
      ),
    );
  }
}
