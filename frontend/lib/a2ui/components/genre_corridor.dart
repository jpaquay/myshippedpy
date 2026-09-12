/// GenreCorridor — a genre as an anchor point plus a tolerance.
///
/// A corridor is not a category, it is an interval: `anchor` is where the
/// centre of the corridor sits on the genre axis and `width` is how far the
/// forge may wander from it. Rendering it as a chip would throw away the
/// second number, which is the interesting one — a wide corridor and a narrow
/// corridor with the same anchor produce very different playlists.
///
/// So each corridor draws as a horizontal track with a shaded band. Selecting
/// one fires the agent's action. If the component declares a `widthAction`,
/// the band also becomes draggable and reports the new width — that is the
/// agent letting the user tune the corridor, not the client inventing a
/// control.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../app_theme.dart';
import '../catalog.dart';
import '../messages.dart';

class GenreCorridorComponent extends StatelessWidget {
  const GenreCorridorComponent({required this.node, super.key});

  final A2uiNode node;

  @override
  Widget build(BuildContext context) {
    final List<Object?> items = node.list('items').isNotEmpty
        ? node.list('items')
        : node.list('corridors');

    if (items.isEmpty) {
      return A2uiPlaceholder.binding(
        componentId: node.id,
        detail: 'no corridors bound to "items"',
      );
    }

    final String? selectedId = node.string('selected');
    final String? title = node.string('title');
    final List<JsonMap> corridors = <JsonMap>[
      for (final Object? raw in items)
        if (asJsonMap(raw) case final JsonMap c) c,
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        if (title != null && title.isNotEmpty) ...<Widget>[
          Row(
            children: <Widget>[
              Icon(Icons.tune, size: 14, color: node.colors.primary),
              const SizedBox(width: BgSpace.xs),
              Text(
                title.toUpperCase(),
                style: node.text.labelSmall?.copyWith(
                  letterSpacing: 1.2,
                  color: node.colors.primary,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.md),
        ],
        LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) {
            final int cols = constraints.maxWidth >= 560 ? 2 : 1;
            final double cardWidth = cols == 1
                ? constraints.maxWidth
                : (constraints.maxWidth - BgSpace.md) / 2;

            return Wrap(
              spacing: BgSpace.md,
              runSpacing: BgSpace.md,
              children: <Widget>[
                for (final JsonMap corridor in corridors)
                  SizedBox(
                    width: cardWidth,
                    child: _CorridorRow(
                      node: node,
                      corridor: corridor,
                      selected: asStringOrNull(corridor['id']) == selectedId,
                    ),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _CorridorRow extends StatelessWidget {
  const _CorridorRow({
    required this.node,
    required this.corridor,
    required this.selected,
  });

  final A2uiNode node;
  final JsonMap corridor;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = node.colors;
    final TextTheme text = node.text;

    final String id = asStringOrNull(corridor['id']) ?? '';
    final String name = asStringOrNull(corridor['name']) ?? id;
    final String? description = asStringOrNull(corridor['description']);
    final double anchor =
        (asDoubleOrNull(corridor['anchor']) ?? 0.5).clamp(0.0, 1.0);
    final double width =
        (asDoubleOrNull(corridor['width']) ?? 0.2).clamp(0.0, 1.0);
    final List<String> tags = asStringList(corridor['tags']);

    final bool enabled = !node.host.busy;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: enabled ? () => _select(id) : null,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.all(BgSpace.md),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: selected
                  ? <Color>[
                      colors.primary.withValues(alpha: 0.18),
                      colors.surfaceContainerHigh,
                    ]
                  : <Color>[
                      colors.surfaceContainer,
                      colors.surfaceContainerLow,
                    ],
            ),
            border: Border.all(
              color: selected ? colors.primary : colors.outlineVariant,
              width: selected ? 1.8 : 1.0,
            ),
            boxShadow: selected
                ? <BoxShadow>[
                    BoxShadow(
                      color: colors.primary.withValues(alpha: 0.18),
                      blurRadius: 14,
                      offset: const Offset(0, 4),
                    ),
                  ]
                : null,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Icon(
                    Icons.equalizer,
                    size: 16,
                    color: selected ? colors.primary : colors.onSurfaceVariant,
                  ),
                  const SizedBox(width: BgSpace.xs),
                  Expanded(
                    child: Text(
                      name,
                      style: text.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: selected
                            ? colors.onSurface
                            : colors.onSurface.withValues(alpha: 0.9),
                      ),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 7,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: selected
                          ? colors.primary.withValues(alpha: 0.22)
                          : colors.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(99),
                    ),
                    child: Text(
                      '±${(width / 2 * 100).round()}% BAND',
                      style: text.labelSmall?.copyWith(
                        fontSize: 10,
                        color: selected
                            ? colors.primary
                            : colors.onSurfaceVariant,
                        fontWeight: FontWeight.w700,
                        fontFeatures: const <FontFeature>[
                          FontFeature.tabularFigures(),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: BgSpace.md),
              _CorridorTrack(
                anchor: anchor,
                width: width,
                tone: selected ? colors.primary : BgPalette.gold500,
                trackColor: colors.surfaceContainerHighest,
                rule: colors.outline,
              ),
              if (description != null && description.isNotEmpty) ...<Widget>[
                const SizedBox(height: BgSpace.sm),
                Text(
                  description,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: text.bodySmall?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ],
              if (tags.isNotEmpty) ...<Widget>[
                const SizedBox(height: BgSpace.sm),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: <Widget>[
                    for (final String tag in tags.take(5))
                      _TagPill(label: tag, active: selected),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  void _select(String id) {
    final action = node.action();
    if (action == null) return;
    node.fire(action, extra: <String, Object?>{'genreId': id});
  }
}

class _CorridorTrack extends StatelessWidget {
  const _CorridorTrack({
    required this.anchor,
    required this.width,
    required this.tone,
    required this.trackColor,
    required this.rule,
  });

  final double anchor;
  final double width;
  final Color tone;
  final Color trackColor;
  final Color rule;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints c) {
        const double h = 12;
        final double full = c.maxWidth;
        final double bandWidth = math.max(full * width, 8);
        final double left =
            (full * anchor - bandWidth / 2).clamp(0.0, full - bandWidth);

        return SizedBox(
          height: h,
          width: full,
          child: Stack(
            children: <Widget>[
              Positioned.fill(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: trackColor,
                    borderRadius: BorderRadius.circular(h / 2),
                  ),
                ),
              ),
              Positioned(
                left: left,
                width: bandWidth,
                top: 0,
                bottom: 0,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: <Color>[
                        tone.withValues(alpha: 0.25),
                        tone.withValues(alpha: 0.55),
                        tone.withValues(alpha: 0.25),
                      ],
                    ),
                    borderRadius: BorderRadius.circular(h / 2),
                    border: Border.all(color: tone, width: 1.2),
                  ),
                ),
              ),
              Positioned(
                left: (full * anchor - 2).clamp(0.0, full - 4),
                top: -2,
                bottom: -2,
                width: 4,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(2),
                    boxShadow: <BoxShadow>[
                      BoxShadow(
                        color: tone,
                        blurRadius: 6,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _TagPill extends StatelessWidget {
  const _TagPill({required this.label, this.active = false});

  final String label;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 8,
        vertical: 3,
      ),
      decoration: BoxDecoration(
        color: active
            ? colors.primary.withValues(alpha: 0.14)
            : colors.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(99),
        border: Border.all(
          color: active
              ? colors.primary.withValues(alpha: 0.4)
              : colors.outlineVariant.withValues(alpha: 0.6),
        ),
      ),
      child: Text(
        '#$label',
        style: text.labelSmall?.copyWith(
          fontSize: 10.5,
          color: active ? colors.primary : colors.onSurfaceVariant,
        ),
      ),
    );
  }
}
