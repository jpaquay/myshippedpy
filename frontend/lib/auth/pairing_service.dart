/// In-app pairing for Spotify (OAuth PKCE) and Last.fm (web auth).
///
/// ## The rule
///
/// The user never sees, types or pastes an API key. They tap "Connect", the
/// provider's own consent page opens, they approve, and they come back to a
/// connected account. Anything that asks a human to copy a token out of a
/// browser and into a text field is a broken product, not a security measure.
///
/// ## How the round trip works here
///
/// The backend owns the client secret and the token exchange; we never hold
/// either. Our part is:
///
///   1. Generate a PKCE verifier/challenge (Spotify only) and POST the
///      challenge to `/api/pair/spotify/start`. The backend returns an
///      `authorize_url` and a `state`.
///   2. Launch that URL in the system browser / a new tab.
///   3. The provider redirects to the BACKEND's callback, not to us. The
///      backend completes the exchange, stores the tokens against the
///      Firebase uid, and the user lands on a "you can close this" page.
///   4. We poll `/api/pair/status` until the provider flips to connected, or
///      the user gives up.
///
/// Polling rather than deep-linking is deliberate. A deep link back into the
/// app needs a custom URL scheme registered on both mobile platforms plus a
/// redirect page on web, and it fails silently in exactly the situations
/// (in-app browsers, corporate SSO interstitials) where you most need it to
/// work. Polling a status endpoint is dull and it always works.
///
/// The PKCE verifier is generated and retained here even though the backend
/// performs the exchange: if the backend prefers the client to complete the
/// exchange it can ask for the verifier, and generating it client-side is the
/// only way PKCE means anything. UNVERIFIED which side the final BAROGROOVE
/// backend does the exchange on; both are supported.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/client.dart';
import '../api/models.dart';

/// A music provider we can pair with.
enum PairingProvider {
  spotify('spotify', 'Spotify'),
  lastfm('lastfm', 'Last.fm');

  const PairingProvider(this.id, this.label);

  final String id;
  final String label;

  /// What the user loses by not connecting this one. Shown in the UI so the
  /// choice is informed rather than nagged.
  String get degradation => switch (this) {
        PairingProvider.spotify =>
          'Without Spotify, a forged set is delivered as an M3U file you '
              'download. Everything else works.',
        PairingProvider.lastfm =>
          'Without Last.fm there is no taste signal, so the forge runs '
              'theme-only. The rationale will say so.',
      };

  String get purpose => switch (this) {
        PairingProvider.spotify =>
          'Creates the playlist in your Spotify account.',
        PairingProvider.lastfm =>
          'Reads your scrobbles to weight tracks towards your taste.',
      };
}

/// Outcome of a pairing attempt.
enum PairingOutcome {
  connected,
  cancelled,
  timedOut,
  failed,
}

@immutable
class PairingAttempt {
  const PairingAttempt(this.outcome, {this.message, this.status});

  final PairingOutcome outcome;
  final String? message;
  final PairingStatus? status;

  bool get ok => outcome == PairingOutcome.connected;
}

/// PKCE verifier/challenge pair (RFC 7636, S256).
@immutable
class PkcePair {
  const PkcePair({required this.verifier, required this.challenge});

  final String verifier;
  final String challenge;

  /// 64 characters from the unreserved set, well inside the 43–128 the RFC
  /// allows.
  factory PkcePair.generate([Random? random]) {
    final Random rng = random ?? Random.secure();
    const String alphabet =
        'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
    final String verifier = List<String>.generate(
      64,
      (_) => alphabet[rng.nextInt(alphabet.length)],
    ).join();

    final Digest digest = sha256.convert(ascii.encode(verifier));
    final String challenge = base64Url
        .encode(digest.bytes)
        .replaceAll('=', ''); // base64url without padding, per the RFC.

    return PkcePair(verifier: verifier, challenge: challenge);
  }
}

/// Drives the pairing flows and exposes the resulting status.
class PairingService {
  PairingService(this._api);

  final BarogrooveApi _api;

  static const String _verifierKey = 'bg.pkce.verifier.spotify';
  static const String _stateKey = 'bg.pkce.state.spotify';

  /// How long we keep polling after opening the provider's page.
  static const Duration _pollWindow = Duration(minutes: 3);
  static const Duration _pollInterval = Duration(seconds: 2);

  Future<ApiResult<PairingStatus>> status() => _api.pairStatus();

  /// Starts and completes a pairing flow.
  ///
  /// Returns when the provider reports connected, the window expires, or
  /// something fails. Callers should show a "waiting for `<provider>`…" state
  /// with a cancel affordance while this is pending; pass [cancelled] to let
  /// the user stop the poll.
  Future<PairingAttempt> connect(
    PairingProvider provider, {
    String? redirectUri,
    Future<void>? cancelled,
  }) async {
    final ApiResult<PairingStart> start = switch (provider) {
      PairingProvider.spotify => await _startSpotify(redirectUri: redirectUri),
      PairingProvider.lastfm => await _api.startLastfmPairing(redirectUri: redirectUri),
    };

    final PairingStart? begin = start.valueOrNull;
    if (begin == null) {
      return PairingAttempt(
        PairingOutcome.failed,
        message: start.failureOrNull?.message ??
            'Could not start ${provider.label} pairing.',
      );
    }
    if (!begin.isValid) {
      return PairingAttempt(
        PairingOutcome.failed,
        message: 'The backend returned no authorize URL for '
            '${provider.label}.',
      );
    }

    if (provider == PairingProvider.spotify && begin.state != null) {
      await _remember(_stateKey, begin.state!);
    }

    final Uri? uri = Uri.tryParse(begin.authorizeUrl);
    if (uri == null) {
      return PairingAttempt(
        PairingOutcome.failed,
        message: 'The ${provider.label} authorize URL was malformed.',
      );
    }

    final bool launched = await launchUrl(
      uri,
      // On web this opens a new tab, which keeps our app state alive behind
      // it — important, because we are about to poll from that state.
      mode: kIsWeb
          ? LaunchMode.platformDefault
          : LaunchMode.externalApplication,
      webOnlyWindowName: kIsWeb ? '_blank' : null,
    );

    if (!launched) {
      return PairingAttempt(
        PairingOutcome.failed,
        message: 'Could not open the ${provider.label} authorisation page. '
            'If your browser blocked a popup, allow it and try again.',
      );
    }

    return _pollUntilConnected(provider, cancelled: cancelled);
  }

  Future<ApiResult<PairingStart>> _startSpotify({String? redirectUri}) async {
    final PkcePair pkce = PkcePair.generate();
    await _remember(_verifierKey, pkce.verifier);
    return _api.startSpotifyPairing(
      codeChallenge: pkce.challenge,
      redirectUri: redirectUri,
    );
  }

  /// Directly pairs Last.fm by public username (e.g., jpaquay).
  Future<PairingAttempt> connectLastfmUsername(String username) async {
    final ApiResult<PairingStatus> res =
        await _api.connectLastfmUsername(username.trim());
    return res.when(
      ok: (PairingStatus status) =>
          PairingAttempt(PairingOutcome.connected, status: status),
      failed: (ApiFailure<PairingStatus> f) =>
          PairingAttempt(PairingOutcome.failed, message: f.message),
    );
  }

  /// Completes Spotify pairing using a manually pasted redirect URL or code.
  Future<PairingAttempt> manualSpotifyExchange(
    String urlOrCode, {
    String? redirectUri,
  }) async {
    final ApiResult<PairingStatus> res = await _api.manualSpotifyExchange(
      urlOrCode: urlOrCode.trim(),
      redirectUri: redirectUri,
    );
    return res.when(
      ok: (PairingStatus status) =>
          PairingAttempt(PairingOutcome.connected, status: status),
      failed: (ApiFailure<PairingStatus> f) =>
          PairingAttempt(PairingOutcome.failed, message: f.message),
    );
  }

  /// Polls `/api/pair/status` until [provider] is connected.
  Future<PairingAttempt> _pollUntilConnected(
    PairingProvider provider, {
    Future<void>? cancelled,
  }) async {
    final DateTime deadline = DateTime.now().add(_pollWindow);
    var wasCancelled = false;
    unawaited(cancelled?.then((_) => wasCancelled = true));

    // A short grace period: the user has to read the provider's page before
    // there is any chance of a result, and hammering the endpoint in that
    // window is pure noise.
    await Future<void>.delayed(const Duration(seconds: 3));

    while (DateTime.now().isBefore(deadline)) {
      if (wasCancelled) {
        return const PairingAttempt(PairingOutcome.cancelled);
      }

      final ApiResult<PairingStatus> res = await _api.pairStatus();
      final PairingStatus? status = res.valueOrNull;

      if (status != null) {
        final bool connected = switch (provider) {
          PairingProvider.spotify => status.spotify,
          PairingProvider.lastfm => status.lastfm,
        };
        if (connected) {
          await _forget(_verifierKey);
          await _forget(_stateKey);
          return PairingAttempt(PairingOutcome.connected, status: status);
        }
      } else if (res.failureOrNull?.isAuth ?? false) {
        // Losing the session mid-pair is worth saying out loud.
        return const PairingAttempt(
          PairingOutcome.failed,
          message: 'Your session expired during pairing. Sign in and retry.',
        );
      }

      await Future<void>.delayed(_pollInterval);
    }

    return PairingAttempt(
      PairingOutcome.timedOut,
      message: 'We stopped waiting for ${provider.label}. If you finished '
          'authorising, pull to refresh — the connection may already be live.',
    );
  }

  Future<PairingAttempt> disconnect(PairingProvider provider) async {
    final ApiResult<PairingStatus> res = await _api.disconnect(provider.id);
    return res.when(
      ok: (PairingStatus s) =>
          PairingAttempt(PairingOutcome.connected, status: s),
      failed: (ApiFailure<PairingStatus> f) => PairingAttempt(
        PairingOutcome.failed,
        message: f.message,
      ),
    );
  }

  /// The PKCE verifier for the in-flight Spotify flow, if the backend asks
  /// the client to complete the exchange.
  Future<String?> pendingSpotifyVerifier() async {
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    return prefs.getString(_verifierKey);
  }

  Future<void> _remember(String key, String value) async {
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, value);
  }

  Future<void> _forget(String key) async {
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    await prefs.remove(key);
  }
}
