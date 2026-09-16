import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:studybot_app/features/settings/theme_providers.dart';

import '../../support/no_retry_container.dart';

void main() {
  test('defaults to ThemeMode.system', () {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer(retry: kNoRetry);
    addTearDown(container.dispose);

    expect(container.read(themeModeProvider), ThemeMode.system);
  });

  test('setThemeMode updates state and persists it', () async {
    SharedPreferences.setMockInitialValues({});
    final container = ProviderContainer(retry: kNoRetry);
    addTearDown(container.dispose);

    await container.read(themeModeProvider.notifier).setThemeMode(ThemeMode.dark);
    expect(container.read(themeModeProvider), ThemeMode.dark);

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('studybot.settings.themeMode'), 'dark');
  });

  test('restores a previously persisted theme mode on startup', () async {
    SharedPreferences.setMockInitialValues({'studybot.settings.themeMode': 'light'});
    final container = ProviderContainer(retry: kNoRetry);
    addTearDown(container.dispose);

    // Reading the provider is what kicks off build() (and its background
    // _restore() call) in the first place — only then is there anything
    // for pumpEventQueue() to wait out.
    container.read(themeModeProvider);
    await pumpEventQueue();
    expect(container.read(themeModeProvider), ThemeMode.light);
  });
}
