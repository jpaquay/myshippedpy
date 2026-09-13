/// The theme glyph lookup, asserted.
///
/// `theme_chips.dart` used to pick a glyph by *guessing* from substrings of the
/// theme id — `contains('rain')`, `contains('fog')`, `contains('sun')` — with a
/// final `return Icons.graphic_eq`. Four of BAROGROOVE's eight canonical themes
/// (heatwave_cruise, blue_hour, first_frost, sirocco) matched no branch, so all
/// four wore the same meaningless glyph. Presentation knowledge had leaked into
/// Dart and drifted from the Python that owns it.
///
/// The renderer now resolves a semantic token supplied by the backend
/// (`palette.THEME_ICONS` -> the theme item's `icon` key). These tests pin the
/// two properties that make that fix permanent:
///
///   1. Every canonical theme's token resolves to a REAL, DISTINCT glyph — not
///      the fallback. Adding a theme without an icon goes red here rather than
///      shipping a grey blob.
///   2. The map is statically analysable, so `--tree-shake-icons` keeps the
///      glyphs. An `IconData` built from a runtime codepoint would pass a unit
///      test and render blank boxes in a release web build, so the source is
///      checked for that too.
///
/// The Python half of the contract lives in `tests/test_theme_icons.py`, which
/// reads this file and asserts the two vocabularies cannot silently diverge.
library;

import 'dart:io';

import 'package:barogroove/a2ui/components/theme_chips.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// The canonical eight, mirroring `THEME_IDS` in `backend/app/contracts.py`,
/// paired with the token `THEME_ICONS` emits for each. If the backend table
/// changes, `tests/test_theme_icons.py` fails and points here.
const Map<String, String> _canonicalThemeTokens = <String, String>{
  'petrichor': 'water_drop',
  'golden_hour': 'wb_twilight',
  'nordic_fog': 'foggy',
  'storm_front': 'thunderstorm',
  'heatwave_cruise': 'wb_sunny',
  'blue_hour': 'nights_stay',
  'first_frost': 'ac_unit',
  'sirocco': 'air',
};

void main() {
  group('every canonical theme resolves to a real glyph', () {
    _canonicalThemeTokens.forEach((String themeId, String token) {
      test('$themeId ("$token") is mapped and is not the fallback', () {
        expect(
          kThemeIconsByToken.containsKey(token),
          isTrue,
          reason:
              '$themeId sends the icon token "$token" and this build has no '
              'entry for it — the chip would draw the fallback glyph. Add it '
              'to kThemeIconsByToken in theme_chips.dart.',
        );
        expect(
          themeIconForToken(token),
          isNot(kThemeIconFallback),
          reason:
              '$themeId resolves to the fallback glyph. That is exactly the '
              'bug this lookup replaced.',
        );
      });
    });

    test('all eight glyphs are distinct', () {
      final Set<IconData> glyphs = _canonicalThemeTokens.values
          .map(themeIconForToken)
          .toSet();
      expect(
        glyphs.length,
        _canonicalThemeTokens.length,
        reason:
            'two themes share a glyph, so the chips stop distinguishing them',
      );
    });

    test('all eight tokens are distinct', () {
      expect(
        _canonicalThemeTokens.values.toSet().length,
        _canonicalThemeTokens.length,
      );
    });
  });

  group('the fallback is exactly one, and only for the unknown', () {
    test('an unknown token falls back', () {
      expect(themeIconForToken('no_such_token'), kThemeIconFallback);
    });

    test('a missing token falls back', () {
      expect(themeIconForToken(null), kThemeIconFallback);
      expect(themeIconForToken(''), kThemeIconFallback);
    });

    test('no canonical theme is allowed to use the fallback glyph', () {
      for (final String token in _canonicalThemeTokens.values) {
        expect(kThemeIconsByToken[token], isNot(kThemeIconFallback));
      }
    });
  });

  group('the lookup survives icon tree-shaking', () {
    final File source = File('lib/a2ui/components/theme_chips.dart');

    test('theme_chips.dart is where the map lives', () {
      expect(source.existsSync(), isTrue);
    });

    test('no IconData is built from a runtime codepoint', () {
      // `IconData(0xe1a5, fontFamily: 'MaterialIcons')` passes every unit test
      // and renders a blank box in `flutter build web --tree-shake-icons`,
      // because the compiler can no longer prove which glyphs are reachable.
      expect(
        RegExp(r'IconData\s*\(').hasMatch(source.readAsStringSync()),
        isFalse,
        reason:
            'theme_chips.dart constructs an IconData instead of referencing an '
            'Icons.* constant; release web builds would show blank boxes',
      );
    });

    test('the guessing branches are gone for good', () {
      final String text = source.readAsStringSync();
      // Substring sniffing on the theme id is the original defect. The words
      // may appear in comments explaining the fix; a live `contains(` call on
      // a lowercased id may not.
      final Iterable<String> code = text
          .split('\n')
          .map((String line) => line.trimLeft())
          .where((String line) => !line.startsWith('//') && !line.startsWith('///'));
      expect(
        code.any((String line) => line.contains('.contains(')),
        isFalse,
        reason: 'theme_chips.dart is guessing from the theme id again',
      );
      expect(code.any((String line) => line.contains('_iconForTheme')), isFalse);
    });
  });
}
