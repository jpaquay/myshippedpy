/// The appearance control: three options, and a choice that survives a
/// restart (spec §7.4, plan item 13).
///
/// What matters here is not that a `SegmentedButton` renders — it is that
/// **"As host" is what a first run gets**, that an explicit choice is written
/// to the same storage the rest of the app already uses, and that a corrupt
/// or future value degrades to the default instead of taking the app down on
/// start-up.
library;

import 'package:barogroove/app_theme.dart';
import 'package:barogroove/providers.dart';
import 'package:barogroove/screens/widgets/theme_mode_control.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// A container whose controller has finished reading storage.
Future<ProviderContainer> restoredContainer() async {
  final ProviderContainer container = ProviderContainer();
  addTearDown(container.dispose);
  await container.read(bgThemeChoiceProvider.notifier).restored;
  return container;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('default and persistence', () {
    test('first run follows the host, not a hardcoded dark', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final ProviderContainer container = await restoredContainer();

      expect(container.read(bgThemeChoiceProvider), BgThemeChoice.host);
      expect(container.read(themeModeProvider), ThemeMode.system);
    });

    test('a stored choice is restored on the next launch', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        BgThemeController.storageKey: 'light',
      });
      final ProviderContainer container = await restoredContainer();

      expect(container.read(bgThemeChoiceProvider), BgThemeChoice.light);
      expect(container.read(themeModeProvider), ThemeMode.light);
    });

    test('an unrecognised stored value degrades to the default', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        BgThemeController.storageKey: 'solarized-midnight',
      });
      final ProviderContainer container = await restoredContainer();

      expect(container.read(bgThemeChoiceProvider), BgThemeChoice.host);
    });

    test('round trip: choose, then relaunch', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});

      final ProviderContainer first = await restoredContainer();
      await first.read(bgThemeChoiceProvider.notifier).choose(
            BgThemeChoice.dark,
          );
      expect(first.read(themeModeProvider), ThemeMode.dark);

      // What actually landed in storage.
      final SharedPreferences prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(BgThemeController.storageKey), 'dark');

      // A fresh process reading the same storage.
      final ProviderContainer second = await restoredContainer();
      expect(second.read(bgThemeChoiceProvider), BgThemeChoice.dark);
    });

    test('every choice maps to a ThemeMode and back', () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final ProviderContainer container = await restoredContainer();

      for (final BgThemeChoice choice in BgThemeChoice.values) {
        await container.read(bgThemeChoiceProvider.notifier).choose(choice);
        expect(container.read(themeModeProvider), choice.mode);
        expect(BgThemeChoice.byId(choice.id), choice);
      }
      expect(BgThemeChoice.host.mode, ThemeMode.system);
    });
  });

  group('the control itself', () {
    Widget harness({Size size = const Size(390, 844)}) {
      return ProviderScope(
        child: MaterialApp(
          theme: BgTheme.light(),
          darkTheme: BgTheme.dark(),
          home: MediaQuery(
            data: MediaQueryData(size: size),
            child: const Scaffold(
              body: Center(child: ThemeModeControl()),
            ),
          ),
        ),
      );
    }

    testWidgets('offers exactly three options, labelled per spec',
        (WidgetTester tester) async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      await tester.pumpWidget(harness());
      await tester.pumpAndSettle();

      expect(find.byType(SegmentedButton<BgThemeChoice>), findsOneWidget);
      expect(find.text('Dark'), findsOneWidget);
      expect(find.text('Light'), findsOneWidget);
      expect(find.text('As host'), findsOneWidget);

      final SegmentedButton<BgThemeChoice> control = tester.widget(
        find.byType(SegmentedButton<BgThemeChoice>),
      );
      expect(control.segments.length, 3);
      // The selected option is never re-stated with a checkmark; the wash and
      // the accent label carry it.
      expect(control.showSelectedIcon, isFalse);
      expect(control.selected, <BgThemeChoice>{BgThemeChoice.host});
    });

    testWidgets('tapping an option persists it', (WidgetTester tester) async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      await tester.pumpWidget(harness());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Light'));
      await tester.pumpAndSettle();

      final SegmentedButton<BgThemeChoice> control = tester.widget(
        find.byType(SegmentedButton<BgThemeChoice>),
      );
      expect(control.selected, <BgThemeChoice>{BgThemeChoice.light});

      final SharedPreferences prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(BgThemeController.storageKey), 'light');
    });

    testWidgets('a stored choice is reflected without a tap',
        (WidgetTester tester) async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        BgThemeController.storageKey: 'dark',
      });
      await tester.pumpWidget(harness());
      await tester.pumpAndSettle();

      final SegmentedButton<BgThemeChoice> control = tester.widget(
        find.byType(SegmentedButton<BgThemeChoice>),
      );
      expect(control.selected, <BgThemeChoice>{BgThemeChoice.dark});
    });

    testWidgets('light mode renders on light surfaces, not inverted dark',
        (WidgetTester tester) async {
      SharedPreferences.setMockInitialValues(<String, Object>{
        BgThemeController.storageKey: 'light',
      });
      await tester.pumpWidget(harness());
      await tester.pumpAndSettle();

      final BuildContext context = tester.element(find.byType(Card));
      final ThemeData theme = Theme.of(context);
      expect(theme.brightness, Brightness.light);
      expect(theme.bg.surfaceRaised, BgPalette.white);
      expect(theme.bg.inkPrimary, BgPalette.slate900);
    });
  });
}
