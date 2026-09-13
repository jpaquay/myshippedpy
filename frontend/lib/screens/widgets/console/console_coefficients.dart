import 'package:flutter/material.dart';

import '../../../app_theme.dart';
import '../../../providers.dart';

/// The client-side preview of the sonic target, and the weights that produce
/// it.
///
/// These are the same three numbers the console has always previewed; item 8
/// only moves them behind the `COEFFICIENTS` rung (§5.2) and finally states the
/// weights instead of drawing three unexplained bars. They are a *preview*: the
/// backend recomputes the real sonic vector. The header says so, because a
/// number with no provenance in an instrument panel is a lie.
class SonicPreview {
  const SonicPreview({
    required this.energy,
    required this.valence,
    required this.warmth,
  });

  final double energy;
  final double valence;
  final double warmth;

  factory SonicPreview.of(ForgeSelection s) {
    final double light = s.customLightPct / 100.0;
    final double temp = (s.customTempC + 15.0) / 57.0;
    final double trend = (s.customTrendHpa + 6.0) / 12.0;
    final double kelvin = (s.customColorKelvin - 2000.0) / 8000.0;
    final double pressure = (s.customPressureHpa - 975.0) / 65.0;
    return SonicPreview(
      energy: (light * 0.45 + temp * 0.30 + trend * 0.25).clamp(0.12, 0.96),
      valence: (light * 0.50 + (1.0 - kelvin) * 0.30 + pressure * 0.20)
          .clamp(0.15, 0.95),
      warmth: (1.0 - kelvin * 0.75).clamp(0.15, 0.98),
    );
  }
}

/// Rung-1 body for `COEFFICIENTS`: the mapping weight table plus the resulting
/// preview bars.
class ConsoleCoefficientsTable extends StatelessWidget {
  const ConsoleCoefficientsTable({required this.selection, super.key});

  final ForgeSelection selection;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final SonicPreview preview = SonicPreview.of(selection);

    const List<(String, String, double)> weights = <(String, String, double)>[
      ('Energy', 'light', 0.45),
      ('Energy', 'temperature', 0.30),
      ('Energy', 'pressure trend', 0.25),
      ('Valence', 'light', 0.50),
      ('Valence', 'colour (inverted)', 0.30),
      ('Valence', 'pressure', 0.20),
      ('Warmth', 'colour (inverted)', 0.75),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(
          'Client-side preview of the sonic target. The backend recomputes it '
          'from the live sky when you forge.',
          style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
        ),
        const SizedBox(height: BgSpace.md),
        for (final (String target, String input, double weight) in weights)
          Padding(
            padding: const EdgeInsets.only(bottom: BgSpace.xs),
            child: Row(
              children: <Widget>[
                SizedBox(
                  width: 72,
                  child: Text(target, style: text.labelMedium),
                ),
                Expanded(
                  child: Text(
                    input,
                    style: text.bodySmall,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Text(
                  weight.toStringAsFixed(2),
                  style: text.labelMedium?.copyWith(color: colors.primary),
                ),
              ],
            ),
          ),
        const SizedBox(height: BgSpace.md),
        _PreviewBar(label: 'ENERGY', value: preview.energy),
        const SizedBox(height: BgSpace.sm),
        _PreviewBar(label: 'VALENCE', value: preview.valence),
        const SizedBox(height: BgSpace.sm),
        _PreviewBar(label: 'WARMTH', value: preview.warmth),
      ],
    );
  }
}

class _PreviewBar extends StatelessWidget {
  const _PreviewBar({required this.label, required this.value});

  final String label;
  final double value;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Row(
      children: <Widget>[
        SizedBox(
          width: 72,
          child: Text(label, style: text.labelSmall),
        ),
        Expanded(
          child: ClipRRect(
            borderRadius: BgSpace.brSm,
            child: LinearProgressIndicator(
              value: value,
              minHeight: 6,
              backgroundColor: colors.surfaceContainerHighest,
              valueColor: AlwaysStoppedAnimation<Color>(colors.primary),
            ),
          ),
        ),
        const SizedBox(width: BgSpace.sm),
        Text('${(value * 100).round()}%', style: text.labelMedium),
      ],
    );
  }
}
