import 'package:barogroove/api/models.dart';
import 'package:barogroove/app_theme.dart';
import 'package:barogroove/providers.dart';
import 'package:barogroove/screens/widgets/atmospheric_cursors_console.dart';
import 'package:barogroove/screens/widgets/console/console_tokens.dart';
import 'package:barogroove/screens/widgets/console/forge_sky_block.dart';
import 'package:barogroove/screens/widgets/console/forge_sky_reading.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Item 8 — the Forge console's three modes (`docs/UX_IA_SPEC.md` §5).
///
/// These tests are written at **390 × 844**, the phone the spec budgets for,
/// and they assert what each mode does *not* render as carefully as what it
/// does: §5.2's legend says "✕ not rendered at all (not merely `Opacity(0)`)",
/// which is only meaningful if something checks.
void main() {
  const Size phone = Size(390, 844);
  const Size desktop = Size(1280, 900);

  const ForgeSkyReading fallingSky = ForgeSkyReading(
    trendDisplay: '-4.2 hPa',
    trendTone: 'falling',
    trendCaption: 'falling',
    tempDisplay: '-1.8 °C',
    lightDisplay: '12.4°',
  );

  /// The backend is unreachable in the test environment, and that is the point:
  /// `healthProvider` is pinned to the same value it takes when `/api/health`
  /// fails, so the Expert telemetry badges are exercised on their degraded path.
  ProviderScope harness({
    ForgeSkyReading? reading,
    Widget? child,
  }) {
    return ProviderScope(
      overrides: <Override>[
        healthProvider.overrideWith((Ref ref) async => HealthStatus.unknown),
      ],
      child: MaterialApp(
        theme: BgTheme.light(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: child ?? AtmosphericCursorsConsole(skyReading: reading),
          ),
        ),
      ),
    );
  }

  Future<void> sizeTo(WidgetTester tester, Size size) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
  }

  ProviderContainer containerOf(WidgetTester tester) =>
      ProviderScope.containerOf(
        tester.element(find.byType(MaterialApp)),
      );

  Future<void> setMode(WidgetTester tester, String mode) async {
    containerOf(tester).read(forgeSelectionProvider.notifier).setConsoleMode(mode);
    await tester.pumpAndSettle();
  }

  // ---------------------------------------------------------------- affordance

  group('the affordance (§5.1)', () {
    testWidgets('one full-width segmented control, three segments, no icons',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();

      expect(find.byKey(ForgeKeys.modeControl), findsOneWidget);
      expect(find.text('Guided'), findsOneWidget);
      expect(find.text('Easy'), findsOneWidget);
      expect(find.text('Expert'), findsOneWidget);

      final SegmentedButton<String> control = tester
          .widget<SegmentedButton<String>>(find.byKey(ForgeKeys.modeControl));
      expect(control.segments.length, 3);
      expect(control.showSelectedIcon, isFalse);
      for (final ButtonSegment<String> s in control.segments) {
        expect(s.icon, isNull);
      }

      // Full width at 390 minus the screen gutter the console sits in.
      final double width =
          tester.getSize(find.byKey(ForgeKeys.modeControl)).width;
      expect(width, greaterThan(320));
    });

    testWidgets('a permanent one-line helper changes with the mode',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();

      Text helper() => tester.widget<Text>(find.byKey(ForgeKeys.modeHelper));
      expect(helper().data, 'Guided — we choose everything.');

      await tester.tap(find.text('Easy'));
      await tester.pumpAndSettle();
      expect(helper().data, 'Easy — nudge three dials.');

      await tester.tap(find.text('Expert'));
      await tester.pumpAndSettle();
      expect(helper().data, 'Expert — the full instrument panel.');
    });

    testWidgets('tapping a segment moves consoleMode, and the old '
        '"switch to Easy" text button is gone', (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();

      expect(
        containerOf(tester).read(forgeSelectionProvider).consoleMode,
        'guided',
      );
      await tester.tap(find.text('Expert'));
      await tester.pumpAndSettle();
      expect(
        containerOf(tester).read(forgeSelectionProvider).consoleMode,
        'expert',
      );
      expect(find.textContaining('switch to Easy'), findsNothing);
    });
  });

  // -------------------------------------------------------------------- guided

  group('Guided at 390 px (§5.2, §5.3)', () {
    testWidgets('is the outcome card and nothing else',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();

      // Shown.
      expect(find.byKey(ForgeKeys.outcomeCard), findsOneWidget);
      expect(find.text('Slower, denser, minor-key.'), findsOneWidget);
      expect(find.text('Falling pressure asks for weight.'), findsOneWidget);

      // Not rendered at all.
      expect(find.byKey(ForgeKeys.cursorTemp), findsNothing);
      expect(find.byKey(ForgeKeys.cursorLight), findsNothing);
      expect(find.byKey(ForgeKeys.cursorKelvin), findsNothing);
      expect(find.byKey(ForgeKeys.whyTheseThree), findsNothing);
      expect(find.byKey(ForgeKeys.sliderPressure), findsNothing);
      expect(find.byKey(ForgeKeys.sliderTrend), findsNothing);
      expect(find.byKey(ForgeKeys.sliderBpm), findsNothing);
      expect(find.byKey(ForgeKeys.telemetryRow), findsNothing);
      expect(find.byKey(ForgeKeys.coefficients), findsNothing);
      expect(find.byKey(ForgeKeys.sourceRequest), findsNothing);
      expect(find.byType(Slider), findsNothing);
      expect(tester.takeException(), isNull);
    });

    // Measured at the time of writing: 105.0 px (a 356 × 105 outcome card in a
    // 390 px viewport). 15 px of head-room against the budget.
    testWidgets('body fits the 120 px budget', (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();

      final double height = tester.getSize(find.byKey(ForgeKeys.body)).height;
      expect(
        height,
        lessThanOrEqualTo(ForgeMetrics.guidedBodyBudget),
        reason: '§5.3: Guided taller than 120 px is wrong. Got $height.',
      );
    });

    testWidgets('with no live sky it says so instead of inventing a forecast',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness());
      await tester.pumpAndSettle();

      expect(find.text('The sky decides.'), findsOneWidget);
      expect(
        find.text('No live reading yet — we read it when you forge.'),
        findsOneWidget,
      );
      expect(
        tester.getSize(find.byKey(ForgeKeys.body)).height,
        lessThanOrEqualTo(ForgeMetrics.guidedBodyBudget),
      );
    });
  });

  // ---------------------------------------------------------------------- easy

  group('Easy at 390 px (§5.2)', () {
    testWidgets('adds exactly the three cursors and a collapsed rationale',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'easy');

      expect(find.byKey(ForgeKeys.outcomeCard), findsOneWidget);
      expect(find.byKey(ForgeKeys.cursorTemp), findsOneWidget);
      expect(find.byKey(ForgeKeys.cursorLight), findsOneWidget);
      expect(find.byKey(ForgeKeys.cursorKelvin), findsOneWidget);
      expect(find.byType(Slider), findsNWidgets(3));

      // WHY THESE THREE is present, collapsed, and its body is not built.
      expect(find.byKey(ForgeKeys.whyTheseThree), findsOneWidget);
      expect(find.text('WHY THESE THREE'), findsOneWidget);
      expect(find.textContaining('sets how sparse'), findsNothing);

      // Expert instrumentation stays away.
      expect(find.byKey(ForgeKeys.sliderPressure), findsNothing);
      expect(find.byKey(ForgeKeys.sliderTrend), findsNothing);
      expect(find.byKey(ForgeKeys.sliderBpm), findsNothing);
      expect(find.byKey(ForgeKeys.telemetryRow), findsNothing);
      expect(find.byKey(ForgeKeys.coefficients), findsNothing);
      expect(find.byKey(ForgeKeys.sourceRequest), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('opening WHY THESE THREE builds its body',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'easy');

      await tester.tap(find.text('WHY THESE THREE'));
      await tester.pumpAndSettle();
      expect(find.textContaining('sets how sparse'), findsOneWidget);
    });

    testWidgets('the three cursors stack, they do not squeeze into a row',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'easy');

      final Rect temp = tester.getRect(find.byKey(ForgeKeys.cursorTemp));
      final Rect light = tester.getRect(find.byKey(ForgeKeys.cursorLight));
      final Rect kelvin = tester.getRect(find.byKey(ForgeKeys.cursorKelvin));

      expect(light.top, greaterThan(temp.bottom - 1));
      expect(kelvin.top, greaterThan(light.bottom - 1));
      expect(temp.left, closeTo(light.left, 0.5));
      expect(temp.width, greaterThan(300));
      expect(tester.takeException(), isNull);
    });
  });

  // -------------------------------------------------------------------- expert

  group('Expert at 390 px (§5.2, §5.4)', () {
    testWidgets('promotes the full instrument panel', (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'expert');

      expect(find.byKey(ForgeKeys.outcomeCard), findsOneWidget);
      expect(find.byKey(ForgeKeys.cursorTemp), findsOneWidget);
      expect(find.byKey(ForgeKeys.cursorLight), findsOneWidget);
      expect(find.byKey(ForgeKeys.cursorKelvin), findsOneWidget);
      expect(find.byKey(ForgeKeys.sliderPressure), findsOneWidget);
      expect(find.byKey(ForgeKeys.sliderTrend), findsOneWidget);
      expect(find.byKey(ForgeKeys.sliderBpm), findsOneWidget);
      expect(find.byType(Slider), findsNWidgets(6));
      expect(find.byKey(ForgeKeys.telemetryRow), findsOneWidget);
      expect(find.byKey(ForgeKeys.whyTheseThree), findsOneWidget);
      expect(find.byKey(ForgeKeys.coefficients), findsOneWidget);
      expect(find.byKey(ForgeKeys.sourceRequest), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('COEFFICIENTS is collapsed until asked for',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'expert');

      expect(find.text('COEFFICIENTS'), findsOneWidget);
      expect(find.textContaining('Client-side preview'), findsNothing);

      await tester.scrollUntilVisible(find.text('COEFFICIENTS'), 120);
      await tester.tap(find.text('COEFFICIENTS'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Client-side preview'), findsOneWidget);
    });

    testWidgets('SOURCE REQUEST opens a rung-2 sheet showing the real body',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'expert');

      await tester.scrollUntilVisible(find.byKey(ForgeKeys.sourceRequest), 120);
      await tester.tap(find.byKey(ForgeKeys.sourceRequest));
      await tester.pumpAndSettle();

      expect(find.text('SOURCE REQUEST'), findsOneWidget);
      expect(find.textContaining('custom_pressure_hpa'), findsOneWidget);
      expect(find.text('Close'), findsOneWidget);
    });

    testWidgets('telemetry badges print a dash when the backend is unreachable',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'expert');

      expect(find.text('AVG LATENCY'), findsOneWidget);
      expect(find.text('—'), findsNWidgets(3));
    });

    testWidgets('all six sliders stack on a phone and nothing overflows',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'expert');

      final Rect pressure = tester.getRect(find.byKey(ForgeKeys.sliderPressure));
      final Rect trend = tester.getRect(find.byKey(ForgeKeys.sliderTrend));
      final Rect bpm = tester.getRect(find.byKey(ForgeKeys.sliderBpm));
      expect(trend.top, greaterThan(pressure.bottom - 1));
      expect(bpm.top, greaterThan(trend.bottom - 1));
      expect(pressure.width, greaterThan(300));
      expect(tester.takeException(), isNull);
    });

    testWidgets('at 1280 px the triplets sit side by side (§5.4 keeps the row '
        'above the wide breakpoint)', (WidgetTester tester) async {
      await sizeTo(tester, desktop);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'expert');

      final Rect temp = tester.getRect(find.byKey(ForgeKeys.cursorTemp));
      final Rect light = tester.getRect(find.byKey(ForgeKeys.cursorLight));
      expect(light.left, greaterThan(temp.right - 1));
      expect(light.top, closeTo(temp.top, 0.5));
      expect(tester.takeException(), isNull);
    });
  });

  // ------------------------------------------------- the UI tells the truth

  group('modes match what toRequest() actually sends', () {
    testWidgets('guided renders no control whose value it then nulls',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();

      final ForgeRequest request =
          containerOf(tester).read(forgeSelectionProvider).toRequest();
      expect(request.customTempC, isNull);
      expect(request.customLightPct, isNull);
      expect(request.customColorKelvin, isNull);
      expect(request.customPressureHpa, isNull);
      expect(find.byType(Slider), findsNothing);
    });

    testWidgets('easy renders exactly the three fields it sends',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'easy');

      final ForgeRequest request =
          containerOf(tester).read(forgeSelectionProvider).toRequest();
      expect(request.customTempC, isNotNull);
      expect(request.customLightPct, isNotNull);
      expect(request.customColorKelvin, isNotNull);
      expect(request.customPressureHpa, isNull);
      expect(request.customTrendHpa, isNull);
      expect(request.customTargetBpm, isNull);
      expect(find.byType(Slider), findsNWidgets(3));
    });

    testWidgets('expert renders all six fields it sends',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(reading: fallingSky));
      await tester.pumpAndSettle();
      await setMode(tester, 'expert');

      final ForgeRequest request =
          containerOf(tester).read(forgeSelectionProvider).toRequest();
      expect(request.customTempC, isNotNull);
      expect(request.customPressureHpa, isNotNull);
      expect(request.customTrendHpa, isNotNull);
      expect(request.customTargetBpm, isNotNull);
      expect(find.byType(Slider), findsNWidgets(6));
    });
  });

  // ----------------------------------------------------------------- sky block

  group('the sky follows the mode (§5.2)', () {
    Widget skyBlock() => const ForgeSkyBlock(
          reading: fallingSky,
          dial: SizedBox(key: Key('dial-under-test'), height: 240),
        );

    testWidgets('guided: three values, no dial', (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(child: skyBlock()));
      await tester.pumpAndSettle();

      expect(find.byKey(ForgeKeys.skyStrip), findsOneWidget);
      expect(find.text('-4.2 hPa'), findsOneWidget);
      expect(find.byKey(const Key('dial-under-test')), findsNothing);
      expect(find.byKey(ForgeKeys.skyDetail), findsNothing);
    });

    testWidgets('easy: strip plus SKY DETAIL, collapsed',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(child: skyBlock()));
      await tester.pumpAndSettle();
      await setMode(tester, 'easy');

      expect(find.byKey(ForgeKeys.skyStrip), findsOneWidget);
      expect(find.byKey(ForgeKeys.skyDetail), findsOneWidget);
      expect(find.byKey(const Key('dial-under-test')), findsNothing);

      await tester.tap(find.text('SKY DETAIL'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('dial-under-test')), findsOneWidget);
    });

    testWidgets('expert: the dial replaces the strip at rung 0',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(harness(child: skyBlock()));
      await tester.pumpAndSettle();
      await setMode(tester, 'expert');

      expect(find.byKey(ForgeKeys.skyStrip), findsNothing);
      expect(find.byKey(ForgeKeys.skyDetail), findsNothing);
      expect(find.byKey(const Key('dial-under-test')), findsOneWidget);
    });

    testWidgets('a missing surface prints dashes, not numbers',
        (WidgetTester tester) async {
      await sizeTo(tester, phone);
      await tester.pumpWidget(
        harness(
          child: const ForgeSkyBlock(
            reading: ForgeSkyReading.unavailable,
            dial: SizedBox(key: Key('dial-under-test'), height: 240),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('—'), findsNWidgets(3));
    });
  });
}
