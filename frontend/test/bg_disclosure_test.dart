/// The disclosure ladder, asserted (`docs/UX_IA_SPEC.md` §2).
///
/// Three workers each shipped a local copy of these rules before
/// `lib/widgets/bg_disclosure.dart` existed. These tests pin the two
/// behaviours the swap had to preserve — the body is not built while collapsed,
/// and ≥ 900 px may default a tile open — plus the fact that the deprecated
/// forwarders left behind for files other workers own carry no numbers of their
/// own.
library;

import 'package:barogroove/app_theme.dart';
import 'package:barogroove/screens/dataviz/dataviz_tokens.dart';
import 'package:barogroove/screens/widgets/console/console_tokens.dart';
import 'package:barogroove/widgets/bg_disclosure.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Sentinel that records whether the disclosure body was ever built.
class _BodyProbe extends StatelessWidget {
  const _BodyProbe();

  static bool built = false;

  @override
  Widget build(BuildContext context) {
    built = true;
    return const Text('BODY');
  }
}

Future<void> _pumpAt(
  WidgetTester tester,
  Size size,
  Widget child,
) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    MaterialApp(
      theme: BgTheme.light(),
      home: Scaffold(body: SingleChildScrollView(child: child)),
    ),
  );
  await tester.pump();
}

void main() {
  setUp(() => _BodyProbe.built = false);

  group('BgDisclosure — rung 1', () {
    testWidgets('does not build its body while collapsed', (
      WidgetTester tester,
    ) async {
      await _pumpAt(
        tester,
        const Size(390, 844),
        const BgDisclosure(
          label: 'Why these three',
          builder: _build,
        ),
      );

      expect(find.text('WHY THESE THREE'), findsOneWidget);
      expect(find.text('BODY'), findsNothing);
      expect(
        _BodyProbe.built,
        isFalse,
        reason: 'a collapsed rung 1 must not build its body at all — '
            '"does not render X" has to mean exactly that',
      );
    });

    testWidgets('builds the body once opened, and the chevron rotates', (
      WidgetTester tester,
    ) async {
      await _pumpAt(
        tester,
        const Size(390, 844),
        const BgDisclosure(label: 'Coefficients', builder: _build),
      );

      AnimatedRotation rotation() => tester.widget<AnimatedRotation>(
            find.byType(AnimatedRotation),
          );
      expect(rotation().turns, 0.0);

      await tester.tap(find.text('COEFFICIENTS'));
      await tester.pumpAndSettle();

      expect(find.text('BODY'), findsOneWidget);
      expect(_BodyProbe.built, isTrue);
      expect(rotation().turns, 0.5);
      expect(rotation().duration, const Duration(milliseconds: 180));
    });

    testWidgets('header is the eyebrow role, uppercased, over a 1 px rule', (
      WidgetTester tester,
    ) async {
      await _pumpAt(
        tester,
        const Size(390, 844),
        const BgDisclosure(label: 'Source query', builder: _build),
      );

      final Text header = tester.widget<Text>(find.text('SOURCE QUERY'));
      expect(header.style!.fontSize, BgTheme.light().textTheme.labelSmall!.fontSize);

      final Divider rule = tester.widget<Divider>(find.byType(Divider));
      expect(rule.thickness, 1);
      expect(rule.color, BgTheme.light().colorScheme.outlineVariant);

      final Icon chevron = tester.widget<Icon>(
        find.byIcon(Icons.keyboard_arrow_down),
      );
      expect(chevron.size, BgIcon.inline);
      expect(chevron.size, 18);
    });

    testWidgets('the ≥ 900 default-open rule survives', (
      WidgetTester tester,
    ) async {
      await _pumpAt(
        tester,
        const Size(1200, 900),
        Builder(
          builder: (BuildContext context) => BgDisclosure(
            label: 'Summary',
            initiallyExpanded: BgBreak.disclosureDefaultOpen(context),
            builder: _build,
          ),
        ),
      );

      expect(find.text('BODY'), findsOneWidget);
    });

    testWidgets('… and below 900 the same call site starts closed', (
      WidgetTester tester,
    ) async {
      await _pumpAt(
        tester,
        const Size(899, 844),
        Builder(
          builder: (BuildContext context) => BgDisclosure(
            label: 'Summary',
            initiallyExpanded: BgBreak.disclosureDefaultOpen(context),
            builder: _build,
          ),
        ),
      );

      expect(find.text('BODY'), findsNothing);
      expect(_BodyProbe.built, isFalse);
    });

    testWidgets('a trailing label ellipsises rather than push the chevron off',
        (WidgetTester tester) async {
      await _pumpAt(
        tester,
        const Size(390, 844),
        const BgDisclosure(
          label: 'Source query',
          trailingLabel: 'Gemini Data Analytics · BigQuery, and then some more',
          builder: _build,
        ),
      );

      final Text trailing = tester.widget<Text>(
        find.textContaining('Gemini Data Analytics'),
      );
      expect(trailing.maxLines, 1);
      expect(trailing.overflow, TextOverflow.ellipsis);
      expect(find.byIcon(Icons.keyboard_arrow_down), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('showBgDetailSheet — rung 2', () {
    testWidgets('below 900 it is a modal bottom sheet with a Close', (
      WidgetTester tester,
    ) async {
      await _pumpAt(
        tester,
        const Size(390, 844),
        Builder(
          builder: (BuildContext context) => TextButton(
            onPressed: () => showBgDetailSheet(
              context,
              title: 'Source request',
              builder: _build,
            ),
            child: const Text('open'),
          ),
        ),
      );

      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();

      expect(find.text('SOURCE REQUEST'), findsOneWidget);
      expect(find.text('BODY'), findsOneWidget);
      expect(find.text('Close'), findsOneWidget);
      expect(find.byType(FractionallySizedBox), findsOneWidget);
      expect(find.byType(Dialog), findsNothing);
    });

    testWidgets('at 900 and above it is a 420 px side panel, not a Dialog', (
      WidgetTester tester,
    ) async {
      await _pumpAt(
        tester,
        const Size(1200, 900),
        Builder(
          builder: (BuildContext context) => TextButton(
            onPressed: () => showBgDetailSheet(
              context,
              title: 'Source request',
              builder: _build,
            ),
            child: const Text('open'),
          ),
        ),
      );

      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();

      expect(find.text('SOURCE REQUEST'), findsOneWidget);
      expect(find.text('Close'), findsOneWidget);
      expect(find.byType(Dialog), findsNothing);
      expect(
        tester
            .getSize(
              find.ancestor(
                of: find.text('SOURCE REQUEST'),
                matching: find.byType(Material),
              ).first,
            )
            .width,
        kBgDetailPanelWidth,
      );
    });
  });

  group('the deprecated forwarders carry no numbers of their own', () {
    test('DvBreak forwards to BgBreak, with the same buckets', () {
      expect(DvBreak.compact, BgBreak.compact);
      expect(DvBreak.expanded, BgBreak.expanded);
      expect(DvBreak.compact, 600);
      expect(DvBreak.expanded, 900);

      // The screen used to hard-code 920; 920 and 900 must land in the same
      // bucket (§4).
      expect(DvBreak.isExpanded(920), isTrue);
      expect(DvBreak.isExpanded(900), isTrue);
      expect(DvBreak.isExpanded(899), isFalse);
      expect(BgBreak.forWidth(920), BgBreak.forWidth(900));

      expect(DvBreak.isCompact(599), isTrue);
      expect(DvBreak.isCompact(600), isFalse);
    });

    test('DvSpace and ForgeMetrics forward to BgSpace', () {
      expect(DvSpace.bubbleClearance, BgSpace.bubbleClearance);
      expect(DvSpace.xxxl, BgSpace.xxxl);
      expect(ForgeMetrics.bubbleClearance, BgSpace.bubbleClearance);

      expect(BgSpace.bubbleClearance, 96);
      expect(BgSpace.xxxl, 48);
    });
  });
}

Widget _build(BuildContext context) => const _BodyProbe();
