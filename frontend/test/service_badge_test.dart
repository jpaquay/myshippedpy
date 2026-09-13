/// Connection badges (spec §7.5, plan item 14).
///
/// The two things worth pinning down: the badges are **monochrome** — the one
/// drop of colour is a dot that appears only when linked — and they report
/// **three** states, so a backend that has not answered yet is never rendered
/// as "not linked".
library;

import 'package:barogroove/api/models.dart';
import 'package:barogroove/app_theme.dart';
import 'package:barogroove/screens/widgets/service_badge.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Widget harness(Widget child, {Brightness brightness = Brightness.light}) {
  return MaterialApp(
    theme: brightness == Brightness.light ? BgTheme.light() : BgTheme.dark(),
    home: Scaffold(body: Center(child: child)),
  );
}

Text monogramOf(WidgetTester tester, String text) =>
    tester.widget<Text>(find.text(text));

void main() {
  group('state mapping reads the one source of truth', () {
    test('loading is unknown, not unlinked', () {
      const AsyncValue<PairingStatus> loading = AsyncLoading<PairingStatus>();
      final BgServiceLink link =
          BgServiceLink.of(loading, BgService.spotify);

      expect(link.isKnown, isFalse);
      expect(link.isLinked, isFalse);
      expect(link.statusWord, 'Status unknown');
    });

    test('an error is unknown, not unlinked', () {
      const AsyncValue<PairingStatus> failed =
          AsyncError<PairingStatus>('boom', StackTrace.empty);
      final BgServiceLink link = BgServiceLink.of(failed, BgService.lastfm);

      expect(link.isKnown, isFalse);
      expect(link.statusWord, 'Status unknown');
    });

    test('data maps each service independently', () {
      const AsyncValue<PairingStatus> data = AsyncData<PairingStatus>(
        PairingStatus(
          spotify: true,
          lastfm: false,
          spotifyAccount: 'jerome',
        ),
      );

      final BgServiceLink spotify = BgServiceLink.of(data, BgService.spotify);
      expect(spotify.isKnown, isTrue);
      expect(spotify.isLinked, isTrue);
      expect(spotify.statusWord, 'Linked as jerome');

      final BgServiceLink lastfm = BgServiceLink.of(data, BgService.lastfm);
      expect(lastfm.isKnown, isTrue);
      expect(lastfm.isLinked, isFalse);
      expect(lastfm.statusWord, 'Not linked');
    });

    test('linked without an account name still says linked', () {
      const AsyncValue<PairingStatus> data = AsyncData<PairingStatus>(
        PairingStatus(spotify: false, lastfm: true),
      );
      expect(
        BgServiceLink.of(data, BgService.lastfm).statusWord,
        'Linked',
      );
    });

    test('a badge names a pairing provider rather than redefining one', () {
      expect(BgService.spotify.label, 'Spotify');
      expect(BgService.lastfm.label, 'Last.fm');
      expect(BgService.spotify.monogram, 'SP');
      expect(BgService.lastfm.monogram, 'FM');
    });
  });

  group('the badge renders', () {
    testWidgets('linked: monogram in ink, plus the one dot',
        (WidgetTester tester) async {
      await tester.pumpWidget(
        harness(
          const ServiceBadge(
            service: BgService.spotify,
            linked: true,
            account: 'jerome',
          ),
        ),
      );

      expect(find.text('SP'), findsOneWidget);
      expect(find.byKey(linkedDotKey), findsOneWidget);

      final BgColors bg = Theme.of(tester.element(find.text('SP'))).bg;
      expect(monogramOf(tester, 'SP').style!.color, bg.connected);
      expect(monogramOf(tester, 'SP').style!.color, bg.inkPrimary);

      final Tooltip tip = tester.widget(find.byType(Tooltip));
      expect(tip.message, 'Spotify · Linked as jerome');
    });

    testWidgets('unlinked: muted, no dot', (WidgetTester tester) async {
      await tester.pumpWidget(
        harness(
          const ServiceBadge(service: BgService.lastfm, linked: false),
        ),
      );

      expect(find.text('FM'), findsOneWidget);
      expect(find.byKey(linkedDotKey), findsNothing);

      final BgColors bg = Theme.of(tester.element(find.text('FM'))).bg;
      expect(monogramOf(tester, 'FM').style!.color, bg.disconnected);

      final Tooltip tip = tester.widget(find.byType(Tooltip));
      expect(tip.message, 'Last.fm · Not linked');
    });

    testWidgets('unknown: muted, no dot, and it says so',
        (WidgetTester tester) async {
      await tester.pumpWidget(
        harness(const ServiceBadge.unknown(service: BgService.spotify)),
      );

      expect(find.byKey(linkedDotKey), findsNothing);
      final Tooltip tip = tester.widget(find.byType(Tooltip));
      expect(tip.message, 'Spotify · Status unknown');
    });

    testWidgets('no brand colour ever reaches the pill',
        (WidgetTester tester) async {
      const Color spotifyGreen = Color(0xFF1DB954);
      const Color lastfmRed = Color(0xFFD51007);

      for (final Brightness brightness in Brightness.values) {
        await tester.pumpWidget(
          harness(
            const Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                ServiceBadge(service: BgService.spotify, linked: true),
                ServiceBadge(service: BgService.lastfm, linked: false),
              ],
            ),
            brightness: brightness,
          ),
        );

        for (final String monogram in <String>['SP', 'FM']) {
          final Color? colour = monogramOf(tester, monogram).style?.color;
          expect(colour, isNot(spotifyGreen));
          expect(colour, isNot(lastfmRed));
        }

        // The border is a hairline in both states, never a brand colour.
        final BgColors bg = Theme.of(tester.element(find.text('SP'))).bg;
        final Container pill = tester.widget<Container>(
          find
              .descendant(
                of: find.byType(ServiceBadge).first,
                matching: find.byType(Container),
              )
              .first,
        );
        final BoxDecoration decoration = pill.decoration! as BoxDecoration;
        expect(decoration.color, Colors.transparent);
        expect(decoration.border!.top.color, bg.hairline);
        expect(decoration.borderRadius, BgSpace.brSm);
      }
    });

    testWidgets('the pill is 24 high with the small radius',
        (WidgetTester tester) async {
      await tester.pumpWidget(
        harness(const ServiceBadge(service: BgService.spotify, linked: true)),
      );
      final Size size = tester.getSize(
        find
            .descendant(
              of: find.byType(ServiceBadge),
              matching: find.byType(Container),
            )
            .first,
      );
      expect(size.height, 24);
    });
  });

  group('the Settings row', () {
    testWidgets('unlinked offers Connect', (WidgetTester tester) async {
      bool tapped = false;
      await tester.pumpWidget(
        harness(
          ServiceStatusRow(
            service: BgService.lastfm,
            link: const BgServiceLink.unlinked(),
            onConnect: () => tapped = true,
          ),
        ),
      );

      expect(find.text('Last.fm · Not linked'), findsOneWidget);
      expect(find.text('Connect'), findsOneWidget);
      expect(find.text('Disconnect'), findsNothing);

      await tester.tap(find.text('Connect'));
      expect(tapped, isTrue);
    });

    testWidgets('linked offers Disconnect', (WidgetTester tester) async {
      await tester.pumpWidget(
        harness(
          const ServiceStatusRow(
            service: BgService.spotify,
            link: BgServiceLink.linked('jerome'),
          ),
        ),
      );

      expect(find.text('Spotify · Linked as jerome'), findsOneWidget);
      expect(find.text('Disconnect'), findsOneWidget);
      expect(find.text('Connect'), findsNothing);
    });

    testWidgets('unknown offers nothing to press',
        (WidgetTester tester) async {
      await tester.pumpWidget(
        harness(
          const ServiceStatusRow(
            service: BgService.spotify,
            link: BgServiceLink.unknown(),
          ),
        ),
      );

      expect(find.text('Spotify · Status unknown'), findsOneWidget);
      expect(find.text('Connect'), findsNothing);
      expect(find.text('Disconnect'), findsNothing);
    });
  });
}
