import 'package:flutter/material.dart';

import '../../../app_theme.dart';

/// One labelled cursor: eyebrow + current value + slider + one-line meaning.
///
/// Lifted verbatim out of `atmospheric_cursors_console.dart` (it was
/// `_CursorSliderCard`) so the console file can be about the mode ladder and
/// nothing else. Behaviour is unchanged.
class ConsoleCursorSlider extends StatelessWidget {
  const ConsoleCursorSlider({
    required this.icon,
    required this.title,
    required this.valueLabel,
    required this.subtitle,
    required this.value,
    required this.min,
    required this.max,
    required this.accentColor,
    required this.onChanged,
    super.key,
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
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: <Widget>[
              Flexible(
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Icon(icon, size: 16, color: accentColor),
                    const SizedBox(width: BgSpace.xs),
                    Flexible(
                      child: Text(
                        title,
                        style: text.labelSmall,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: BgSpace.sm,
                  vertical: 2,
                ),
                decoration: BoxDecoration(
                  color: accentColor.withValues(alpha: 0.15),
                  borderRadius: BgSpace.brSm,
                ),
                child: Text(
                  valueLabel,
                  style: text.labelMedium?.copyWith(color: accentColor),
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
            style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}
