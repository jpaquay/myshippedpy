import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app_theme.dart';
import '../../providers.dart';

/// Desktop & Mobile Atmospheric Synthesis Console.
///
/// Replaces the static time-of-day display with an interactive 3-mode
/// control deck:
///   1. Guided (Happy Path)  - Automatic Weathercaster & Geo-Cache solar time
///   2. Adjustable (Easy)    - Temp (°C), Sky Color (Kelvin), & Light (%) cursors
///   3. Expert / Advanced    - Full Barometer (hPa), 6h Derivative, & BPM lock
///                             with real-time Sonic Vector preview bars.
class AtmosphericCursorsConsole extends ConsumerStatefulWidget {
  const AtmosphericCursorsConsole({
    this.onTriggerForge,
    super.key,
  });

  final VoidCallback? onTriggerForge;

  @override
  ConsumerState<AtmosphericCursorsConsole> createState() =>
      _AtmosphericCursorsConsoleState();
}

class _AtmosphericCursorsConsoleState
    extends ConsumerState<AtmosphericCursorsConsole> {
  /// Maps Kelvin (2000K..10000K) to a realistic atmospheric sky tint.
  Color _kelvinToColor(double kelvin) {
    final double t = ((kelvin - 2000.0) / 8000.0).clamp(0.0, 1.0);
    if (t < 0.35) {
      // Warm Amber / Sunset Gold -> Soft Peach
      return Color.lerp(
        const Color(0xFFD97706),
        const Color(0xFFF59E0B),
        t / 0.35,
      )!;
    } else if (t < 0.65) {
      // Soft Peach -> Horizon Sky Blue
      return Color.lerp(
        const Color(0xFFF59E0B),
        const Color(0xFF0EA5E9),
        (t - 0.35) / 0.30,
      )!;
    } else {
      // Horizon Sky Blue -> Deep Stratosphere Cyan / Indigo
      return Color.lerp(
        const Color(0xFF0EA5E9),
        const Color(0xFF1D4ED8),
        (t - 0.65) / 0.35,
      )!;
    }
  }

  String _lightPhaseLabel(double lightPct) {
    if (lightPct < 15) return 'Midnight Thermal (00:00)';
    if (lightPct < 35) return 'Blue Hour / Dawn (06:15)';
    if (lightPct < 65) return 'Golden Horizon (17:45)';
    if (lightPct < 85) return 'High Daylight (14:00)';
    return 'Solar Zenith (12:00)';
  }

  String _kelvinLabel(double kelvin) {
    if (kelvin < 3000) return 'Warm Sunset Amber (${kelvin.round()}K)';
    if (kelvin < 4600) return 'Golden Hour Glow (${kelvin.round()}K)';
    if (kelvin < 6500) return 'Solar Daylight (${kelvin.round()}K)';
    if (kelvin < 8200) return 'Cool Dusk Cyan (${kelvin.round()}K)';
    return 'Deep Stratosphere (${kelvin.round()}K)';
  }

  @override
  Widget build(BuildContext context) {
    final ForgeSelection selection = ref.watch(forgeSelectionProvider);
    final ForgeSelectionNotifier notifier =
        ref.read(forgeSelectionProvider.notifier);
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    final String mode = selection.consoleMode; // 'guided' | 'easy' | 'expert'
    final Color skyColor = _kelvinToColor(selection.customColorKelvin);
    final double brightnessFactor =
        0.25 + (selection.customLightPct / 100.0) * 0.75;

    // Derived preview metrics for Expert mode sonic vector bars
    final double energyPreview = ((selection.customLightPct / 100.0) * 0.45 +
            ((selection.customTempC + 15.0) / 57.0) * 0.30 +
            ((selection.customTrendHpa + 6.0) / 12.0) * 0.25)
        .clamp(0.12, 0.96);
    final double valencePreview = ((selection.customLightPct / 100.0) * 0.50 +
            (1.0 - (selection.customColorKelvin - 2000.0) / 8000.0) * 0.30 +
            ((selection.customPressureHpa - 975.0) / 65.0) * 0.20)
        .clamp(0.15, 0.95);
    final double warmthPreview =
        (1.0 - ((selection.customColorKelvin - 2000.0) / 8000.0) * 0.75)
            .clamp(0.15, 0.98);

    return Container(
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BgSpace.br,
        border: Border.all(
          color: mode == 'guided'
              ? colors.outlineVariant
              : skyColor.withValues(alpha: 0.65),
          width: mode == 'guided' ? 1.0 : 1.5,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // Top Header & 3-Way Mode Switcher (Guided / Easy / Expert)
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: BgSpace.lg,
              vertical: BgSpace.md,
            ),
            decoration: BoxDecoration(
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(BgSpace.radius - 1),
              ),
              gradient: LinearGradient(
                colors: <Color>[
                  skyColor.withValues(alpha: 0.18 * brightnessFactor),
                  colors.surface,
                ],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
            ),
            child: Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: BgSpace.md,
              runSpacing: BgSpace.sm,
              children: <Widget>[
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Icon(
                      mode == 'guided'
                          ? Icons.wb_twilight_rounded
                          : mode == 'easy'
                              ? Icons.tune_rounded
                              : Icons.science_rounded,
                      size: 20,
                      color: mode == 'guided' ? colors.primary : skyColor,
                    ),
                    const SizedBox(width: BgSpace.sm),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(
                          'ATMOSPHERIC SYNTHESIS CONSOLE',
                          style: text.labelSmall?.copyWith(
                            color: colors.primary,
                            letterSpacing: 1.1,
                          ),
                        ),
                        Text(
                          mode == 'guided'
                              ? 'Guided Happy Path • Live Solar & Barometric Sync'
                              : mode == 'easy'
                                  ? 'Adjustable Studio • Temp, Color Spectrum & Light Cursors'
                                  : 'Expert Meteorological Deck • Full Derivative & BPM Lock',
                          style: text.bodySmall,
                        ),
                      ],
                    ),
                  ],
                ),
                // 3-Way Segmented Mode Toggle
                Container(
                  padding: const EdgeInsets.all(3),
                  decoration: BoxDecoration(
                    color: colors.surfaceContainerHigh,
                    borderRadius: BgSpace.brSm,
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      _ModePillButton(
                        label: 'Guided (Happy Path)',
                        icon: Icons.auto_awesome_rounded,
                        selected: mode == 'guided',
                        onTap: () {
                          HapticFeedback.selectionClick();
                          notifier.setConsoleMode('guided');
                        },
                      ),
                      _ModePillButton(
                        label: 'Easy Cursors',
                        icon: Icons.wb_sunny_outlined,
                        selected: mode == 'easy',
                        onTap: () {
                          HapticFeedback.selectionClick();
                          notifier.setConsoleMode('easy');
                        },
                      ),
                      _ModePillButton(
                        label: 'Expert',
                        icon: Icons.equalizer_rounded,
                        selected: mode == 'expert',
                        onTap: () {
                          HapticFeedback.selectionClick();
                          notifier.setConsoleMode('expert');
                        },
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),

          const Divider(height: 1),

          // BODY CONTENT BY MODE
          Padding(
            padding: const EdgeInsets.all(BgSpace.lg),
            child: mode == 'guided'
                ? _buildGuidedBody(context, selection, notifier)
                : _buildAdjustableBody(
                    context,
                    selection: selection,
                    notifier: notifier,
                    isExpert: mode == 'expert',
                    skyColor: skyColor,
                    brightnessFactor: brightnessFactor,
                    energyPreview: energyPreview,
                    valencePreview: valencePreview,
                    warmthPreview: warmthPreview,
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildGuidedBody(
    BuildContext context,
    ForgeSelection selection,
    ForgeSelectionNotifier notifier,
  ) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Row(
      children: <Widget>[
        Expanded(
          child: Wrap(
            spacing: BgSpace.lg,
            runSpacing: BgSpace.sm,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: <Widget>[
              _TelemetryBadge(
                icon: Icons.schedule_rounded,
                label: 'SOLAR CHRONOLOGY',
                value: 'Live Local Horizon Sync',
              ),
              _TelemetryBadge(
                icon: Icons.thermostat_rounded,
                label: 'ATMOSPHERE',
                value: '${selection.label} Weathercaster',
              ),
              _TelemetryBadge(
                icon: Icons.speed_rounded,
                label: 'BAROMETER',
                value: '6h Derivative Active',
              ),
            ],
          ),
        ),
        const SizedBox(width: BgSpace.md),
        OutlinedButton.icon(
          onPressed: () => notifier.setConsoleMode('easy'),
          icon: const Icon(Icons.tune_rounded, size: 16),
          label: const Text('Adjust Temp / Light / Color'),
        ),
      ],
    );
  }

  Widget _buildAdjustableBody(
    BuildContext context, {
    required ForgeSelection selection,
    required ForgeSelectionNotifier notifier,
    required bool isExpert,
    required Color skyColor,
    required double brightnessFactor,
    required double energyPreview,
    required double valencePreview,
    required double warmthPreview,
  }) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        // Live Atmospheric Sky Preview Strip
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(
            horizontal: BgSpace.lg,
            vertical: BgSpace.md,
          ),
          decoration: BoxDecoration(
            borderRadius: BgSpace.brSm,
            gradient: LinearGradient(
              colors: <Color>[
                skyColor.withValues(alpha: 0.75 * brightnessFactor),
                Color.lerp(skyColor, const Color(0xFF0F172A), 1.0 - brightnessFactor * 0.85)!,
              ],
              begin: Alignment.centerLeft,
              end: Alignment.centerRight,
            ),
            border: Border.all(
              color: skyColor.withValues(alpha: 0.5),
            ),
          ),
          child: Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: BgSpace.md,
            runSpacing: BgSpace.xs,
            children: <Widget>[
              Row(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Icon(
                    selection.customLightPct < 25
                        ? Icons.nights_stay_rounded
                        : selection.customLightPct > 75
                            ? Icons.wb_sunny_rounded
                            : Icons.wb_twilight_rounded,
                    color: Colors.white,
                    size: 20,
                  ),
                  const SizedBox(width: BgSpace.sm),
                  Text(
                    '${_lightPhaseLabel(selection.customLightPct)} • '
                    '${selection.customTempC.toStringAsFixed(1)}°C • '
                    '${_kelvinLabel(selection.customColorKelvin)}',
                    style: text.labelLarge?.copyWith(
                      color: Colors.white,
                      shadows: const <Shadow>[
                        Shadow(color: Colors.black54, blurRadius: 4),
                      ],
                    ),
                  ),
                ],
              ),
              if (widget.onTriggerForge != null)
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: Colors.white.withValues(alpha: 0.92),
                    foregroundColor: const Color(0xFF0F172A),
                    padding: const EdgeInsets.symmetric(
                      horizontal: BgSpace.md,
                      vertical: BgSpace.xs,
                    ),
                  ),
                  onPressed: widget.onTriggerForge,
                  icon: const Icon(Icons.bolt_rounded, size: 16),
                  label: const Text('Forge with Cursors'),
                ),
            ],
          ),
        ),

        const SizedBox(height: BgSpace.lg),

        // PRIMARY 3 CURSORS (Temp, Sky Color Spectrum, Solar Light)
        LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
            final bool threeCol = constraints.maxWidth >= 780;
            final List<Widget> primarySliders = <Widget>[
              _CursorSliderCard(
                icon: Icons.thermostat_rounded,
                title: 'TEMPERATURE CURSOR',
                valueLabel: '${selection.customTempC >= 0 ? "+" : ""}${selection.customTempC.toStringAsFixed(1)} °C',
                subtitle: selection.customTempC < 5
                    ? 'Crisp sub-zero / raw acoustic edge'
                    : selection.customTempC > 26
                        ? 'Tropical heat / sun-drenched groove'
                        : 'Temperate atmospheric balance',
                value: selection.customTempC,
                min: -15.0,
                max: 42.0,
                accentColor: selection.customTempC < 8
                    ? const Color(0xFF38BDF8)
                    : selection.customTempC > 24
                        ? const Color(0xFFF97316)
                        : colors.primary,
                onChanged: (double v) =>
                    notifier.setAtmosphericCursors(tempC: v),
              ),
              _CursorSliderCard(
                icon: Icons.palette_outlined,
                title: 'SKY COLOR SPECTRUM',
                valueLabel: '${selection.customColorKelvin.round()} K',
                subtitle: _kelvinLabel(selection.customColorKelvin),
                value: selection.customColorKelvin,
                min: 2000.0,
                max: 10000.0,
                accentColor: skyColor,
                onChanged: (double v) =>
                    notifier.setAtmosphericCursors(colorKelvin: v),
              ),
              _CursorSliderCard(
                icon: Icons.light_mode_rounded,
                title: 'SOLAR LIGHT / TIME OF DAY',
                valueLabel: '${selection.customLightPct.round()}% Luminance',
                subtitle: _lightPhaseLabel(selection.customLightPct),
                value: selection.customLightPct,
                min: 0.0,
                max: 100.0,
                accentColor: const Color(0xFFFACC15),
                onChanged: (double v) =>
                    notifier.setAtmosphericCursors(lightPct: v),
              ),
            ];

            if (threeCol) {
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Expanded(child: primarySliders[0]),
                  const SizedBox(width: BgSpace.md),
                  Expanded(child: primarySliders[1]),
                  const SizedBox(width: BgSpace.md),
                  Expanded(child: primarySliders[2]),
                ],
              );
            }
            return Column(
              children: <Widget>[
                primarySliders[0],
                const SizedBox(height: BgSpace.sm),
                primarySliders[1],
                const SizedBox(height: BgSpace.sm),
                primarySliders[2],
              ],
            );
          },
        ),

        // EXPERT MODE: Barometric Pressure, 6h Derivative, Target BPM + Sonic Vector Preview
        if (isExpert) ...<Widget>[
          const SizedBox(height: BgSpace.md),
          const Divider(),
          const SizedBox(height: BgSpace.md),
          Text(
            'EXPERT METEOROLOGICAL & SONIC OVERRIDES',
            style: text.labelSmall?.copyWith(color: colors.secondary),
          ),
          const SizedBox(height: BgSpace.sm),
          LayoutBuilder(
            builder: (BuildContext context, BoxConstraints constraints) {
              final bool threeCol = constraints.maxWidth >= 780;
              final List<Widget> expertSliders = <Widget>[
                _CursorSliderCard(
                  icon: Icons.speed_rounded,
                  title: 'BAROMETRIC PRESSURE',
                  valueLabel: '${selection.customPressureHpa.toStringAsFixed(0)} hPa',
                  subtitle: selection.customPressureHpa < 1000
                      ? 'Deep Cyclonic Low (Moody / Dub / Trip-Hop)'
                      : selection.customPressureHpa > 1022
                          ? 'High Anticyclonic Ridge (Crisp / Upbeat)'
                          : 'Standard Sea-Level Isobar',
                  value: selection.customPressureHpa,
                  min: 975.0,
                  max: 1040.0,
                  accentColor: colors.primary,
                  onChanged: (double v) =>
                      notifier.setAtmosphericCursors(pressureHpa: v),
                ),
                _CursorSliderCard(
                  icon: Icons.trending_down_rounded,
                  title: '6-HOUR PRESSURE DERIVATIVE',
                  valueLabel:
                      '${selection.customTrendHpa >= 0 ? "+" : ""}${selection.customTrendHpa.toStringAsFixed(1)} hPa/6h',
                  subtitle: selection.customTrendHpa < -1.5
                      ? 'Falling Front — High Emotional Tension'
                      : selection.customTrendHpa > 1.5
                          ? 'Clearing Ridge — Expansive Release'
                          : 'Steady Barograph Trace',
                  value: selection.customTrendHpa,
                  min: -6.0,
                  max: 6.0,
                  accentColor: selection.customTrendHpa < 0
                      ? const Color(0xFFF43F5E)
                      : const Color(0xFF10B981),
                  onChanged: (double v) =>
                      notifier.setAtmosphericCursors(trendHpa: v),
                ),
                _CursorSliderCard(
                  icon: Icons.graphic_eq_rounded,
                  title: 'TARGET TEMPO LOCK (BPM)',
                  valueLabel: '${selection.customTargetBpm.round()} BPM',
                  subtitle: selection.customTargetBpm < 90
                      ? 'Downtempo / Ambient Dub Pulse'
                      : selection.customTargetBpm > 128
                          ? 'Driving Club / Breakbeat Velocity'
                          : 'Mid-Tempo Headnod Groove',
                  value: selection.customTargetBpm,
                  min: 60.0,
                  max: 165.0,
                  accentColor: colors.secondary,
                  onChanged: (double v) =>
                      notifier.setAtmosphericCursors(targetBpm: v),
                ),
              ];

              if (threeCol) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Expanded(child: expertSliders[0]),
                    const SizedBox(width: BgSpace.md),
                    Expanded(child: expertSliders[1]),
                    const SizedBox(width: BgSpace.md),
                    Expanded(child: expertSliders[2]),
                  ],
                );
              }
              return Column(
                children: <Widget>[
                  expertSliders[0],
                  const SizedBox(height: BgSpace.sm),
                  expertSliders[1],
                  const SizedBox(height: BgSpace.sm),
                  expertSliders[2],
                ],
              );
            },
          ),
          const SizedBox(height: BgSpace.md),
          // Real-Time Sonic Vector Target Preview Bar
          Container(
            padding: const EdgeInsets.all(BgSpace.md),
            decoration: BoxDecoration(
              color: colors.surfaceContainerLow,
              borderRadius: BgSpace.brSm,
              border: Border.all(color: colors.outlineVariant),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: <Widget>[
                    Text(
                      'REAL-TIME SONIC TRANSFER MATRIX PREVIEW',
                      style: text.labelSmall,
                    ),
                    Text(
                      'Target: ${selection.customTargetBpm.round()} BPM • '
                      '${(energyPreview * 100).round()}% Energy • '
                      '${(warmthPreview * 100).round()}% Analog Warmth',
                      style: text.bodySmall?.copyWith(
                        color: colors.primary,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: BgSpace.sm),
                Row(
                  children: <Widget>[
                    Expanded(
                      child: _MiniVectorBar(
                        label: 'ENERGY',
                        value: energyPreview,
                        color: const Color(0xFFF97316),
                      ),
                    ),
                    const SizedBox(width: BgSpace.md),
                    Expanded(
                      child: _MiniVectorBar(
                        label: 'VALENCE (MOOD)',
                        value: valencePreview,
                        color: const Color(0xFF0EA5E9),
                      ),
                    ),
                    const SizedBox(width: BgSpace.md),
                    Expanded(
                      child: _MiniVectorBar(
                        label: 'ANALOG WARMTH',
                        value: warmthPreview,
                        color: const Color(0xFFF59E0B),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}

class _ModePillButton extends StatelessWidget {
  const _ModePillButton({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return InkWell(
      onTap: onTap,
      borderRadius: BgSpace.brSm,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: BgSpace.md,
          vertical: 6,
        ),
        decoration: BoxDecoration(
          color: selected ? colors.primary : Colors.transparent,
          borderRadius: BgSpace.brSm,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(
              icon,
              size: 15,
              color: selected ? colors.onPrimary : colors.onSurfaceVariant,
            ),
            const SizedBox(width: 6),
            Text(
              label,
              style: text.labelLarge?.copyWith(
                fontSize: 12.5,
                color: selected ? colors.onPrimary : colors.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TelemetryBadge extends StatelessWidget {
  const _TelemetryBadge({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Icon(icon, size: 18, color: colors.primary),
        const SizedBox(width: 6),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(label, style: text.labelSmall?.copyWith(fontSize: 10)),
            Text(value, style: text.titleSmall),
          ],
        ),
      ],
    );
  }
}

class _CursorSliderCard extends StatelessWidget {
  const _CursorSliderCard({
    required this.icon,
    required this.title,
    required this.valueLabel,
    required this.subtitle,
    required this.value,
    required this.min,
    required this.max,
    required this.accentColor,
    required this.onChanged,
  });

  final IconData icon;
  final String title;
  final String valueLabel;
  final String subtitle;
  final double value;
  final double min;
  final double max;
  final Color accentColor;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: <Widget>[
              Row(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Icon(icon, size: 16, color: accentColor),
                  const SizedBox(width: 6),
                  Text(title, style: text.labelSmall),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: accentColor.withValues(alpha: 0.15),
                  borderRadius: BgSpace.brSm,
                ),
                child: Text(
                  valueLabel,
                  style: text.labelLarge?.copyWith(
                    color: accentColor,
                    fontSize: 12.5,
                  ),
                ),
              ),
            ],
          ),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: accentColor,
              thumbColor: accentColor,
              overlayColor: accentColor.withValues(alpha: 0.15),
              trackHeight: 4.0,
            ),
            child: Slider(
              value: value.clamp(min, max),
              min: min,
              max: max,
              onChanged: onChanged,
            ),
          ),
          Text(
            subtitle,
            style: text.bodySmall?.copyWith(fontSize: 11.5),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}

class _MiniVectorBar extends StatelessWidget {
  const _MiniVectorBar({
    required this.label,
    required this.value,
    required this.color,
  });

  final String label;
  final double value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: <Widget>[
            Text(label, style: text.labelSmall?.copyWith(fontSize: 10)),
            Text(
              '${(value * 100).round()}%',
              style: text.labelSmall?.copyWith(color: color),
            ),
          ],
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: LinearProgressIndicator(
            value: value.clamp(0.0, 1.0),
            minHeight: 6,
            color: color,
            backgroundColor: color.withValues(alpha: 0.15),
          ),
        ),
      ],
    );
  }
}
