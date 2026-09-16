import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/theme/app_spacing.dart';
import '../status/status_providers.dart';
import 'connection_providers.dart';

/// The "not connected yet" screen: enter the engine's base URL and bearer
/// token (printed to stdout when the Python API starts, per
/// API_CONTRACT.md), then attempt a connection. Shown whenever no token is
/// configured, or the engine could not be reached.
class ConnectionSetupView extends ConsumerStatefulWidget {
  const ConnectionSetupView({super.key});

  @override
  ConsumerState<ConnectionSetupView> createState() => _ConnectionSetupViewState();
}

class _ConnectionSetupViewState extends ConsumerState<ConnectionSetupView> {
  late final TextEditingController _urlController;
  late final TextEditingController _tokenController;
  bool _connecting = false;
  ApiException? _error;

  @override
  void initState() {
    super.initState();
    final config = ref.read(connectionConfigProvider);
    _urlController = TextEditingController(text: config.baseUrl);
    _tokenController = TextEditingController(text: config.token);
  }

  @override
  void dispose() {
    _urlController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    final url = _urlController.text.trim();
    final token = _tokenController.text.trim();
    if (url.isEmpty || token.isEmpty) {
      setState(() => _error = const ApiException(code: 'VALIDATION_ERROR', message: 'Enter both a URL and a token.'));
      return;
    }

    setState(() {
      _connecting = true;
      _error = null;
    });

    await ref.read(connectionConfigProvider.notifier).update(baseUrl: url, token: token);
    await ref.read(engineHealthProvider.notifier).refresh();

    if (!mounted) return;
    final health = ref.read(engineHealthProvider);
    setState(() {
      _connecting = false;
      _error = health.hasError ? _asApiException(health.error) : null;
    });
  }

  ApiException _asApiException(Object? error) {
    if (error is ApiException) return error;
    return ApiException.disconnected();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.xl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Icon(Icons.hub_outlined, size: 36, color: theme.colorScheme.primary),
                const SizedBox(height: AppSpacing.md),
                Text('Connect to Study Bot', style: theme.textTheme.headlineSmall, textAlign: TextAlign.center),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  'Start the Study Bot engine, then enter its address and token '
                  'below. Both are printed to the terminal when it starts.',
                  style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: AppSpacing.lg),
                TextField(
                  controller: _urlController,
                  decoration: const InputDecoration(labelText: 'Base URL', hintText: 'http://127.0.0.1:8765'),
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                ),
                const SizedBox(height: AppSpacing.sm),
                TextField(
                  controller: _tokenController,
                  decoration: const InputDecoration(labelText: 'Access token'),
                  obscureText: true,
                  autocorrect: false,
                ),
                if (_error != null) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    _error!.message,
                    style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error),
                    textAlign: TextAlign.center,
                  ),
                ],
                const SizedBox(height: AppSpacing.lg),
                FilledButton(
                  onPressed: _connecting ? null : _connect,
                  child: _connecting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Connect'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
