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

    // ---------------------------------------------------------------------
    // Data Viz. The same defect as the Almanac KPI strip, one destination
    // over, and a much larger instance of it.
    // ---------------------------------------------------------------------

    test('the Data Viz models carry no fabricated dashboard', () {
      final String src = _code('screens/dataviz/dataviz_models.dart');

      // `DataVizDashboardModel.fallback()` was ~90 lines of invented
      // analytics, and it was the screen's *initial state* — not dead code.
      expect(
        src,
        isNot(contains('fallback()')),
        reason: 'the canned dashboard was the value `_dashboard` started at',
      );
      for (final String literal in <String>[
        '160717', // total scrobbles
        '102.4', // average tempo
        '0.84', // "pressure sensitivity index"
        '20893', // "High Pressure Clarity" scrobbles
        '38572', // Petrichor scrobbles
        'Teardrop', // the stand-in track, artist and album
        'Massive Attack',
        'Mezzanine',
        'Nocturnal Dub', // the stand-in hourly mood
      ]) {
        expect(src, isNot(contains(literal)), reason: '$literal is back');
      }

      // The one spelling of "no value", shared with the Almanac strip.
      expect(src, contains("const String kDvNoValue = '—';"));
    });

    test('the Data Viz screen starts empty, not full', () {
      final String src = _code('screens/dataviz_screen.dart');

      expect(src, contains('DataVizDashboardModel.empty'));
      expect(
        src,
        isNot(contains('DataVizDashboardModel.fallback')),
        reason: 'every user saw the canned figures before any real data landed',
      );
      // A failed load now empties the dashboard rather than leaving invented
      // charts on screen behind a "this is a sample" label.
      expect(src, isNot(contains('_dashboardIsSample')));
      expect(src, contains('_dashboardFailed'));
    });

    test('the Data Viz cards state no finding of their own', () {
      final String src = _code('screens/dataviz/dataviz_dashboard.dart');

      // Card titles and subtitles used to assert results — a share, a play
      // count, a BPM range, a decade span — as static strings, so they stayed
      // put no matter what the backend actually returned.
      for (final String literal in <String>[
        '160,717',
        '38,572',
        '24.0% Share',
        '78 BPM Storm',
        '132 BPM Zenith',
        '1970s – 2020s',
        'Bristol Trip-Hop',
        'Solar Zenith',
        'Midnight Thermal',
        'low_pressure_front',
      ]) {
        expect(src, isNot(contains(literal)), reason: '$literal is back');
      }

      // Every card handles having nothing to draw.
      expect(
        RegExp(r'_buildChartEmptyState\(').allMatches(src).length,
        greaterThanOrEqualTo(4),
        reason: 'all four standing cards need an honest empty state',
      );
      expect(
        RegExp(r'kDvNoValue').allMatches(src).length,
        greaterThanOrEqualTo(6),
        reason: 'every figure that can be unknown says so the same way',
      );
    });

    // ---------------------------------------------------------------------
    // Tenancy and location.
    // ---------------------------------------------------------------------

    test('the Almanac sync does not name a Last.fm account', () {
      final String src = _code('screens/almanac_screen.dart');

      // A literal handle here meant every signed-in user's "Sync Last.fm"
      // pulled the same real person's listening history into their almanac.
      expect(src, isNot(contains("'jpaquay'")));
      expect(src, contains('pairingStatusProvider'));
    });

    test('a geocache with no coordinates is not placed in Brussels', () {
      final String src = _code('api/models.dart');

      // `lat: ?? 50.8503, lon: ?? 4.3517` put any landmark the backend sent
      // without coordinates in Belgium, and fetched Belgian weather for it.
      expect(src, isNot(contains('50.8503')));
      expect(src, isNot(contains('4.3517')));
      // ...along with the clock that came with it.
      expect(src, isNot(contains("'14:00 (UTC+1)'")));
      expect(src, isNot(contains("?? 'afternoon'")));
    });

    test('parsed analytics do not stand in a tempo', () {
      final String src = _code('api/models.dart');

      // `avg_bpm ?? 112.0` / `?? 102.0` and `bpm_estimate ?? 112` / `?? 102`
      // rendered as a measured tempo beside honest em-dashes.
      for (final String literal in <String>[
        "?? 112.0",
        "?? 102.0",
        "?? 112)",
        "?? 102)",
        "?? 0.60,",
        "?? 0.54,",
      ]) {
        expect(src, isNot(contains(literal)), reason: '$literal is back');
      }
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
