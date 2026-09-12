/// Build-time configuration.
///
/// Everything here is supplied with `--dart-define` so that the same source
/// tree builds for local dev, staging and bg.netdev.be without a code edit.
///
///   flutter run -d chrome \
///     --dart-define=BG_API_BASE=http://localhost:8000
///
/// In production the app is served by Firebase Hosting, which rewrites
/// `/api/**` and `/mcp/**` to Cloud Run in europe-west1. Same origin, so the
/// base is the empty string and every request is a relative path.
library;

class BgConfig {
  const BgConfig._();

  /// Base URL for the BAROGROOVE backend.
  ///
  /// Empty string means "same origin", which is what we want on Firebase
  /// Hosting. The localhost default is for `flutter run`.
  static const String apiBase = String.fromEnvironment(
    'BG_API_BASE',
    defaultValue: '',
  );

  /// Set to `true` in a production build to make the app refuse to fall back
  /// to the demo forge when the user is unauthenticated.
  static const bool strictAuth = bool.fromEnvironment('BG_STRICT_AUTH');

  /// Network timeout for a single API call, before retry.
  static const Duration requestTimeout = Duration(seconds: 12);

  /// Total attempts (1 initial + 2 retries) for idempotent GETs.
  static const int maxAttempts = 3;

  /// Builds an absolute [Uri] for a backend path such as `/api/health`.
  ///
  /// Handles the same-origin case by deferring to [Uri.base], which on web is
  /// the document URL and on mobile is a file URI — hence the guard: on
  /// mobile an empty [apiBase] is a misconfiguration, not "same origin".
  static Uri resolve(String path, [Map<String, String>? query]) {
    assert(path.startsWith('/'), 'API paths must be rooted: got "$path"');
    final Uri base;
    if (apiBase.isEmpty) {
      base = Uri.base.replace(path: path, queryParameters: query);
    } else {
      base = Uri.parse('$apiBase$path').replace(queryParameters: query);
    }
    return base;
  }
}
