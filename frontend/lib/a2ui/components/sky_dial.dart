/// SkyDial — the instrument.
///
/// ## The thesis, and why this widget is shaped the way it is
///
/// BAROGROOVE's claim is not "it is 14°C so here is chill music". Anyone can
/// read a thermometer. The claim is that the *derivative* is what you feel:
/// a barometer falling three millibars in six hours is a different afternoon
/// from a barometer sitting flat at the same reading. Pressure trend is the
/// product. Everything else is supporting evidence.
///
/// So this widget does not draw nine equal spokes. It draws:
///
///   * `pressure_trend_6h` as the hero — a large signed arc, centred, with
///     the numeral set at display size and a plain-language reading. It gets
///     roughly half the visual weight of the component.
///   * The other two signed, normalised-deviation dims
///     (`pressure_norm_deviation`, `temp_norm_deviation`) as a secondary pair
///     of bipolar bars, because "unusual for here, for now" is the second-
///     order story.
///   * The remaining six magnitude dims as a quiet strip of unipolar meters.
///     Present, readable, subordinate.
///
/// A radar chart would have been easier and would have said the opposite
/// thing: that all nine dimensions matter equally. They do not.
///
/// ## Data
///
/// Bound to a SkyVector object in the data model, e.g.
/// `{"vector": {"path": "/sky"}}`. Signed dims are [-1, 1]; magnitude dims
/// are [0, 1]. Also reads `observed_at`, `stale` and `notes[]` from the same
/// object, because a stale reading that pretends to be live is a lie the
/// user cannot detect.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../app_theme.dart';
import '../catalog.dart';
import '../messages.dart';

/// The nine SkyVector dimensions, in the order the contract defines them.
enum SkyDim {
  pressureTrend6h('pressure_trend_6h', 'Pressure trend', '6 h', signed: true),
  pressureNormDeviation(
      'pressure_norm_deviation', 'Pressure vs normal', 'σ', signed: true),
  tempNormDeviation(
      'temp_norm_deviation', 'Temperature vs normal', 'σ', signed: true),
  sunElevation('sun_elevation', 'Sun elevation', '', signed: false),
  goldenHourProximity(
      'golden_hour_proximity', 'Golden hour', '', signed: false),
  gustVariance('gust_variance', 'Gust variance', '', signed: false),
  cloudDepth('cloud_depth', 'Cloud depth', '', signed: false),
  precipIntensity('precip_intensity', 'Precipitation', '', signed: false),
  daylightDelta('daylight_delta', 'Daylight delta', '', signed: true);

  const SkyDim(this.key, this.label, this.unit, {required this.signed});

  final String key;
  final String label;
  final String unit;

  /// Signed dims live in [-1, 1] and are drawn bipolar from a centre line.
  /// Magnitude dims live in [0, 1] and are drawn as a fill from the left.
  final bool signed;
}

class SkyDialComponent extends StatelessWidget {
  const SkyDialComponent({required this.node, super.key});

  final A2uiNode node;

  @override
  Widget build(BuildContext context) {
    // The server binds one object; we read the nine floats out of it. Reading
    // a whole object rather than nine separate bindings keeps the wire
    // payload sane and means one updateDataModel on /sky refreshes the dial.
    final JsonMap? vector = node.map('vector') ?? node.map('sky');
    if (vector == null) {
      return A2uiPlaceholder.binding(
        componentId: node.id,
        detail: 'no SkyVector bound to "vector"',
      );
    }

    double dim(SkyDim d) =>
        (asDoubleOrNull(vector[d.key]) ?? 0).clamp(d.signed ? -1.0 : 0.0, 1.0);

    final bool stale = asBoolOrNull(vector['stale']) ?? false;
    final String? observedAt = asStringOrNull(vector['observed_at']);
    final List<String> notes = asStringList(vector['notes']);

    final ColorScheme colors = node.colors;
    final TextTheme text = node.text;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(BgSpace.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Expanded(
                  child: Text(
                    node.stringOr('title', 'SKY READING'),
                    style: text.labelSmall,
                  ),
                ),
                if (stale) const _StaleBadge(),
              ],
            ),
            const SizedBox(height: BgSpace.lg),

            // --- HERO: the derivative -------------------------------------
            _PressureTrendHero(
              value: dim(SkyDim.pressureTrend6h),
              observedAt: observedAt,
            ),

            const SizedBox(height: BgSpace.xl),
            Divider(color: colors.outlineVariant),
            const SizedBox(height: BgSpace.lg),

            // --- SECONDARY: the two normalised deviations -----------------
            Text('DEVIATION FROM NORMAL', style: text.labelSmall),
            const SizedBox(height: BgSpace.md),
            _BipolarBar(
              label: SkyDim.pressureNormDeviation.label,
              value: dim(SkyDim.pressureNormDeviation),
              emphasis: 0.75,
            ),
            const SizedBox(height: BgSpace.md),
            _BipolarBar(
              label: SkyDim.tempNormDeviation.label,
              value: dim(SkyDim.tempNormDeviation),
              emphasis: 0.75,
            ),

            const SizedBox(height: BgSpace.xl),

            // --- TERTIARY: the magnitude strip ----------------------------
            Text('CONDITIONS', style: text.labelSmall),
            const SizedBox(height: BgSpace.md),
            LayoutBuilder(
              builder: (BuildContext context, BoxConstraints constraints) {
                // Two columns above 520 logical pixels; one below. The strip
                // is subordinate, so it may reflow freely.
                final int columns = constraints.maxWidth >= 520 ? 2 : 1;
                const List<SkyDim> magnitudes = <SkyDim>[
                  SkyDim.sunElevation,
                  SkyDim.goldenHourProximity,
                  SkyDim.gustVariance,
                  SkyDim.cloudDepth,
                  SkyDim.precipIntensity,
                  SkyDim.daylightDelta,
                ];
                final double itemWidth = columns == 1
                    ? constraints.maxWidth
                    : (constraints.maxWidth - BgSpace.xl) / 2;
                return Wrap(
                  spacing: BgSpace.xl,
                  runSpacing: BgSpace.md,
                  children: <Widget>[
                    for (final SkyDim d in magnitudes)
                      SizedBox(
                        width: itemWidth,
                        child: d.signed
                            ? _BipolarBar(
                                label: d.label,
                                value: dim(d),
                                emphasis: 0.45,
                              )
                            : _MagnitudeMeter(label: d.label, value: dim(d)),
                      ),
                  ],
                );
              },
            ),

            if (notes.isNotEmpty) ...<Widget>[
              const SizedBox(height: BgSpace.lg),
              Divider(color: colors.outlineVariant),
              const SizedBox(height: BgSpace.md),
              for (final String note in notes)
                Padding(
                  padding: const EdgeInsets.only(bottom: BgSpace.xs),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Padding(
                        padding: const EdgeInsets.only(top: 5, right: BgSpace.sm),
                        child: Container(
                          width: 3,
                          height: 3,
                          decoration: BoxDecoration(
                            color: colors.onSurfaceVariant,
                            shape: BoxShape.circle,
                          ),
                        ),
                      ),
                      Expanded(child: Text(note, style: text.bodySmall)),
                    ],
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

// ===========================================================================
// The hero
// ===========================================================================

/// `pressure_trend_6h`, drawn as a signed arc with the numeral inside.
///
/// The arc sweeps left of centre for falling and right for rising, over a
/// 240° span. Falling pressure gets the sky blue (weather coming in); rising
/// gets the gold (settling). Flat gets slate. Colour is doing semantic work
/// here, which is why it is the one place gold is allowed to be large.
class _PressureTrendHero extends StatelessWidget {
  const _PressureTrendHero({required this.value, this.observedAt});

  /// Normalised trend in [-1, 1]. Negative is falling.
  final double value;
  final String? observedAt;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final Color tone = _toneFor(value, colors);

    final bool narrow = MediaQuery.sizeOf(context).width < 460;
    final double dialSize = narrow ? 108 : 132;

    return Semantics(
      label: 'Six hour pressure trend, ${_reading(value)}, '
          '${value.toStringAsFixed(2)} normalised',
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: <Widget>[
          RepaintBoundary(
            child: SizedBox(
              width: dialSize,
              height: dialSize,
              child: CustomPaint(
                painter: _TrendArcPainter(
                  value: value,
                  track: colors.outlineVariant,
                  tone: tone,
                ),
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Icon(
                        value.abs() < 0.05
                            ? Icons.remove
                            : value < 0
                                ? Icons.south_east
                                : Icons.north_east,
                        size: narrow ? 18 : 20,
                        color: tone,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        _signed(value),
                        style: (narrow ? text.titleLarge : text.headlineMedium)
                            ?.copyWith(
                          color: tone,
                          fontFeatures: const <FontFeature>[
                            FontFeature.tabularFigures(),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          SizedBox(width: narrow ? BgSpace.md : BgSpace.xl),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text('PRESSURE TREND · 6 H', style: text.labelSmall),
                const SizedBox(height: BgSpace.xs),
                Text(_reading(value), style: text.headlineSmall),
                const SizedBox(height: BgSpace.sm),
                Text(
                  _gloss(value),
                  style: text.bodyMedium?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
                if (observedAt != null) ...<Widget>[
                  const SizedBox(height: BgSpace.sm),
                  Text('Observed $observedAt', style: text.bodySmall),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  static Color _toneFor(double v, ColorScheme colors) {
    if (v.abs() < 0.05) return BgPalette.slate500;
    return v < 0 ? colors.primary : BgPalette.gold600;
  }

  static String _signed(double v) {
    if (v == 0) return '0.00';
    return '${v > 0 ? '+' : '−'}${v.abs().toStringAsFixed(2)}';
  }

  /// Plain language, no adjectives we cannot defend.
  static String _reading(double v) {
    final double a = v.abs();
    if (a < 0.05) return 'Steady';
    final String direction = v < 0 ? 'Falling' : 'Rising';
    if (a < 0.25) return '$direction slowly';
    if (a < 0.6) return direction;
    return '$direction sharply';
  }

  static String _gloss(double v) {
    final double a = v.abs();
    if (a < 0.05) return 'Nothing is moving. The sky is not making an argument.';
    if (v < 0) {
      return a < 0.6
          ? 'Weather is on its way in. The set leans darker and wetter.'
          : 'A front is closing fast. Expect the set to get urgent.';
    }
    return a < 0.6
        ? 'The air is settling. The set opens out.'
        : 'Clearing hard. The set gets bright and wide.';
  }
}

/// Paints a 240° arc, filled from centre outward in the direction of the sign.
class _TrendArcPainter extends CustomPainter {
  const _TrendArcPainter({
    required this.value,
    required this.track,
    required this.tone,
  });

  final double value;
  final Color track;
  final Color tone;

  static const double _sweep = 240 * math.pi / 180;
  // Start at the bottom-left of the gap so the arc reads like a gauge.
  static const double _start = math.pi / 2 + (math.pi - _sweep / 2) * -1;

  @override
  void paint(Canvas canvas, Size size) {
    final Rect rect = Offset.zero & size;
    const double stroke = 10;
    final Rect arcRect = rect.deflate(stroke / 2 + 2);

    final Paint trackPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round
      ..color = track;

    canvas.drawArc(arcRect, _start, _sweep, false, trackPaint);

    // Centre tick: the zero line. Without it a filled arc is ambiguous.
    const double mid = _start + _sweep / 2;
    final Paint tickPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..color = track;
    final Offset centre = arcRect.center;
    final double r = arcRect.width / 2;
    canvas.drawLine(
      centre + Offset(math.cos(mid) * (r - stroke), math.sin(mid) * (r - stroke)),
      centre + Offset(math.cos(mid) * (r + stroke / 2), math.sin(mid) * (r + stroke / 2)),
      tickPaint,
    );

    if (value.abs() < 0.005) return;

    final Paint valuePaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round
      ..color = tone;

    const double half = _sweep / 2;
    final double magnitude = value.abs().clamp(0.0, 1.0) * half;
    if (value < 0) {
      canvas.drawArc(arcRect, mid - magnitude, magnitude, false, valuePaint);
    } else {
      canvas.drawArc(arcRect, mid, magnitude, false, valuePaint);
    }
  }

  @override
  bool shouldRepaint(_TrendArcPainter old) =>
      old.value != value || old.tone != tone || old.track != track;
}

// ===========================================================================
// Secondary and tertiary readouts
// ===========================================================================

/// A bipolar bar for a signed dimension: fills left or right of a centre rule.
class _BipolarBar extends StatelessWidget {
  const _BipolarBar({
    required this.label,
    required this.value,
    required this.emphasis,
  });

  final String label;
  final double value;

  /// 0..1 — scales the bar height so the visual hierarchy stays explicit.
  final double emphasis;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final double height = 6 + 4 * emphasis;
    final Color tone = value.abs() < 0.05
        ? BgPalette.slate400
        : value < 0
            ? colors.primary
            : BgPalette.gold600;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Row(
          children: <Widget>[
            Expanded(child: Text(label, style: text.bodySmall)),
            Text(
              value == 0
                  ? '0.00'
                  : '${value > 0 ? '+' : '−'}${value.abs().toStringAsFixed(2)}',
              style: text.bodySmall?.copyWith(
                color: colors.onSurface,
                fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
              ),
            ),
          ],
        ),
        const SizedBox(height: BgSpace.xs),
        LayoutBuilder(
          builder: (BuildContext context, BoxConstraints c) {
            final double half = c.maxWidth / 2;
            final double extent = half * value.abs().clamp(0.0, 1.0);
            return SizedBox(
              height: height,
              width: c.maxWidth,
              child: Stack(
                children: <Widget>[
                  Positioned.fill(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: colors.surfaceContainer,
                        borderRadius: BorderRadius.circular(height / 2),
                      ),
                    ),
                  ),
                  Positioned(
                    left: value < 0 ? half - extent : half,
                    width: math.max(extent, value.abs() < 0.005 ? 0 : 2),
                    top: 0,
                    bottom: 0,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: tone,
                        borderRadius: BorderRadius.circular(height / 2),
                      ),
                    ),
                  ),
                  Positioned(
                    left: half - 0.5,
                    top: -1,
                    bottom: -1,
                    width: 1,
                    child: ColoredBox(color: colors.outline),
                  ),
                ],
              ),
            );
          },
        ),
      ],
    );
  }
}

/// A unipolar meter for a magnitude dimension. Quiet by construction.
class _MagnitudeMeter extends StatelessWidget {
  const _MagnitudeMeter({required this.label, required this.value});

  final String label;
  final double value;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Semantics(
      label: '$label ${(value * 100).round()} percent',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(child: Text(label, style: text.bodySmall)),
              Text(
                '${(value * 100).round()}',
                style: text.bodySmall?.copyWith(
                  fontFeatures: const <FontFeature>[
                    FontFeature.tabularFigures(),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.xs),
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: value.clamp(0.0, 1.0),
              minHeight: 5,
              backgroundColor: colors.surfaceContainer,
              valueColor: const AlwaysStoppedAnimation<Color>(BgPalette.slate500),
            ),
          ),
        ],
      ),
    );
  }
}

/// Shown when the upstream observation is old. We say so rather than quietly
/// serving yesterday's sky.
class _StaleBadge extends StatelessWidget {
  const _StaleBadge();

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: 'The upstream observation is older than the freshness window. '
          'The forge still runs, but the reading may not match your window.',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: BgSpace.sm, vertical: 3),
        decoration: BoxDecoration(
          color: BgPalette.gold50,
          borderRadius: BgSpace.brSm,
          border: Border.all(color: BgPalette.gold300),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const Icon(Icons.schedule, size: 13, color: BgPalette.gold600),
            const SizedBox(width: 4),
            Text(
              'STALE',
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(color: BgPalette.gold600),
            ),
          ],
        ),
      ),
    );
  }
}
