/// The retry policy every test [ProviderContainer]/[ProviderScope] should use:
/// no automatic retry. Pass as `retry: kNoRetry`.
///
/// Riverpod 3's default `build()` retry (exponential backoff, real `Timer`s)
/// makes a test that triggers an initial-build failure under plain `test()`
/// hang for real seconds. Production disables the same retry in `main.dart`,
/// since the app's explicit "Retry" buttons are the intended UX.
///
/// This is a plain top-level function because the `Retry` typedef is not part
/// of Riverpod's public API; Dart's structural function typing matches it
/// against the `retry:` parameter.
Duration? kNoRetry(int retryCount, Object error) => null;
