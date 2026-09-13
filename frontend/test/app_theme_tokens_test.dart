/// The design system, asserted.
///
/// These are the rules from `docs/UX_IA_SPEC.md` §7 that a reviewer would
/// otherwise have to enforce by eye: the frozen type scale, radius discipline,
/// the three breakpoints, and the fact that every colour role is reachable
/// from the theme rather than from a widget's private palette.
library;

import 'package:barogroove/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('type scale is frozen', () {
    for (final ThemeData theme in <ThemeData>[
      BgTheme.light(),
      BgTheme.dark(),
    ]) {
      final String name = theme.brightness.name;
      final TextTheme t = theme.textTheme;

      test('$name: sizes match the spec table', () {
        expect(t.displaySmall!.fontSize, 34);
        expect(t.headlineMedium!.fontSize, 24);
        expect(t.headlineSmall!.fontSize, 20);
        expect(t.titleLarge!.fontSize, 18);
        expect(t.titleMedium!.fontSize, 15);
        expect(t.titleSmall!.fontSize, 13);
        expect(t.bodyLarge!.fontSize, 16);
        expect(t.bodyMedium!.fontSize, 14);
        expect(t.bodySmall!.fontSize, 13);
        expect(t.labelLarge!.fontSize, 14);
        expect(t.labelMedium!.fontSize, 12);
        expect(t.labelSmall!.fontSize, 11);
      });

      test('$name: no fractional sizes', () {
        for (final TextStyle? style in <TextStyle?>[
          t.displaySmall,
          t.headlineMedium,
          t.headlineSmall,
          t.titleLarge,
          t.titleMedium,
          t.titleSmall,
          t.bodyLarge,
          t.bodyMedium,
          t.bodySmall,
          t.labelLarge,
          t.labelMedium,
          t.labelSmall,
        ]) {
          expect(style!.fontSize! % 1, 0, reason: '$style has a fraction');
        }
      });

      test('$name: w700 is banned; w500 is reserved for meta', () {
        final Map<String, TextStyle?> styles = <String, TextStyle?>{
          'displaySmall': t.displaySmall,
          'headlineMedium': t.headlineMedium,
          'headlineSmall': t.headlineSmall,
          'titleLarge': t.titleLarge,
          'titleMedium': t.titleMedium,
          'titleSmall': t.titleSmall,
          'bodyLarge': t.bodyLarge,
          'bodyMedium': t.bodyMedium,
          'bodySmall': t.bodySmall,
          'labelLarge': t.labelLarge,
          'labelSmall': t.labelSmall,
        };
        styles.forEach((String slot, TextStyle? style) {
          expect(
            style!.fontWeight,
            isNot(FontWeight.w700),
            reason: '$slot must not be w700',
          );
          expect(
            style.fontWeight,
            isNot(FontWeight.w500),
            reason: 'w500 is reserved for BgText.meta, not $slot',
          );
        });
        expect(t.labelMedium!.fontWeight, FontWeight.w500);
      });
    }
  });

  test('BgText.numeric asks for tabular figures', () {
    final TextStyle style = BgText.numeric(const TextStyle(fontSize: 15));
    expect(style.fontFeatures, contains(const FontFeature.tabularFigures()));
    expect(style.fontSize, 15);
  });

  group('radius discipline', () {
    test('nothing is rounder than 10 except the sheet grab-edge', () {
      expect(BgSpace.radius, 10);
      expect(BgSpace.radiusSm, 6);
      expect(BgSpace.radiusSheet, 16);
    });

    test('cards and controls use the small/regular radius', () {
      for (final ThemeData theme in <ThemeData>[
        BgTheme.light(),
        BgTheme.dark(),
      ]) {
        final RoundedRectangleBorder card =
            theme.cardTheme.shape! as RoundedRectangleBorder;
        expect(card.borderRadius, BgSpace.br);

        final RoundedRectangleBorder sheet =
            theme.bottomSheetTheme.shape! as RoundedRectangleBorder;
        expect(sheet.borderRadius, BgSpace.brSheet);
      }
    });
  });

  group('breakpoints', () {
    test('there are exactly three, at 600 and 900', () {
      expect(BgBreak.compact, 600);
      expect(BgBreak.expanded, 900);
      expect(BgBreak.forWidth(390), BgBreakpoint.compact);
      expect(BgBreak.forWidth(599), BgBreakpoint.compact);
      expect(BgBreak.forWidth(600), BgBreakpoint.medium);
      expect(BgBreak.forWidth(899), BgBreakpoint.medium);
      expect(BgBreak.forWidth(900), BgBreakpoint.expanded);
      // The old dataviz 920 must resolve to the same bucket as 900.
      expect(BgBreak.forWidth(920), BgBreak.forWidth(900));
    });
  });

  group('colour roles', () {
    test('are attached to the theme, not owned by a widget', () {
      expect(BgTheme.light().bg.hairline, BgPalette.slate200);
      expect(BgTheme.dark().bg.hairline, BgPalette.slate700);
      expect(BgTheme.light().bg.surfaceBase, BgPalette.slate50);
      expect(BgTheme.dark().bg.surfaceBase, BgPalette.slate900);
    });

    test('a linked badge is monochrome, never green', () {
      for (final ThemeData theme in <ThemeData>[
        BgTheme.light(),
        BgTheme.dark(),
      ]) {
        expect(theme.bg.connected, theme.bg.inkPrimary);
        expect(theme.bg.connected, isNot(theme.bg.statusOk));
        expect(theme.bg.disconnected, theme.bg.inkTertiary);
      }
    });

    test('dark mode separates with hairlines, not shadows', () {
      expect(BgTheme.dark().colorScheme.shadow, Colors.transparent);
      expect(BgTheme.light().colorScheme.shadow, isNot(Colors.transparent));
    });

    test('a tinted A2UI surface moves the accent and nothing else', () {
      final ThemeData base = BgTheme.dark();
      final ThemeData tinted = BgTheme.tinted(base, const Color(0xFF7C3AED));

      expect(tinted.bg.accent, const Color(0xFF7C3AED));
      // Structure is untouched: the renderer cannot acquire a private palette.
      expect(tinted.bg.hairline, base.bg.hairline);
      expect(tinted.bg.surfaceBase, base.bg.surfaceBase);
      expect(tinted.bg.inkPrimary, base.bg.inkPrimary);
    });
  });

  test('chrome icons are never larger than 20', () {
    expect(BgIcon.chrome, 20);
    expect(BgIcon.inline, 18);
    expect(BgIcon.nav, 24);
    for (final ThemeData theme in <ThemeData>[
      BgTheme.light(),
      BgTheme.dark(),
    ]) {
      expect(theme.appBarTheme.actionsIconTheme!.size, BgIcon.chrome);
      expect(theme.appBarTheme.iconTheme!.size, BgIcon.chrome);
    }
  });
}
