/// The typed BAROGROOVE API client.
///
/// ## Policy
///
/// Every call has a timeout, retries idempotent GETs with exponential backoff
/// and jitter, and returns an [ApiResult] rather than throwing. Nothing in
/// this app should be able to die because a network was slow.
///
/// "Graceful degradation" here means something specific and slightly
/// unfashionable: we do NOT hide failures. A degraded backend reports what is
/// broken in `degraded[]`, and the UI shows that list verbatim. A caller that
/// swallows a failure and renders a plausible-looking empty state is lying to
/// the user, which for a product whose entire pitch is "it explains itself"
/// would be a strange thing to do.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;

import '../a2ui/messages.dart';
import '../config.dart';
import 'auth_interceptor.dart';
import 'models.dart';

/// Success or a described failure. Never an exception across the boundary.
sealed class ApiResult<T> {
  const ApiResult();

  bool get isOk => this is ApiOk<T>;

  T? get valueOrNull => this is ApiOk<T> ? (this as ApiOk<T>).value : null;

  ApiFailure<T>? get failureOrNull =>
      this is ApiFailure<T> ? this as ApiFailure<T> : null;

  /// Folds into a single value — the usual way screens consume this.
  R when<R>({
    required R Function(T value) ok,
    required R Function(ApiFailure<T> failure) failed,
  }) =>
      switch (this) {
        ApiOk<T>(:final T value) => ok(value),
        ApiFailure<T>() => failed(this as ApiFailure<T>),
      };
}

final class ApiOk<T> extends ApiResult<T> {
  const ApiOk(this.value);
  final T value;
}

final class ApiFailure<T> extends ApiResult<T> {
  const ApiFailure({
    required this.message,
    this.statusCode,
    this.kind = ApiFailureKind.network,
  });

  /// Shown to the user. Written to be read by a human, not grepped.
  final String message;

  final int? statusCode;
  final ApiFailureKind kind;

  bool get isAuth => kind == ApiFailureKind.unauthorized;

  ApiFailure<R> cast<R>() => ApiFailure<R>(
        message: message,
        statusCode: statusCode,
        kind: kind,
      );
}

enum ApiFailureKind { network, timeout, unauthorized, notFound, server, decode }

/// The client. One instance per app; created in `main` and shared via
/// Riverpod.
class BarogrooveApi {
  BarogrooveApi({http.Client? client})
      : _client = client ?? AuthedClient();

  final http.Client _client;
  final Random _jitter = Random();

  void dispose() => _client.close();

  // =========================================================================
  // Health and metadata
  // =========================================================================

  Future<ApiResult<HealthStatus>> health() =>
      _getJson('/api/health', HealthStatus.fromJson);

  /// The easter egg. `GET /legacy` returns "Hello World!!" — the first thing
  /// this service ever did, kept alive because deleting it felt rude.
  Future<ApiResult<String>> legacy() async {
    final ApiResult<http.Response> res = await _get('/legacy');
    return res.when(
      ok: (http.Response r) => ApiOk<String>(r.body.trim()),
      failed: (ApiFailure<http.Response> f) => f.cast<String>(),
    );
  }

  Future<ApiResult<List<SkyTheme>>> themes() =>
      _getJsonList('/api/themes', SkyTheme.fromJson);

  Future<ApiResult<List<GenreCorridorModel>>> genres() =>
      _getJsonList('/api/genres', GenreCorridorModel.fromJson);

  Future<ApiResult<List<SkyScenario>>> scenarios() =>
      _getJsonList('/api/sky/scenarios', SkyScenario.fromJson);

  Future<ApiResult<SkyVector>> skyVector({
    double? lat,
    double? lon,
    String? scenario,
  }) =>
      _getJson(
        '/api/sky/vector',
        SkyVector.fromJson,
        query: <String, String>{
          if (lat != null) 'lat': '$lat',
          if (lon != null) 'lon': '$lon',
          if (scenario != null) 'scenario': scenario,
        },
      );

  // =========================================================================
  // Forge
  // =========================================================================

  Future<ApiResult<ForgeResult>> forge(ForgeRequest request) => _postJson(
        '/api/forge',
        request.toJson(),
        ForgeResult.fromJson,
        // A forge does real work upstream; give it room.
        timeout: const Duration(seconds: 45),
      );

  /// Zero-credential demo. What an unauthenticated visitor gets.
  Future<ApiResult<ForgeResult>> demoForge() => _getJson(
        '/api/forge/demo',
        ForgeResult.fromJson,
        timeout: const Duration(seconds: 30),
      );

  // =========================================================================
  // A2UI surfaces — the important ones
  // =========================================================================

  /// The catalog the server declares. We fetch it to *verify* our renderer
  /// can handle every type the server may send, and to report the mismatch
  /// honestly if not. We never derive layout from it — layout arrives in the
  /// message stream.
  Future<ApiResult<JsonMap>> surfaceCatalog() =>
      _getJson('/api/surfaces/catalog', (JsonMap j) => j);

  /// `GET /api/surfaces/sky` -> a list of A2UI envelopes.
  Future<ApiResult<List<A2uiMessage>>> skySurface({
    double? lat,
    double? lon,
  }) =>
      _getMessages(
        '/api/surfaces/sky',
        query: <String, String>{
          if (lat != null) 'lat': '$lat',
          if (lon != null) 'lon': '$lon',
        },
      );

  /// `GET /api/surfaces/themes` -> a list of A2UI envelopes.
  Future<ApiResult<List<A2uiMessage>>> themesSurface() =>
      _getMessages('/api/surfaces/themes');

  Future<ApiResult<List<A2uiMessage>>> _getMessages(
    String path, {
    Map<String, String>? query,
  }) async {
    final ApiResult<http.Response> res = await _get(path, query: query);
    return res.when(
      ok: (http.Response r) => ApiOk<List<A2uiMessage>>(
        // Parsing is total, so a malformed envelope becomes an
        // UnknownA2uiMessage that the renderer displays. That is strictly
        // more useful than a decode failure here.
        A2uiMessage.parseJson(r.body),
      ),
      failed: (ApiFailure<http.Response> f) => f.cast<List<A2uiMessage>>(),
    );
  }

  // =========================================================================
  // Pairing
  // =========================================================================

  Future<ApiResult<PairingStatus>> pairStatus() =>
      _getJson('/api/pair/status', PairingStatus.fromJson);

  Future<ApiResult<PairingStart>> startSpotifyPairing({
    String? codeChallenge,
    String? redirectUri,
  }) =>
      _postJson(
        '/api/pair/spotify/start',
        <String, Object?>{
          if (codeChallenge != null) 'code_challenge': codeChallenge,
          if (codeChallenge != null) 'code_challenge_method': 'S256',
          if (redirectUri != null) 'redirect_uri': redirectUri,
        },
        PairingStart.fromJson,
      );

  Future<ApiResult<PairingStart>> startLastfmPairing({String? redirectUri}) =>
      _postJson(
        '/api/pair/lastfm/start',
        <String, Object?>{
          if (redirectUri != null) 'redirect_uri': redirectUri,
        },
        PairingStart.fromJson,
      );

  Future<ApiResult<PairingStatus>> disconnect(String provider) => _postJson(
        '/api/pair/$provider/disconnect',
        const <String, Object?>{},
        PairingStatus.fromJson,
      );

  // =========================================================================
  // Almanac
  // =========================================================================

  Future<ApiResult<List<AlmanacEntry>>> almanacHistory() =>
      _getJsonList('/api/almanac/history', AlmanacEntry.fromJson);

  Future<ApiResult<Retrospective>> retrospective() async {
    final ApiResult<http.Response> res = await _get('/api/almanac/retrospective');
    return res.when(
      ok: (http.Response r) {
        try {
          return ApiOk<Retrospective>(
            Retrospective.fromJson(jsonDecode(r.body)),
          );
        } on FormatException catch (e) {
          return ApiFailure<Retrospective>(
            message: 'The retrospective came back unreadable: ${e.message}',
            kind: ApiFailureKind.decode,
          );
        }
      },
      failed: (ApiFailure<http.Response> f) => f.cast<Retrospective>(),
    );
  }

  Future<ApiResult<void>> sendFeedback(FeedbackSignal signal) async {
    final ApiResult<http.Response> res = await _post(
      '/api/almanac/feedback',
      signal.toJson(),
    );
    return res.when(
      ok: (_) => const ApiOk<void>(null),
      failed: (ApiFailure<http.Response> f) => f.cast<void>(),
    );
  }

  // =========================================================================
  // Transport
  // =========================================================================

  Future<ApiResult<T>> _getJson<T>(
    String path,
    T Function(JsonMap json) decode, {
    Map<String, String>? query,
    Duration? timeout,
  }) async {
    final ApiResult<http.Response> res =
        await _get(path, query: query, timeout: timeout);
    return res.when(
      ok: (http.Response r) => _decodeObject(r.body, decode, path),
      failed: (ApiFailure<http.Response> f) => f.cast<T>(),
    );
  }

  Future<ApiResult<List<T>>> _getJsonList<T>(
    String path,
    T Function(JsonMap json) decode, {
    Map<String, String>? query,
  }) async {
    final ApiResult<http.Response> res = await _get(path, query: query);
    return res.when(
      ok: (http.Response r) {
        try {
          final Object? parsed = jsonDecode(r.body);
          // Accept a bare array or `{"items": [...]}`.
          final List<Object?>? items = asJsonList(parsed) ??
              asJsonList(asJsonMap(parsed)?['items']) ??
              asJsonList(asJsonMap(parsed)?['results']);
          if (items == null) {
            return ApiFailure<List<T>>(
              message: '$path returned an object where a list was expected.',
              kind: ApiFailureKind.decode,
            );
          }
          return ApiOk<List<T>>(<T>[
            for (final Object? i in items)
              if (asJsonMap(i) case final JsonMap m) decode(m),
          ]);
        } on FormatException catch (e) {
          return ApiFailure<List<T>>(
            message: '$path returned malformed JSON: ${e.message}',
            kind: ApiFailureKind.decode,
          );
        }
      },
      failed: (ApiFailure<http.Response> f) => f.cast<List<T>>(),
    );
  }

  Future<ApiResult<T>> _postJson<T>(
    String path,
    JsonMap body,
    T Function(JsonMap json) decode, {
    Duration? timeout,
  }) async {
    final ApiResult<http.Response> res =
        await _post(path, body, timeout: timeout);
    return res.when(
      ok: (http.Response r) => _decodeObject(r.body, decode, path),
      failed: (ApiFailure<http.Response> f) => f.cast<T>(),
    );
  }

  ApiResult<T> _decodeObject<T>(
    String body,
    T Function(JsonMap json) decode,
    String path,
  ) {
    try {
      final JsonMap? json = asJsonMap(jsonDecode(body));
      if (json == null) {
        return ApiFailure<T>(
          message: '$path returned something other than a JSON object.',
          kind: ApiFailureKind.decode,
        );
      }
      return ApiOk<T>(decode(json));
    } on FormatException catch (e) {
      return ApiFailure<T>(
        message: '$path returned malformed JSON: ${e.message}',
        kind: ApiFailureKind.decode,
      );
    } catch (e) {
      // A model constructor that throws is our bug; report it as such rather
      // than as a network problem, so it gets fixed instead of retried.
      return ApiFailure<T>(
        message: 'Could not read the response from $path: $e',
        kind: ApiFailureKind.decode,
      );
    }
  }

  /// Idempotent GET with retry.
  Future<ApiResult<http.Response>> _get(
    String path, {
    Map<String, String>? query,
    Duration? timeout,
  }) =>
      _send(
        path: path,
        query: query,
        timeout: timeout,
        retryable: true,
        perform: (Uri uri, Map<String, String> headers) =>
            _client.get(uri, headers: headers),
      );

  /// POST. Retried only on a timeout or a 5xx, and only because the BAROGROOVE
  /// POST endpoints are all either idempotent or cheap to repeat. Do not add
  /// a non-idempotent POST here without narrowing this.
  Future<ApiResult<http.Response>> _post(
    String path,
    JsonMap body, {
    Duration? timeout,
  }) =>
      _send(
        path: path,
        timeout: timeout,
        retryable: true,
        perform: (Uri uri, Map<String, String> headers) => _client.post(
          uri,
          headers: headers,
          body: jsonEncode(body),
        ),
      );

  Future<ApiResult<http.Response>> _send({
    required String path,
    required Future<http.Response> Function(Uri, Map<String, String>) perform,
    required bool retryable,
    Map<String, String>? query,
    Duration? timeout,
  }) async {
    final Uri uri = BgConfig.resolve(
      path,
      (query == null || query.isEmpty) ? null : query,
    );
    final Duration limit = timeout ?? BgConfig.requestTimeout;
    final int attempts = retryable ? BgConfig.maxAttempts : 1;

    ApiFailure<http.Response>? last;

    for (var attempt = 1; attempt <= attempts; attempt++) {
      try {
        final http.Response res = await perform(
          uri,
          const <String, String>{
            'accept': 'application/json',
            'content-type': 'application/json',
          },
        ).timeout(limit);

        if (res.statusCode >= 200 && res.statusCode < 300) {
          return ApiOk<http.Response>(res);
        }

        if (res.statusCode == 401 || res.statusCode == 403) {
          return ApiFailure<http.Response>(
            message: 'You need to sign in to do that.',
            statusCode: res.statusCode,
            kind: ApiFailureKind.unauthorized,
          );
        }

        if (res.statusCode == 404) {
          return ApiFailure<http.Response>(
            message: 'The backend has no $path. It may be an older build.',
            statusCode: 404,
            kind: ApiFailureKind.notFound,
          );
        }

        if (res.statusCode < 500) {
          // A 4xx is a considered answer. Retrying will not change it.
          return ApiFailure<http.Response>(
            message: 'The backend rejected $path '
                '(${res.statusCode}). ${_snippet(res.body)}',
            statusCode: res.statusCode,
            kind: ApiFailureKind.server,
          );
        }

        last = ApiFailure<http.Response>(
          message: 'The backend failed on $path (${res.statusCode}).',
          statusCode: res.statusCode,
          kind: ApiFailureKind.server,
        );
      } on TimeoutException {
        last = ApiFailure<http.Response>(
          message: '$path did not answer within ${limit.inSeconds}s.',
          kind: ApiFailureKind.timeout,
        );
      } catch (e) {
        last = ApiFailure<http.Response>(
          message: 'Could not reach the backend for $path: $e',
          kind: ApiFailureKind.network,
        );
      }

      if (attempt < attempts) {
        // Exponential backoff with jitter. Jitter matters: without it a
        // dozen widgets that all failed at once retry in lockstep.
        final int base = 300 * (1 << (attempt - 1));
        await Future<void>.delayed(
          Duration(milliseconds: base + _jitter.nextInt(250)),
        );
      }
    }

    return last ??
        const ApiFailure<http.Response>(
          message: 'Request failed for an unknown reason.',
        );
  }

  static String _snippet(String body) {
    final String trimmed = body.trim();
    if (trimmed.isEmpty) return '';
    return trimmed.length <= 180 ? trimmed : '${trimmed.substring(0, 180)}…';
  }
}
