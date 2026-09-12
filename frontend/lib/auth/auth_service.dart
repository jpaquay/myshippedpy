/// Google sign-in via Firebase, for web and mobile from one codebase.
///
/// ## The platform split, and why it exists
///
/// VERIFIED (google_sign_in 7.x, current at time of writing): the package was
/// redesigned. There is now a singleton `GoogleSignIn.instance`, an explicit
/// `initialize()` that must complete before anything else, `authenticate()`
/// for interactive sign-in, and `attemptLightweightAuthentication()` in place
/// of the old `signInSilently()`. Crucially, **`authenticate()` throws
/// `UnsupportedError` on web** — the web implementation cannot open an
/// interactive flow from arbitrary Dart code, because Google Identity
/// Services requires either a rendered button or a popup triggered directly
/// by a user gesture.
///
/// So:
///   * WEB    -> `FirebaseAuth.instance.signInWithPopup(GoogleAuthProvider())`.
///               One call, no google_sign_in involvement, works on
///               bg.netdev.be as long as the domain is in Firebase Auth's
///               authorised domains list.
///   * MOBILE -> `GoogleSignIn.instance.authenticate()` to get an ID token,
///               then exchange it for a Firebase credential.
///
/// Also VERIFIED: in 7.x, `GoogleSignInAuthentication` exposes only `idToken`.
/// The OAuth access token moved to the separate `authorizationClient`. Firebase
/// accepts a credential built from `idToken` alone, so we do not need it —
/// which is convenient, because asking for it would trigger a second consent
/// prompt for no benefit.
///
/// UNVERIFIED: whether `GoogleSignIn.instance.initialize()` requires
/// `clientId` on Android in the current release. We pass the optional
/// server/client IDs from --dart-define when present and omit them otherwise,
/// which is correct on iOS (reads Info.plist) and on Android (reads
/// google-services.json).
library;

import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:google_sign_in/google_sign_in.dart';

/// The app's view of who is signed in.
@immutable
class BgUser {
  const BgUser({
    required this.uid,
    required this.displayName,
    required this.email,
    this.photoUrl,
  });

  final String uid;
  final String displayName;
  final String email;
  final String? photoUrl;

  /// Initials for the avatar fallback. Two letters, upper case, no emoji.
  String get initials {
    final List<String> parts = displayName
        .trim()
        .split(RegExp(r'\s+'))
        .where((String p) => p.isNotEmpty)
        .toList();
    if (parts.isEmpty) {
      return email.isEmpty ? '?' : email[0].toUpperCase();
    }
    if (parts.length == 1) return parts.first[0].toUpperCase();
    return '${parts.first[0]}${parts.last[0]}'.toUpperCase();
  }

  static BgUser? fromFirebase(User? user) {
    if (user == null) return null;
    return BgUser(
      uid: user.uid,
      displayName: user.displayName ?? user.email?.split('@').first ?? 'You',
      email: user.email ?? '',
      photoUrl: user.photoURL,
    );
  }
}

/// A sign-in attempt that did not produce a session.
class AuthFailure implements Exception {
  const AuthFailure(this.message, {this.code});

  final String message;
  final String? code;

  @override
  String toString() => message;
}

/// Wraps Firebase Auth and google_sign_in behind one small surface.
class AuthService {
  AuthService({FirebaseAuth? auth}) : _auth = auth ?? FirebaseAuth.instance;

  final FirebaseAuth _auth;

  bool _googleInitialised = false;

  /// Optional overrides for platforms that need an explicit client id.
  static const String _serverClientId =
      String.fromEnvironment('BG_GOOGLE_SERVER_CLIENT_ID');
  static const String _clientId = String.fromEnvironment('BG_GOOGLE_CLIENT_ID');

  /// Emits on every session change. The router listens to this.
  Stream<BgUser?> get userChanges =>
      _auth.userChanges().map(BgUser.fromFirebase);

  BgUser? get currentUser => BgUser.fromFirebase(_auth.currentUser);

  bool get isSignedIn => _auth.currentUser != null;

  /// Prepares google_sign_in. Safe to call repeatedly; a no-op on web, where
  /// we do not use the package's interactive path at all.
  Future<void> ensureInitialised() async {
    if (kIsWeb || _googleInitialised) return;
    await GoogleSignIn.instance.initialize(
      clientId: _clientId.isEmpty ? null : _clientId,
      serverClientId: _serverClientId.isEmpty ? null : _serverClientId,
    );
    _googleInitialised = true;
  }

  /// Attempts to restore a session without showing UI.
  ///
  /// Firebase already persists its own session, so this only matters on
  /// mobile for the first run after a reinstall, where the Google account is
  /// still authorised but Firebase has no local user.
  Future<BgUser?> restoreSession() async {
    if (_auth.currentUser != null) return currentUser;
    if (kIsWeb) return null;

    try {
      await ensureInitialised();
      final GoogleSignInAccount? account =
          await GoogleSignIn.instance.attemptLightweightAuthentication();
      if (account == null) return null;
      return _exchange(account);
    } catch (_) {
      // A silent restore that fails is not worth reporting; the user simply
      // sees the sign-in screen.
      return null;
    }
  }

  /// Interactive Google sign-in.
  Future<BgUser> signInWithGoogle() async {
    try {
      if (kIsWeb) return await _signInWeb();
      return await _signInMobile();
    } on FirebaseAuthException catch (e) {
      throw AuthFailure(_explain(e), code: e.code);
    } on GoogleSignInException catch (e) {
      // Cancelling is not an error worth shouting about, but the caller still
      // needs to know nothing happened.
      if (e.code == GoogleSignInExceptionCode.canceled) {
        throw const AuthFailure('Sign-in was cancelled.', code: 'cancelled');
      }
      throw AuthFailure('Google sign-in failed: ${e.description ?? e.code}');
    } catch (e) {
      throw AuthFailure('Sign-in failed: $e');
    }
  }

  /// Web: Firebase's own popup. google_sign_in's `authenticate()` is
  /// explicitly unsupported here in 7.x, so do not "unify" these two paths.
  Future<BgUser> _signInWeb() async {
    final GoogleAuthProvider provider = GoogleAuthProvider()
      ..addScope('email')
      ..addScope('profile')
      // Always show the chooser: a shared laptop signing the wrong colleague
      // into someone's Almanac is a bad first impression.
      ..setCustomParameters(<String, String>{'prompt': 'select_account'});

    final UserCredential credential = await _auth.signInWithPopup(provider);
    final BgUser? user = BgUser.fromFirebase(credential.user);
    if (user == null) {
      throw const AuthFailure('Google returned no account.');
    }
    return user;
  }

  /// Mobile: google_sign_in 7.x -> ID token -> Firebase credential.
  Future<BgUser> _signInMobile() async {
    await ensureInitialised();
    final GoogleSignInAccount account =
        await GoogleSignIn.instance.authenticate(
      scopeHint: const <String>['email', 'profile'],
    );
    return _exchange(account);
  }

  Future<BgUser> _exchange(GoogleSignInAccount account) async {
    // In 7.x `authentication` is a synchronous getter returning
    // GoogleSignInAuthentication, which carries idToken only.
    final GoogleSignInAuthentication auth = account.authentication;
    final String? idToken = auth.idToken;
    if (idToken == null) {
      throw const AuthFailure(
        'Google did not return an ID token. Check that the OAuth client for '
        'this platform is configured in the Firebase console.',
      );
    }

    final OAuthCredential credential =
        GoogleAuthProvider.credential(idToken: idToken);
    final UserCredential result = await _auth.signInWithCredential(credential);
    final BgUser? user = BgUser.fromFirebase(result.user);
    if (user == null) {
      throw const AuthFailure('Firebase returned no user.');
    }
    return user;
  }

  Future<void> signOut() async {
    // Order matters: revoke the Google session first so the next sign-in
    // shows the chooser rather than silently reusing the same account.
    if (!kIsWeb) {
      try {
        await ensureInitialised();
        await GoogleSignIn.instance.signOut();
      } catch (_) {
        // A failure to clear the Google session must not block signing out
        // of the app.
      }
    }
    await _auth.signOut();
  }

  /// Turns Firebase's error codes into something a person can act on.
  static String _explain(FirebaseAuthException e) => switch (e.code) {
        'popup-closed-by-user' ||
        'cancelled-popup-request' =>
          'Sign-in was cancelled.',
        'popup-blocked' =>
          'Your browser blocked the sign-in popup. Allow popups for this site '
              'and try again.',
        'network-request-failed' =>
          'No network. Check your connection and try again.',
        'unauthorized-domain' =>
          'This domain is not in the Firebase Auth authorised domains list. '
              'Add it in the Firebase console under Authentication → Settings.',
        'account-exists-with-different-credential' =>
          'That email is already registered with a different sign-in method.',
        _ => e.message ?? 'Sign-in failed (${e.code}).',
      };
}
