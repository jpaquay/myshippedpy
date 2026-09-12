/// Attaches the Firebase ID token to outbound requests.
///
/// Implemented as an `http.BaseClient` wrapper rather than a helper that
/// callers remember to invoke, because the failure mode of "remembered
/// everywhere except one place" is a silent 401 on the one endpoint that
/// mattered.
///
/// Token freshness: `FirebaseAuth.currentUser.getIdToken()` returns a cached
/// token and refreshes it automatically when it is within five minutes of
/// expiry, so we do not manage expiry ourselves. We do force a refresh once
/// after a 401, on the theory that the only interesting cause of a 401 with a
/// signed-in user is a token the backend considers stale.
library;

import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;

/// Supplies a bearer token, or null when signed out.
typedef TokenProvider = Future<String?> Function({bool forceRefresh});

/// Reads the current Firebase user's ID token.
Future<String?> firebaseIdToken({bool forceRefresh = false}) async {
  final User? user = FirebaseAuth.instance.currentUser;
  if (user == null) return null;
  try {
    return await user.getIdToken(forceRefresh);
  } on FirebaseAuthException {
    // A revoked session should log the user out, not crash a background
    // fetch. Returning null degrades the call to anonymous, and the backend
    // decides whether that is allowed.
    return null;
  }
}

/// An [http.Client] that adds `Authorization: Bearer …` and retries once on
/// 401 with a force-refreshed token.
class AuthedClient extends http.BaseClient {
  AuthedClient({
    http.Client? inner,
    TokenProvider? tokenProvider,
  })  : _inner = inner ?? http.Client(),
        _tokenProvider = tokenProvider ?? firebaseIdToken;

  final http.Client _inner;
  final TokenProvider _tokenProvider;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final String? token = await _tokenProvider(forceRefresh: false);
    if (token != null) {
      request.headers['authorization'] = 'Bearer $token';
    }

    final http.StreamedResponse response = await _inner.send(request);
    if (response.statusCode != 401 || token == null) return response;

    // One retry with a fresh token. A streamed request body cannot be
    // replayed, so only retry when we can rebuild the request.
    final http.BaseRequest? replay = _copy(request);
    if (replay == null) return response;

    final String? fresh = await _tokenProvider(forceRefresh: true);
    if (fresh == null || fresh == token) return response;

    replay.headers['authorization'] = 'Bearer $fresh';
    // Drain the original so the connection is not left hanging.
    unawaited(response.stream.drain<void>().catchError((_) {}));
    return _inner.send(replay);
  }

  /// Rebuilds a request for replay. Returns null for streamed bodies, which
  /// we cannot re-read.
  static http.BaseRequest? _copy(http.BaseRequest original) {
    if (original is http.Request) {
      return http.Request(original.method, original.url)
        ..headers.addAll(original.headers)
        ..bodyBytes = original.bodyBytes
        ..followRedirects = original.followRedirects
        ..maxRedirects = original.maxRedirects
        ..persistentConnection = original.persistentConnection;
    }
    return null;
  }

  @override
  void close() {
    _inner.close();
    super.close();
  }
}

/// Header map for callers that build their own requests (the A2UI action
/// dispatcher does this, because it owns its retry policy).
Future<Map<String, String>> authHeaders() async {
  final String? token = await firebaseIdToken();
  return <String, String>{
    if (token != null) 'authorization': 'Bearer $token',
  };
}
