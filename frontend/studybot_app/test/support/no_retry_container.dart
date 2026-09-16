/// The retry policy every test [ProviderContainer]/[ProviderScope] should
/// use: no automatic retry. Pass as `retry: kNoRetry`.
///
/// Riverpod 3's default `build()` retry (exponential backoff, up to ~10
/// attempts, real `Timer`s) means a test that triggers an initial-build
/// failure under plain `test()` (not `testWidgets()`, so no fake clock)
/// hangs for real wall-clock seconds — found via a genuine test hang while
/// verifying this stage's error handling. Production disables the same
/// retry in `main.dart` for the matching reason: this app's explicit
/// "Retry" buttons are the intended UX, not silent background retries.
///
/// This is a plain top-level function rather than a typed `Retry` value —
/// that typedef (like `Override`, the type of an `overrides` list entry)
/// isn't part of riverpod's public API surface, so it can't be named
/// directly here; Dart's structural function typing matches this against
/// the `retry:` parameter without needing the typedef's name.
Duration? kNoRetry(int retryCount, Object error) => null;
