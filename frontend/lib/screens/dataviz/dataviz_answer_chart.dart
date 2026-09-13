// Data Viz — the chart slot inside an answer card.
//
// Four geometries and no more, exactly the set the BigQuery Data QnA agent can
// synthesise (docs/BIGQUERY_DATA_QNA_AGENT.md): bar, horizontal_bar, donut,
// line. Fixed height so a card never reflows when an answer lands.
//
// Colour: the backend ships a `color_hex` per point (a categorical rainbow).
// It is deliberately ignored. UX_IA_SPEC.md §7.3 allows exactly one accent and
// rations gold, so every geometry here is a single-hue ramp of
// `colorScheme.primary`, ordered by rank. Magnitude is carried by length and
// position, which is what makes it readable at 390 px and in monochrome.

import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../app_theme.dart';
import 'dataviz_models.dart';

/// Chart height. §3.4 fixes 180 on mobile; expanded gets a little more room.
double answerChartHeight({required bool isExpanded}) => isExpanded ? 220 : 180;

const TextStyle _kNumeric = TextStyle(
  fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
);

/// Ramp a single accent across [count] ranks: strongest first.
Color _rampColor(ColorScheme colors, int index, int count) {
  if (count <= 1) return colors.primary;
  final double t = index / (count - 1);
  // 1.00 → 0.32 opacity. Below ~0.3 a bar stops being legible on slate50.
  return colors.primary.withValues(alpha: 1.0 - (0.68 * t));
}

class AnswerChart extends StatelessWidget {
  const AnswerChart({
    super.key,
    required this.spec,
    required this.isExpanded,
  });

  final QnaChartSpecModel spec;
  final bool isExpanded;

  @override
  Widget build(BuildContext context) {
    final double height = answerChartHeight(isExpanded: isExpanded);
    final ColorScheme colors = Theme.of(context).colorScheme;

    final Widget body;
    switch (spec.geometry) {
      case QnaChartGeometry.horizontalBar:
        body = _HorizontalBars(spec: spec);
      case QnaChartGeometry.donut:
        body = _Donut(spec: spec);
      case QnaChartGeometry.line:
        body = _LineChart(spec: spec);
      case QnaChartGeometry.bar:
        body = _VerticalBars(spec: spec);
    }

    return Semantics(
      label: spec.title.isEmpty ? 'Answer chart' : spec.title,
      child: Container(
        height: height,
        padding: const EdgeInsets.all(BgSpace.md),
        decoration: BoxDecoration(
          // §7.3 surfaceSunken — chart plot areas.
          color: colors.surfaceContainerHighest.withValues(alpha: 0.45),
          borderRadius: BgSpace.brSm,
        ),
        child: body,
      ),
    );
  }
}

/// The skeleton that occupies the chart slot while a turn is loading, so the
/// card does not jump when the real geometry arrives.
class AnswerChartSkeleton extends StatelessWidget {
  const AnswerChartSkeleton({super.key, required this.isExpanded});

  final bool isExpanded;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Container(
      height: answerChartHeight(isExpanded: isExpanded),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.45),
        borderRadius: BgSpace.brSm,
      ),
      padding: const EdgeInsets.all(BgSpace.md),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: List<Widget>.generate(7, (int i) {
          const List<double> f = <double>[0.35, 0.62, 0.48, 0.85, 0.55, 0.7, 0.4];
          return Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 3),
              child: FractionallySizedBox(
                heightFactor: f[i],
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: colors.outlineVariant.withValues(alpha: 0.55),
                    borderRadius: BgSpace.brSm,
                  ),
                ),
              ),
            ),
          );
        }),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// horizontal_bar — the default for ranked categories; best geometry at 390 px
// because the label gets a full line of its own width.
// ---------------------------------------------------------------------------

class _HorizontalBars extends StatelessWidget {
  const _HorizontalBars({required this.spec});

  final QnaChartSpecModel spec;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;
    final List<QnaChartPointModel> pts = spec.series.take(8).toList();
    final double max = pts.fold<double>(
        0, (double a, QnaChartPointModel p) => math.max(a, p.value));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        for (int i = 0; i < pts.length; i++)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 2),
              child: Row(
                children: <Widget>[
                  SizedBox(
                    width: 92,
                    child: Text(
                      _prettyLabel(pts[i].label),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.labelSmall
                          ?.copyWith(color: colors.onSurfaceVariant),
                    ),
                  ),
                  const SizedBox(width: BgSpace.sm),
                  Expanded(
                    child: LayoutBuilder(
                      builder: (BuildContext context, BoxConstraints c) {
                        final double w =
                            max <= 0 ? 0 : (pts[i].value / max) * c.maxWidth;
                        return Align(
                          alignment: Alignment.centerLeft,
                          child: Container(
                            height: 10,
                            width: w.clamp(2.0, c.maxWidth),
                            decoration: BoxDecoration(
                              color: _rampColor(colors, i, pts.length),
                              borderRadius: BgSpace.brSm,
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                  const SizedBox(width: BgSpace.sm),
                  Text(
                    _valueLabel(pts[i]),
                    style: theme.textTheme.labelSmall?.merge(_kNumeric),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// bar — for ordered series with many points (the 24-hour circadian answer).
// ---------------------------------------------------------------------------

class _VerticalBars extends StatelessWidget {
  const _VerticalBars({required this.spec});

  final QnaChartSpecModel spec;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;
    final List<QnaChartPointModel> pts = spec.series;
    final double max = pts.fold<double>(
        0, (double a, QnaChartPointModel p) => math.max(a, p.value));
    // At 390 px a 24-bar chart cannot label every bar. Label every nth so the
    // axis stays readable instead of turning into grey mush.
    final int step = pts.length <= 8 ? 1 : (pts.length / 6).ceil();

    return Column(
      children: <Widget>[
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: <Widget>[
              for (int i = 0; i < pts.length; i++)
                Expanded(
                  child: Padding(
                    padding: EdgeInsets.symmetric(
                        horizontal: pts.length > 12 ? 1 : 3),
                    child: Tooltip(
                      message: '${_prettyLabel(pts[i].label)} · '
                          '${_valueLabel(pts[i])}',
                      child: FractionallySizedBox(
                        heightFactor:
                            max <= 0 ? 0.02 : math.max(pts[i].value / max, 0.02),
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: _rampColor(colors, i, pts.length),
                            borderRadius: const BorderRadius.vertical(
                              top: Radius.circular(BgSpace.radiusSm),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: BgSpace.xs),
        Row(
          children: <Widget>[
            for (int i = 0; i < pts.length; i++)
              Expanded(
                child: Text(
                  i % step == 0 ? _prettyLabel(pts[i].label) : '',
                  textAlign: TextAlign.center,
                  maxLines: 1,
                  overflow: TextOverflow.clip,
                  style: theme.textTheme.labelSmall
                      ?.merge(_kNumeric)
                      .copyWith(color: colors.onSurfaceVariant, fontSize: 9),
                ),
              ),
          ],
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// donut — share-of-total. Ring plus an explicit legend: a ring alone is not
// readable without one.
// ---------------------------------------------------------------------------

class _Donut extends StatelessWidget {
  const _Donut({required this.spec});

  final QnaChartSpecModel spec;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;
    final List<QnaChartPointModel> pts = spec.series.take(6).toList();
    final double total = pts.fold<double>(
        0, (double a, QnaChartPointModel p) => a + p.value);
    final List<Color> ramp = <Color>[
      for (int i = 0; i < pts.length; i++) _rampColor(colors, i, pts.length),
    ];

    return Row(
      children: <Widget>[
        AspectRatio(
          aspectRatio: 1,
          child: CustomPaint(
            painter: _DonutPainter(
              values: pts.map((QnaChartPointModel p) => p.value).toList(),
              colors: ramp,
              track: colors.outlineVariant,
            ),
          ),
        ),
        const SizedBox(width: BgSpace.lg),
        Expanded(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              for (int i = 0; i < pts.length; i++)
                Padding(
                  padding: const EdgeInsets.only(bottom: 3),
                  child: Row(
                    children: <Widget>[
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          color: ramp[i],
                          borderRadius: BgSpace.brSm,
                        ),
                      ),
                      const SizedBox(width: BgSpace.sm),
                      Expanded(
                        child: Text(
                          _prettyLabel(pts[i].label),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.labelSmall,
                        ),
                      ),
                      Text(
                        total <= 0
                            ? '—'
                            : '${(pts[i].value / total * 100).toStringAsFixed(0)}%',
                        style: theme.textTheme.labelSmall
                            ?.merge(_kNumeric)
                            .copyWith(color: colors.onSurfaceVariant),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _DonutPainter extends CustomPainter {
  _DonutPainter({
    required this.values,
    required this.colors,
    required this.track,
  });

  final List<double> values;
  final List<Color> colors;
  final Color track;

  @override
  void paint(Canvas canvas, Size size) {
    final double total = values.fold<double>(0, (double a, double b) => a + b);
    final double r = math.min(size.width, size.height) / 2;
    final Rect rect = Rect.fromCircle(
      center: Offset(size.width / 2, size.height / 2),
      radius: r - 8,
    );
    final Paint p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 14;

    if (total <= 0) {
      canvas.drawArc(rect, 0, math.pi * 2, false, p..color = track);
      return;
    }

    double start = -math.pi / 2;
    for (int i = 0; i < values.length; i++) {
      final double sweep = (values[i] / total) * math.pi * 2;
      canvas.drawArc(rect, start, sweep - 0.02, false, p..color = colors[i]);
      start += sweep;
    }
  }

  @override
  bool shouldRepaint(covariant _DonutPainter old) =>
      old.values != values || old.colors != colors;
}

// ---------------------------------------------------------------------------
// line — trends over an ordered axis.
// ---------------------------------------------------------------------------

class _LineChart extends StatelessWidget {
  const _LineChart({required this.spec});

  final QnaChartSpecModel spec;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;
    final List<QnaChartPointModel> pts = spec.series;

    return Column(
      children: <Widget>[
        Expanded(
          child: CustomPaint(
            size: Size.infinite,
            painter: _LinePainter(
              values: pts.map((QnaChartPointModel p) => p.value).toList(),
              stroke: colors.primary,
              fill: colors.primary.withValues(alpha: 0.12),
              grid: colors.outlineVariant,
            ),
          ),
        ),
        const SizedBox(height: BgSpace.xs),
        if (pts.isNotEmpty)
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: <Widget>[
              Text(
                _prettyLabel(pts.first.label),
                style: theme.textTheme.labelSmall
                    ?.merge(_kNumeric)
                    .copyWith(color: colors.onSurfaceVariant),
              ),
              Text(
                _prettyLabel(pts.last.label),
                style: theme.textTheme.labelSmall
                    ?.merge(_kNumeric)
                    .copyWith(color: colors.onSurfaceVariant),
              ),
            ],
          ),
      ],
    );
  }
}

class _LinePainter extends CustomPainter {
  _LinePainter({
    required this.values,
    required this.stroke,
    required this.fill,
    required this.grid,
  });

  final List<double> values;
  final Color stroke;
  final Color fill;
  final Color grid;

  @override
  void paint(Canvas canvas, Size size) {
    final Paint gridPaint = Paint()
      ..color = grid
      ..strokeWidth = 1;
    for (int i = 0; i <= 2; i++) {
      final double y = size.height * (i / 2);
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }
    if (values.length < 2) return;

    final double maxV = values.reduce(math.max);
    final double minV = values.reduce(math.min);
    final double span = (maxV - minV).abs() < 1e-9 ? 1.0 : maxV - minV;

    final Path line = Path();
    for (int i = 0; i < values.length; i++) {
      final double x = size.width * (i / (values.length - 1));
      final double y =
          size.height - ((values[i] - minV) / span) * (size.height - 6) - 3;
      if (i == 0) {
        line.moveTo(x, y);
      } else {
        line.lineTo(x, y);
      }
    }

    final Path area = Path.from(line)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawPath(area, Paint()..color = fill);
    canvas.drawPath(
      line,
      Paint()
        ..color = stroke
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..strokeJoin = StrokeJoin.round,
    );
  }

  @override
  bool shouldRepaint(covariant _LinePainter old) => old.values != values;
}

// ---------------------------------------------------------------------------

/// `warm_front_haze` → `Warm front haze`. BigQuery group-by keys are snake_case
/// and unreadable in a legend.
String _prettyLabel(String raw) {
  if (raw.isEmpty) return raw;
  if (!raw.contains('_')) return raw;
  final String spaced = raw.replaceAll('_', ' ');
  return spaced[0].toUpperCase() + spaced.substring(1);
}

String _valueLabel(QnaChartPointModel p) {
  if (p.extraLabel.isNotEmpty) return p.extraLabel;
  if (p.value == p.value.roundToDouble()) return p.value.toInt().toString();
  return p.value.toStringAsFixed(1);
}
