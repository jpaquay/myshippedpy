/// ThemeChips — the eight sky themes as selectable chips.
///
/// The important thing about this widget is what it does NOT contain: any
/// notion of what selecting a theme means. There is no local `_selected`
/// field. The selected id is read from the data model, and a tap fires the
/// action the agent attached to the component. The agent decides whether that
/// re-forges, re-tints the surface, or does nothing at all, and tells us by
/// sending back messages.
///
/// If you add local selection state here to make it "feel snappier", you have
/// moved a product decision into the client and the two surfaces have started
/// to drift. The correct fix for latency is the busy state, which is already
/// wired.
///
/// Data shape: `items` binds to a Theme[] — each with id, name, tagline,
/// palette{}. `selected` binds to the currently active theme id (a string).
library;

import 'package:flutter/material.dart';

import '../../app_theme.dart';
import '../catalog.dart';
import '../messages.dart';

class ThemeChipsComponent extends StatelessWidget {
  const ThemeChipsComponent({required this.node, super.key});

  final A2uiNode node;

  @override
  Widget build(BuildContext context) {
    final List<Object?> raw = node.list('items').isNotEmpty
        ? node.list('items')
        : node.list('themes');

    if (raw.isEmpty) {
      return A2uiPlaceholder.binding(
        componentId: node.id,
        detail: 'no themes bound to "items"',
      );
    }

    final String? selectedId = node.string('selected');
    final String? label = node.string('title');
    final bool busy = node.host.busy;

    final List<JsonMap> themes = <JsonMap>[
      for (final Object? item in raw)
        if (asJsonMap(item) case final JsonMap theme) theme,
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        if (label != null && label.isNotEmpty) ...<Widget>[
          Row(
            children: <Widget>[
              Icon(
                Icons.auto_awesome_outlined,
                size: 14,
                color: node.colors.primary,
              ),
              const SizedBox(width: BgSpace.xs),
              Text(
                label.toUpperCase(),
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
                for (final JsonMap theme in themes)
                  SizedBox(
                    width: cardWidth,
                    child: _ThemeCard(
                      node: node,
                      theme: theme,
                      selected: asStringOrNull(theme['id']) == selectedId,
                      enabled: !busy,
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

class _ThemeCard extends StatelessWidget {
  const _ThemeCard({
    required this.node,
    required this.theme,
    required this.selected,
    required this.enabled,
  });

  final A2uiNode node;
  final JsonMap theme;
  final bool selected;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = node.colors;
    final TextTheme text = node.text;

    final String id = asStringOrNull(theme['id']) ?? '';
    final String name = asStringOrNull(theme['name']) ?? id;
    final String tagline = asStringOrNull(theme['tagline']) ?? '';
    final List<Color> gradientColors = _paletteGradient(theme, colors.primary);
    final Color primaryAccent = gradientColors.first;

    return Semantics(
      button: true,
      selected: selected,
      label: '$name theme',
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: enabled ? _onTap : null,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOutCubic,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: selected
                    ? <Color>[
                        primaryAccent.withValues(alpha: 0.22),
                        colors.surfaceContainerHigh,
                      ]
                    : <Color>[
                        colors.surfaceContainer,
                        colors.surfaceContainerLow,
                      ],
              ),
              border: Border.all(
                color: selected
                    ? primaryAccent
                    : colors.outlineVariant.withValues(alpha: 0.7),
                width: selected ? 1.8 : 1.0,
              ),
              boxShadow: selected
                  ? <BoxShadow>[
                      BoxShadow(
                        color: primaryAccent.withValues(alpha: 0.20),
                        blurRadius: 16,
                        offset: const Offset(0, 4),
                      ),
                    ]
                  : null,
            ),
            clipBehavior: Clip.antiAlias,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                // Top atmospheric palette ribbon
                Container(
                  height: 5,
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: gradientColors,
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(BgSpace.md),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Row(
                        children: <Widget>[
                          Container(
                            width: 32,
                            height: 32,
                            decoration: BoxDecoration(
                              color: primaryAccent.withValues(alpha: 0.16),
                              borderRadius: BgSpace.brSm,
                              border: Border.all(
                                color: primaryAccent.withValues(alpha: 0.4),
                              ),
                            ),
                            child: Icon(
                              _iconForTheme(id),
                              size: 17,
                              color: primaryAccent,
                            ),
                          ),
                          const SizedBox(width: BgSpace.sm),
                          Expanded(
                            child: Text(
                              name,
                              style: text.titleMedium?.copyWith(
                                fontWeight: FontWeight.w700,
                                color: selected
                                    ? colors.onSurface
                                    : colors.onSurface.withValues(alpha: 0.92),
                              ),
                            ),
                          ),
                          if (selected)
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 3,
                              ),
                              decoration: BoxDecoration(
                                color: primaryAccent.withValues(alpha: 0.22),
                                borderRadius: BorderRadius.circular(99),
                                border: Border.all(color: primaryAccent),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: <Widget>[
                                  Icon(
                                    Icons.check_circle,
                                    size: 12,
                                    color: primaryAccent,
                                  ),
                                  const SizedBox(width: 4),
                                  Text(
                                    'ACTIVE',
                                    style: text.labelSmall?.copyWith(
                                      color: primaryAccent,
                                      fontSize: 10,
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                ],
                              ),
                            )
                          else
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: <Widget>[
                                for (final Color c in gradientColors.take(3))
                                  Container(
                                    width: 8,
                                    height: 8,
                                    margin: const EdgeInsets.only(left: 3),
                                    decoration: BoxDecoration(
                                      color: c,
                                      shape: BoxShape.circle,
                                    ),
                                  ),
                              ],
                            ),
                        ],
                      ),
                      if (tagline.isNotEmpty) ...<Widget>[
                        const SizedBox(height: BgSpace.sm),
                        Text(
                          tagline,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: text.bodySmall?.copyWith(
                            color: selected
                                ? colors.onSurface.withValues(alpha: 0.85)
                                : colors.onSurfaceVariant,
                            height: 1.35,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _onTap() {
    final action = node.action();
    if (action == null) return;
    node.fire(
      action,
      extra: <String, Object?>{
        'themeId': asStringOrNull(theme['id']),
      },
    );
  }

  static IconData _iconForTheme(String id) {
    final String lower = id.toLowerCase();
    if (lower.contains('petrichor') || lower.contains('rain')) {
      return Icons.water_drop_outlined;
    }
    if (lower.contains('fog') || lower.contains('nordic') || lower.contains('mist')) {
      return Icons.foggy;
    }
    if (lower.contains('solar') || lower.contains('zenith') || lower.contains('sun')) {
      return Icons.wb_sunny_outlined;
    }
    if (lower.contains('isobar') || lower.contains('surge') || lower.contains('wind')) {
      return Icons.air;
    }
    if (lower.contains('golden') || lower.contains('dusk') || lower.contains('twilight')) {
      return Icons.wb_twilight;
    }
    if (lower.contains('midnight') || lower.contains('velvet') || lower.contains('night')) {
      return Icons.nightlight_round;
    }
    if (lower.contains('storm') || lower.contains('front') || lower.contains('thunder')) {
      return Icons.thunderstorm_outlined;
    }
    return Icons.graphic_eq;
  }

  static List<Color> _paletteGradient(JsonMap theme, Color fallback) {
    final JsonMap? palette = asJsonMap(theme['palette']);
    final List<Color> out = <Color>[];
    if (palette != null) {
      for (final String key in const <String>['accent', 'primary', 'base', 'ink']) {
        final String? hex = asStringOrNull(palette[key]);
        if (hex != null) {
          out.add(BgTheme.parseHex(hex, fallback: fallback));
        }
      }
      if (out.isEmpty) {
        for (final Object? v in palette.values) {
          final String? hex = asStringOrNull(v);
          if (hex != null && hex.startsWith('#')) {
            out.add(BgTheme.parseHex(hex, fallback: fallback));
          }
        }
      }
    }
    if (out.isEmpty) {
      return <Color>[fallback, fallback.withValues(alpha: 0.6)];
    }
    if (out.length == 1) {
      return <Color>[out.first, out.first.withValues(alpha: 0.6)];
    }
    return out;
  }
}
