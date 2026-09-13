/// `UX_IA_SPEC.md` §2 rule 4: empty states are honest, and never show a
/// placeholder number.
///
/// The Almanac KPI strip used to read
/// `totalScrobbles > 0 ? totalScrobbles : 160717`, and the Set meta line
/// defaulted the city to "Brussels" and the theme to "petrichor". Each of those
/// renders as a measurement and is a guess — the exact failure mode this rule
/// exists to stop, and the one that does most damage on a dashboard someone
/// reads for the number.
///
/// A widget test cannot reach these: the KPI strip is a private method on a
/// screen that needs a live API client, and the value is a plain string. So
/// this reads the source, which is enough to stop the literal coming back — and
/// is honest about being a source guard rather than a behavioural one.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// The lines of `lib/<path>` that are actually code.
///
/// Comments are skipped throughout this file: the fix for each of these
/// defects is a comment that names the literal it removed, and a guard that
/// then trips on its own explanation is worse than no guard.
List<String> _codeLines(String path) {
  final File f = File('lib/$path');
  expect(
    f.existsSync(),
    isTrue,
    reason: 'expected to find lib/$path — has it moved?',
  );
  return f
      .readAsLinesSync()
      .where((String l) => !l.trimLeft().startsWith('//'))
      .toList();
}

String _code(String path) => _codeLines(path).join('\n');

void main() {
  group('no fabricated fallbacks', () {
    test('the Almanac KPI strip does not invent a catalog size', () {
      final String src = _code('screens/almanac_screen.dart');

      expect(
        src,
        isNot(contains('160717')),
        reason: 'the strip stood in 160717 scrobbles for missing analytics',
      );
      expect(
        src,
        isNot(contains('2649')),
        reason: 'and 2649 unique tracks alongside it',
      );

      // The honest treatment, and one spelling of it.
      expect(src, contains("const String _kNoValue = '—';"));
      expect(
        RegExp(r"_kNoValue").allMatches(src).length,
        greaterThanOrEqualTo(6),
        reason: 'every KPI that can be unknown says so the same way',
      );
    });

    test('the Almanac does not invent a favourite theme', () {
      final String src = _code('screens/almanac_screen.dart');

      // "Petrichor" is still a legitimate *filter option* and a real theme
      // label; what it may not be is a value substituted for missing data.
      expect(src, isNot(contains(": 'Petrichor',")));
      expect(src, isNot(contains("return 'Petrichor';")));
    });

    test('the Set meta line does not invent a city or a theme', () {
      final String src = _code('screens/playlist_screen.dart');

      expect(src, isNot(contains("'Brussels'")));
      expect(src, isNot(contains("'petrichor'")));
    });
  });

  group('the A2UI tree holds no private palette', () {
    test('no component names a colour of its own', () {
      final Directory dir = Directory('lib/a2ui');
      expect(dir.existsSync(), isTrue);

      // `Colors.transparent` is structural — "draw nothing here" — not a
      // palette choice, so it is allowed. Anything else that names a colour is
      // a private palette and belongs in `app_theme.dart` (§7.3).
      final RegExp namesAColour = RegExp(
        r'(?<![A-Za-z0-9_])Colors\.(?!transparent\b)[a-zA-Z]+'
        r'|Color\(0x[0-9a-fA-F]{8}\)'
        r'|Color\.fromARGB',
      );

      final List<String> offenders = <String>[];
      for (final FileSystemEntity e in dir.listSync(recursive: true)) {
        if (e is! File || !e.path.endsWith('.dart')) continue;
        final List<String> lines = e.readAsLinesSync();
        for (int i = 0; i < lines.length; i++) {
          final String line = lines[i];
          if (line.trimLeft().startsWith('//')) continue;
          if (line.trimLeft().startsWith('///')) continue;
          if (namesAColour.hasMatch(line)) {
            offenders.add('${e.path}:${i + 1}: ${line.trim()}');
          }
        }
      }

      expect(
        offenders,
        // `genre_corridor.dart` paints `Colors.white` label text over its own
        // dark corridor gradient. That file is not ours to change in this pass;
        // it is pinned here so the count cannot quietly grow.
        hasLength(1),
        reason: 'A2UI colour literals found:\n${offenders.join('\n')}',
      );
      expect(offenders.single, contains('genre_corridor.dart'));
    });
  });
}
