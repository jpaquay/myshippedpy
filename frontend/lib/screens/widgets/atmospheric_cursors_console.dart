import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app_theme.dart';
import '../../providers.dart';
import 'console/console_coefficients.dart';
import 'console/console_cursor_slider.dart';
import '../../widgets/bg_disclosure.dart';
import 'console/console_mode.dart';
import 'console/console_mode_control.dart';
import 'console/console_outcome_card.dart';
import 'console/console_source_request.dart';
import 'console/console_telemetry_row.dart';
import 'console/console_tokens.dart';
import 'console/forge_sky_reading.dart';

/// The Forge console: one three-segment control and a body that genuinely
/// changes rung with it (`docs/UX_IA_SPEC.md` §5).
///
/// What each mode renders — and, just as importantly, does not build at all —
/// is declared by [ConsoleMode], so the §5.2 table exists once in code:
///
/// | | Guided | Easy | Expert |
/// |---|---|---|---|
/// | mode control + helper | ● | ● | ● |
/// | outcome card | ● | ● | ● |
/// | temp / light / colour cursors | ✕ | ● | ● |
/// | `WHY THESE THREE` (rung 1) | ✕ | ● | ● |
/// | pressure / trend / BPM | ✕ | ✕ | ● |
/// | telemetry badges | ✕ | ✕ | ● |
/// | `COEFFICIENTS` (rung 1) | ✕ | ✕ | ● |
/// | `SOURCE REQUEST` (rung 2) | ✕ | ✕ | ● |
///
/// The sky dial is not here: it is a server-described A2UI surface, so the
/// Forge screen owns it and `ForgeSkyBlock` places it per mode.
///
/// The set of controls a mode shows is exactly the set of fields
/// `ForgeSelection.toRequest()` sends in that mode. Guided used to display
/// three cursors whose values were then nulled on the way out; it no longer
/// does.
class AtmosphericCursorsConsole extends ConsumerWidget {
  const AtmosphericCursorsConsole({this.skyReading, super.key});

  /// The live reading, used to phrase the Guided outcome. Null while the sky
  /// surface has not arrived — Guided then says so rather than guessing.
  final ForgeSkyReading? skyReading;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ForgeSelection selection = ref.watch(forgeSelectionProvider);
    final ForgeSelectionNotifier notifier =
        ref.read(forgeSelectionProvider.notifier);
    final ColorScheme colors = Theme.of(context).colorScheme;
    final ConsoleMode mode = ConsoleMode.fromId(selection.consoleMode);

    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BgSpace.br,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          ConsoleModeControl(
            mode: mode,
            onChanged: (ConsoleMode next) => notifier.setConsoleMode(next.id),
          ),
          const SizedBox(height: BgSpace.lg),
          // The body grows and shrinks in place; the FORGE call to action is
          // below it, so switching modes never moves anything the user is
          // pointing at (§5.1).
          AnimatedSize(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            alignment: Alignment.topCenter,
            child: KeyedSubtree(
              key: ValueKey<String>(mode.id),
              child: _body(context, mode, selection, notifier),
            ),
          ),
        ],
      ),
    );
  }

  Widget _body(
    BuildContext context,
    ConsoleMode mode,
    ForgeSelection selection,
    ForgeSelectionNotifier notifier,
  ) {
    return Column(
      key: ForgeKeys.body,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        ConsoleOutcomeCard(
          outcome: ConsoleOutcome.forMode(
            mode: mode,
            selection: selection,
            reading: skyReading,
          ),
        ),

        // ---- Easy and Expert: the three cursors that actually travel ------
        if (mode.showsCursors) ...<Widget>[
          const SizedBox(height: BgSpace.md),
          _CursorTriplet(
            children: <Widget>[
              ConsoleCursorSlider(
                key: ForgeKeys.cursorTemp,
                icon: Icons.thermostat_rounded,
                title: 'TEMPERATURE',
                valueLabel:
                    '${selection.customTempC >= 0 ? '+' : ''}${selection.customTempC.toStringAsFixed(1)} °C',
                subtitle: _tempMeaning(selection.customTempC),
                value: selection.customTempC,
                min: -15.0,
                max: 42.0,
                accentColor: Theme.of(context).colorScheme.primary,
                onChanged: (double v) =>
                    notifier.setAtmosphericCursors(tempC: v),
              ),
              ConsoleCursorSlider(
                key: ForgeKeys.cursorLight,
                icon: Icons.light_mode_rounded,
                title: 'LIGHT',
                valueLabel: '${selection.customLightPct.round()} %',
                subtitle: _lightPhaseLabel(selection.customLightPct),
                value: selection.customLightPct,
                min: 0.0,
                max: 100.0,
                accentColor: Theme.of(context).colorScheme.primary,
                onChanged: (double v) =>
                    notifier.setAtmosphericCursors(lightPct: v),
              ),
              ConsoleCursorSlider(
                key: ForgeKeys.cursorKelvin,
                icon: Icons.palette_outlined,
                title: 'COLOUR',
                valueLabel: '${selection.customColorKelvin.round()} K',
                subtitle: _kelvinLabel(selection.customColorKelvin),
                value: selection.customColorKelvin,
                min: 2000.0,
                max: 10000.0,
                accentColor: Theme.of(context).colorScheme.primary,
                onChanged: (double v) =>
                    notifier.setAtmosphericCursors(colorKelvin: v),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.md),
          BgDisclosure(
            key: ForgeKeys.whyTheseThree,
            label: 'Why these three',
            builder: (BuildContext context) => const _WhyTheseThree(),
          ),
        ],

        // ---- Expert only: the rest of the instrument panel ----------------
        if (mode.showsExpertSliders) ...<Widget>[
          const SizedBox(height: BgSpace.sm),
          _CursorTriplet(
            children: <Widget>[
              ConsoleCursorSlider(
                key: ForgeKeys.sliderPressure,
                icon: Icons.speed_rounded,
                title: 'PRESSURE',
                valueLabel:
                    '${selection.customPressureHpa.toStringAsFixed(0)} hPa',
                subtitle: _pressureMeaning(selection.customPressureHpa),
                value: selection.customPressureHpa,
                min: 975.0,
                max: 1040.0,
                accentColor: Theme.of(context).colorScheme.primary,
                onChanged: (double v) =>
                    notifier.setAtmosphericCursors(pressureHpa: v),
              ),
              ConsoleCursorSlider(
                key: ForgeKeys.sliderTrend,
                icon: Icons.trending_down_rounded,
                title: 'TREND',
                valueLabel:
                    '${selection.customTrendHpa >= 0 ? '+' : ''}${selection.customTrendHpa.toStringAsFixed(1)} hPa/3h',
                subtitle: _trendMeaning(selection.customTrendHpa),
                value: selection.customTrendHpa,
                min: -12.0,
                max: 12.0,
                accentColor: Theme.of(context).colorScheme.primary,
                onChanged: (double v) =>
                    notifier.setAtmosphericCursors(trendHpa: v),
              ),
              ConsoleCursorSlider(
                key: ForgeKeys.sliderBpm,
                icon: Icons.graphic_eq_rounded,
                title: 'TARGET BPM',
                valueLabel: '${selection.customTargetBpm.round()} BPM',
                subtitle: _bpmMeaning(selection.customTargetBpm),
                value: selection.customTargetBpm,
                min: 60.0,
                max: 165.0,
                accentColor: Theme.of(context).colorScheme.primary,
                onChanged: (double v) =>
                    notifier.setAtmosphericCursors(targetBpm: v),
              ),
            ],
          ),
        ],

        if (mode.showsInstrumentation) ...<Widget>[
          const SizedBox(height: BgSpace.md),
          const ConsoleTelemetryRow(),
          const SizedBox(height: BgSpace.md),
          BgDisclosure(
            key: ForgeKeys.coefficients,
            label: 'Coefficients',
            builder: (BuildContext context) =>
                ConsoleCoefficientsTable(selection: selection),
          ),
          ConsoleSourceRequestLink(selection: selection),
        ],
      ],
    );
  }
}

/// Three cards: stacked on a phone, side by side from the expanded breakpoint
/// (§5.4 — Expert at 390 px is long, and that is fine, because it is opt-in).
class _CursorTriplet extends StatelessWidget {
  const _CursorTriplet({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    if (BgBreak.isExpanded(context)) {
      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          for (int i = 0; i < children.length; i++) ...<Widget>[
            if (i > 0) const SizedBox(width: BgSpace.md),
            Expanded(child: children[i]),
          ],
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        for (int i = 0; i < children.length; i++) ...<Widget>[
          if (i > 0) const SizedBox(height: BgSpace.sm),
          children[i],
        ],
      ],
    );
  }
}

class _WhyTheseThree extends StatelessWidget {
  const _WhyTheseThree();

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    const List<(String, String)> lines = <(String, String)>[
      ('Temperature', 'sets how sparse or dense the arrangement gets.'),
      ('Light', 'moves the set between night weight and daylight lift.'),
      ('Colour', 'warm Kelvin pulls analogue, cool Kelvin pulls electronic.'),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        for (final (String name, String what) in lines)
          Padding(
            padding: const EdgeInsets.only(bottom: BgSpace.xs),
            child: Text.rich(
              TextSpan(
                children: <InlineSpan>[
                  TextSpan(text: '$name — ', style: text.titleSmall),
                  TextSpan(
                    text: what,
                    style: text.bodySmall
                        ?.copyWith(color: colors.onSurfaceVariant),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

// --------------------------------------------------------------------------
// Plain-language meanings. One line each: a cursor with no consequence stated
// is a cursor the user cannot reason about.
// --------------------------------------------------------------------------

String _tempMeaning(double tempC) {
  if (tempC < 5) return 'Crisp sub-zero, raw acoustic edge';
  if (tempC > 26) return 'Tropical heat, sun-drenched groove';
  return 'Temperate atmospheric balance';
}

String _lightPhaseLabel(double lightPct) {
  if (lightPct < 15) return 'Midnight thermal';
  if (lightPct < 35) return 'Blue hour / dawn';
  if (lightPct < 65) return 'Golden horizon';
  if (lightPct < 85) return 'High daylight';
  return 'Solar zenith';
}

String _kelvinLabel(double kelvin) {
  if (kelvin < 3000) return 'Warm sunset amber';
  if (kelvin < 4600) return 'Golden hour glow';
  if (kelvin < 6500) return 'Solar daylight';
  if (kelvin < 8200) return 'Cool dusk cyan';
  return 'Deep stratosphere';
}

String _pressureMeaning(double hPa) {
  if (hPa < 1000) return 'Deep cyclonic low, moody and dub-leaning';
  if (hPa > 1022) return 'Anticyclonic high, clear and bright';
  return 'Ordinary pressure, no strong pull';
}

String _trendMeaning(double hPa3h) {
  if (hPa3h <= -3) return 'Front arriving fast, heavier and slower';
  if (hPa3h >= 3) return 'Clearing fast, lighter and quicker';
  return 'Barometer steady';
}

String _bpmMeaning(double bpm) {
  if (bpm < 85) return 'Downtempo, long-form';
  if (bpm > 128) return 'Driving club velocity';
  return 'Mid-tempo headnod groove';
}
