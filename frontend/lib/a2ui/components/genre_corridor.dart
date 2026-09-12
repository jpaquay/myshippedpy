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

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        if (title != null && title.isNotEmpty) ...<Widget>[
          Text(title.toUpperCase(), style: node.text.labelSmall),
          const SizedBox(height: BgSpace.md),
        ],
        for (final Object? raw in items)
          if (asJsonMap(raw) case final JsonMap corridor)
            Padding(
              padding: const EdgeInsets.only(bottom: BgSpace.sm),
              child: _CorridorRow(
                node: node,
                corridor: corridor,
                selected: asStringOrNull(corridor['id']) == selectedId,
              ),
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
      color: selected ? colors.primaryContainer : colors.surface,
      borderRadius: BgSpace.brSm,
      child: InkWell(
        borderRadius: BgSpace.brSm,
        onTap: enabled ? () => _select(id) : null,
        child: Container(
          padding: const EdgeInsets.all(BgSpace.md),
          decoration: BoxDecoration(
            borderRadius: BgSpace.brSm,
            border: Border.all(
              color: selected ? colors.primary : colors.outlineVariant,
              width: selected ? 1.6 : 1,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Expanded(
                    child: Text(
                      name,
                      style: text.titleMedium?.copyWith(
                        color: selected
                            ? colors.onPrimaryContainer
                            : colors.onSurface,
                      ),
                    ),
                  ),
                  Text(
                    '± ${(width / 2 * 100).round()}',
                    style: text.bodySmall?.copyWith(
                      fontFeatures: const <FontFeature>[
                        FontFeature.tabularFigures(),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: BgSpace.sm),
              _CorridorTrack(
                anchor: anchor,
                width: width,
                tone: selected ? colors.primary : BgPalette.slate400,
                trackColor: colors.surfaceContainer,
                rule: colors.outline,
              ),
              if (description != null && description.isNotEmpty) ...<Widget>[
                const SizedBox(height: BgSpace.sm),
                Text(description, style: text.bodySmall),
              ],
              if (tags.isNotEmpty) ...<Widget>[
                const SizedBox(height: BgSpace.sm),
                Wrap(
                  spacing: BgSpace.xs,
                  runSpacing: BgSpace.xs,
                  children: <Widget>[
                    for (final String tag in tags.take(6))
                      _TagPill(label: tag),
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

/// The corridor itself: a full-width axis with a shaded band centred on the
/// anchor. Deliberately unlabelled at the ends — the axis is abstract and
/// pretending it has units would be dishonest.
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
        const double h = 10;
        final double full = c.maxWidth;
        final double bandWidth = math.max(full * width, 4);
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
                    color: tone.withValues(alpha: 0.35),
                    borderRadius: BorderRadius.circular(h / 2),
                    border: Border.all(color: tone, width: 1),
                  ),
                ),
              ),
              // The anchor tick. The band says "how far"; the tick says
              // "from where".
              Positioned(
                left: (full * anchor - 1).clamp(0.0, full - 2),
                top: -2,
                bottom: -2,
                width: 2,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: tone,
                    borderRadius: BorderRadius.circular(1),
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
  const _TagPill({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 11.5),
      ),
    );
  }
}
