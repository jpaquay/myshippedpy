/// RationaleCard — the hero.
///
/// ## Why this card is the largest thing on the page
///
/// A recommender that cannot explain itself is a slot machine. BAROGROOVE's
/// entire defensible position is that it can say, in sentences, why the sky
/// produced this set — which readings it took, which sonic moves it made in
/// response, what it knows about your taste, and how confident it is. That is
/// not a footnote under the tracklist. It is the product, and it is laid out
/// like one: a wide card, a display-size headline, generous body copy, and
/// two explicit evidence columns.
///
/// The confidence figure and the `degraded[]` list are given the same
/// prominence as the good news. An explanation that omits its own caveats is
/// marketing. If Last.fm was unavailable and the taste signal is therefore
/// absent, this card says so on its face.
///
/// Data: bound to a Rationale object —
/// `{headline, body, sky_reading[], sonic_moves[], taste_note, confidence,
///   degraded[]}`.
library;

import 'package:flutter/material.dart';

import '../../app_theme.dart';
import '../catalog.dart';
import '../messages.dart';

class RationaleCardComponent extends StatelessWidget {
  const RationaleCardComponent({required this.node, super.key});

  final A2uiNode node;

  @override
  Widget build(BuildContext context) {
    final JsonMap? r = node.map('rationale') ?? node.map('value');
    if (r == null) {
      return A2uiPlaceholder.binding(
        componentId: node.id,
        detail: 'no Rationale bound to "rationale"',
      );
    }

    final String headline = asStringOrNull(r['headline']) ?? 'No reading';
    final String body = asStringOrNull(r['body']) ?? '';
    final List<String> skyReading = asStringList(r['sky_reading']);
    final List<String> sonicMoves = asStringList(r['sonic_moves']);
    final String? tasteNote = asStringOrNull(r['taste_note']);
    final double? confidence = asDoubleOrNull(r['confidence']);
    final List<String> degraded = asStringList(r['degraded']);

    final ColorScheme colors = node.colors;
    final TextTheme text = node.text;

    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          // A gold rule across the top. The one place in the app where the
          // accent runs the full width — this card has earned it.
          Container(height: 3, color: BgPalette.gold500),
          Padding(
            padding: const EdgeInsets.all(BgSpace.xxl),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Expanded(
                      child: Text('WHY THIS SET', style: text.labelSmall),
                    ),
                    if (confidence != null)
                      _ConfidenceMeter(value: confidence.clamp(0.0, 1.0)),
                  ],
                ),
                const SizedBox(height: BgSpace.md),

                // The headline. Display size, tight tracking, no quotation
                // marks — it is a statement, not a pull-quote.
                Text(headline, style: text.displaySmall),

                if (body.isNotEmpty) ...<Widget>[
                  const SizedBox(height: BgSpace.lg),
                  // Measure is capped: long-form copy at full desktop width
                  // is unreadable, and this is the copy we most want read.
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 640),
                    child: Text(body, style: text.bodyLarge),
                  ),
                ],

                const SizedBox(height: BgSpace.xl),
                Divider(color: colors.outlineVariant),
                const SizedBox(height: BgSpace.xl),

                // Two evidence columns: what was read, and what was done
                // about it. Side by side above 680px, stacked below.
                LayoutBuilder(
                  builder: (BuildContext context, BoxConstraints c) {
                    final Widget left = _EvidenceColumn(
                      eyebrow: 'SKY READING',
                      accent: colors.primary,
                      items: skyReading,
                      emptyNote: 'No individual readings were reported.',
                    );
                    final Widget right = _EvidenceColumn(
                      eyebrow: 'SONIC MOVES',
                      accent: BgPalette.gold600,
                      items: sonicMoves,
                      emptyNote: 'No explicit adjustments were made.',
                    );
                    if (c.maxWidth < 680) {
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: <Widget>[
                          left,
                          const SizedBox(height: BgSpace.xl),
                          right,
                        ],
                      );
                    }
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Expanded(child: left),
                        const SizedBox(width: BgSpace.xxl),
                        Expanded(child: right),
                      ],
                    );
                  },
                ),

                if (tasteNote != null && tasteNote.isNotEmpty) ...<Widget>[
                  const SizedBox(height: BgSpace.xl),
                  Container(
                    padding: const EdgeInsets.all(BgSpace.lg),
                    decoration: BoxDecoration(
                      color: colors.surfaceContainerLow,
                      borderRadius: BgSpace.brSm,
                      border: Border.all(color: colors.outlineVariant),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Icon(Icons.person_outline,
                            size: 18, color: colors.onSurfaceVariant),
                        const SizedBox(width: BgSpace.md),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: <Widget>[
                              Text('YOUR TASTE', style: text.labelSmall),
                              const SizedBox(height: BgSpace.xs),
                              Text(tasteNote, style: text.bodyMedium),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ],

                // Degradation, stated plainly. Not a toast, not a tooltip.
                if (degraded.isNotEmpty) ...<Widget>[
                  const SizedBox(height: BgSpace.lg),
                  _DegradedNotice(reasons: degraded),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// A labelled list of evidence lines with a coloured rule.
class _EvidenceColumn extends StatelessWidget {
  const _EvidenceColumn({
    required this.eyebrow,
    required this.accent,
    required this.items,
    required this.emptyNote,
  });

  final String eyebrow;
  final Color accent;
  final List<String> items;
  final String emptyNote;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    final ColorScheme colors = Theme.of(context).colorScheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Row(
          children: <Widget>[
            Container(width: 16, height: 2, color: accent),
            const SizedBox(width: BgSpace.sm),
            Text(eyebrow, style: text.labelSmall),
          ],
        ),
        const SizedBox(height: BgSpace.md),
        if (items.isEmpty)
          Text(
            emptyNote,
            style: text.bodySmall?.copyWith(fontStyle: FontStyle.italic),
          )
        else
          for (final String item in items)
            Padding(
              padding: const EdgeInsets.only(bottom: BgSpace.sm),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Padding(
                    padding: const EdgeInsets.only(top: 7, right: BgSpace.sm),
                    child: Container(
                      width: 4,
                      height: 4,
                      decoration: BoxDecoration(
                        color: accent,
                        shape: BoxShape.circle,
                      ),
                    ),
                  ),
                  Expanded(
                    child: Text(
                      item,
                      style: text.bodyMedium?.copyWith(color: colors.onSurface),
                    ),
                  ),
                ],
              ),
            ),
      ],
    );
  }
}

/// Confidence as a small horizontal meter with the figure spelled out.
///
/// A bare percentage invites false precision, so the meter carries a word
/// too. "0.42" and "Tentative" say the same thing to different readers.
class _ConfidenceMeter extends StatelessWidget {
  const _ConfidenceMeter({required this.value});

  final double value;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    final ColorScheme colors = Theme.of(context).colorScheme;
    final Color tone = value >= 0.66
        ? BgPalette.ok
        : value >= 0.33
            ? BgPalette.gold600
            : BgPalette.slate500;

    return Tooltip(
      message: 'How much of the reading rests on complete, fresh data.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text('CONFIDENCE', style: text.labelSmall),
          const SizedBox(height: BgSpace.xs),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(
                _word(value),
                style: text.titleSmall?.copyWith(color: tone),
              ),
              const SizedBox(width: BgSpace.sm),
              SizedBox(
                width: 64,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: value,
                    minHeight: 6,
                    backgroundColor: colors.surfaceContainer,
                    valueColor: AlwaysStoppedAnimation<Color>(tone),
                  ),
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              Text(
                value.toStringAsFixed(2),
                style: text.bodySmall?.copyWith(
                  fontFeatures: const <FontFeature>[
                    FontFeature.tabularFigures(),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static String _word(double v) {
    if (v >= 0.8) return 'High';
    if (v >= 0.6) return 'Good';
    if (v >= 0.35) return 'Partial';
    return 'Tentative';
  }
}

/// The honest bit. Every entry in `degraded[]` gets a line.
class _DegradedNotice extends StatelessWidget {
  const _DegradedNotice({required this.reasons});

  final List<String> reasons;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: BgPalette.gold50,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: BgPalette.gold300),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Icon(Icons.info_outline, size: 18, color: BgPalette.gold600),
          const SizedBox(width: BgSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(
                  'RUNNING DEGRADED',
                  style: text.labelSmall?.copyWith(color: BgPalette.gold600),
                ),
                const SizedBox(height: BgSpace.xs),
                Text(
                  'This forge ran without everything it wanted. What was '
                  'missing:',
                  style: text.bodySmall,
                ),
                const SizedBox(height: BgSpace.sm),
                for (final String reason in reasons)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 2),
                    child: Text('· $reason', style: text.bodyMedium),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
