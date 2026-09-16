import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/widgets/section_header.dart';
import '../connection/connection_providers.dart';
import '../status/status_providers.dart';
import 'theme_providers.dart';

/// Theme choice, connection info, live provider/model status, and app
/// info. No model management or account settings — none of that exists in
/// the backend yet.
class SettingsView extends ConsumerWidget {
  const SettingsView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themeMode = ref.watch(themeModeProvider);
    final config = ref.watch(connectionConfigProvider);
    final healthAsync = ref.watch(engineHealthProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.md),
        children: [
          const SectionHeader('Appearance'),
          SegmentedButton<ThemeMode>(
            segments: const [
              ButtonSegment(value: ThemeMode.system, label: Text('System'), icon: Icon(Icons.brightness_auto)),
              ButtonSegment(value: ThemeMode.light, label: Text('Light'), icon: Icon(Icons.light_mode)),
              ButtonSegment(value: ThemeMode.dark, label: Text('Dark'), icon: Icon(Icons.dark_mode)),
            ],
            selected: {themeMode},
            onSelectionChanged: (selection) => ref.read(themeModeProvider.notifier).setThemeMode(selection.first),
          ),
          const SizedBox(height: AppSpacing.lg),
          const SectionHeader('Connection'),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Base URL'),
            subtitle: Text(config.baseUrl),
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Status'),
            subtitle: healthAsync.when(
              data: (health) => Text(
                health.isHealthy
                    ? 'Connected — ${health.provider} · ${health.model}'
                    : 'Engine reachable, but not healthy',
              ),
              loading: () => const Text('Checking…'),
              error: (_, _) => const Text('Engine unavailable'),
            ),
            trailing: IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: () => ref.read(engineHealthProvider.notifier).refresh(),
            ),
          ),
          TextButton(onPressed: () => _editConnection(context, ref), child: const Text('Edit connection…')),
          const SizedBox(height: AppSpacing.lg),
          const SectionHeader('About'),
          const ListTile(contentPadding: EdgeInsets.zero, title: Text('Study Bot'), subtitle: Text('Stage 5.6')),
        ],
      ),
    );
  }

  Future<void> _editConnection(BuildContext context, WidgetRef ref) async {
    final config = ref.read(connectionConfigProvider);
    final urlController = TextEditingController(text: config.baseUrl);
    final tokenController = TextEditingController(text: config.token);
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Edit connection'),
        content: SizedBox(
          width: 360,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: urlController, decoration: const InputDecoration(labelText: 'Base URL')),
              const SizedBox(height: AppSpacing.sm),
              TextField(
                controller: tokenController,
                decoration: const InputDecoration(labelText: 'Access token'),
                obscureText: true,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.of(context).pop(true), child: const Text('Save')),
        ],
      ),
    );
    if (result == true) {
      await ref
          .read(connectionConfigProvider.notifier)
          .update(baseUrl: urlController.text.trim(), token: tokenController.text.trim());
      await ref.read(engineHealthProvider.notifier).refresh();
    }
  }
}
