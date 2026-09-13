/// The connection badges belong to ONE user (tenancy rework, item 4).
///
/// These are boundary tests, not happy-path ones. A badge that says
/// "Connected" is a statement about the person currently signed in; if it
/// survives a sign-out, or if it is rendered from a status fetched for
/// somebody else, the next person at that browser is told they are connected
/// to a Spotify account that is not theirs.
///
/// What is asserted here:
///   * signed out, the badges never render as linked, and no per-user status
///     request is made at all;
///   * signing out clears a badge that was linked a moment earlier, even when
///     the backend would still answer "connected";
///   * a user switch never renders the previous user's connection.
library;

import 'dart:async';

import 'package:barogroove/api/client.dart';
import 'package:barogroove/api/models.dart';
import 'package:barogroove/app_theme.dart';
import 'package:barogroove/auth/auth_service.dart';
import 'package:barogroove/auth/pairing_service.dart';
import 'package:barogroove/providers.dart';
import 'package:barogroove/screens/widgets/service_badge.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

/// A pairing service that always claims both providers are connected.
///
/// Deliberately unconditional: the client must not render a connection for a
/// user who is not signed in, no matter what an endpoint would reply. It also
/// counts calls, because "did not ask" is the stronger guarantee than "asked
/// and ignored the answer".
class _AlwaysConnectedPairing extends PairingService {
  _AlwaysConnectedPairing(this.account) : super(BarogrooveApi(client: _DeadClient()));

  final String account;
  int calls = 0;

  @override
  Future<ApiResult<PairingStatus>> status() async {
    calls += 1;
    return ApiOk<PairingStatus>(
      PairingStatus(
        spotify: true,
        lastfm: true,
        spotifyAccount: account,
        lastfmAccount: account,
      ),
    );
  }
}

/// Answers per uid, so a switch can be told apart from a stale render.
class _PerUserPairing extends PairingService {
  _PerUserPairing(this.byUid, this.uidNow)
      : super(BarogrooveApi(client: _DeadClient()));

  final Map<String, PairingStatus> byUid;
  final String? Function() uidNow;
  final List<String?> asked = <String?>[];

  @override
  Future<ApiResult<PairingStatus>> status() async {
    final String? uid = uidNow();
    asked.add(uid);
    return ApiOk<PairingStatus>(byUid[uid] ?? PairingStatus.none);
  }
}

/// No test here may reach the network; this makes that a failure, not a hang.
class _DeadClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    throw StateError('the badge tests must not perform HTTP');
  }
}

BgUser _user(String uid) => BgUser(
      uid: uid,
      displayName: uid,
      email: '$uid@example.test',
    );

Widget _strip(
  StreamController<BgUser?> auth,
  PairingService pairing,
) {
  return ProviderScope(
    overrides: <Override>[
      authStateProvider.overrideWith((Ref ref) => auth.stream),
      pairingServiceProvider.overrideWithValue(pairing),
    ],
    child: MaterialApp(
      theme: BgTheme.light(),
      home: const Scaffold(body: Center(child: ServiceBadgeStrip())),
    ),
  );
}

void main() {
  group('badges are per signed-in user', () {
    testWidgets('signed out: never linked, and never even asked',
        (WidgetTester tester) async {
      final StreamController<BgUser?> auth =
          StreamController<BgUser?>.broadcast();
      addTearDown(auth.close);
      final _AlwaysConnectedPairing pairing =
          _AlwaysConnectedPairing('someone-else');

      await tester.pumpWidget(_strip(auth, pairing));
      auth.add(null);
      await tester.pumpAndSettle();

      expect(find.byKey(linkedDotKey), findsNothing);
      expect(
        pairing.calls,
        0,
        reason: 'a signed-out client has no per-user state to fetch',
      );
    });

    testWidgets('signing out clears a badge that was linked',
        (WidgetTester tester) async {
      final StreamController<BgUser?> auth =
          StreamController<BgUser?>.broadcast();
      addTearDown(auth.close);
      final _AlwaysConnectedPairing pairing = _AlwaysConnectedPairing('jerome');

      await tester.pumpWidget(_strip(auth, pairing));
      auth.add(_user('uid-a'));
      await tester.pumpAndSettle();

      // Precondition: user A really is shown as connected.
      expect(find.byKey(linkedDotKey), findsWidgets);

      auth.add(null);
      await tester.pumpAndSettle();

      expect(
        find.byKey(linkedDotKey),
        findsNothing,
        reason: "user A's connection must not outlive user A's session",
      );
    });

    testWidgets('a user switch does not render the previous user',
        (WidgetTester tester) async {
      final StreamController<BgUser?> auth =
          StreamController<BgUser?>.broadcast();
      addTearDown(auth.close);

      BgUser? current;
      final _PerUserPairing pairing = _PerUserPairing(
        <String, PairingStatus>{
          'uid-a': const PairingStatus(
            spotify: true,
            lastfm: true,
            spotifyAccount: 'a-account',
            lastfmAccount: 'a-account',
          ),
          'uid-b': PairingStatus.none,
        },
        () => current?.uid,
      );

      await tester.pumpWidget(_strip(auth, pairing));
      current = _user('uid-a');
      auth.add(current);
      await tester.pumpAndSettle();
      expect(find.byKey(linkedDotKey), findsWidgets);

      current = _user('uid-b');
      auth.add(current);
      await tester.pumpAndSettle();

      expect(
        find.byKey(linkedDotKey),
        findsNothing,
        reason: "user B is not connected; A's badge must not carry over",
      );
      expect(pairing.asked, <String?>['uid-a', 'uid-b']);
    });
  });
}
