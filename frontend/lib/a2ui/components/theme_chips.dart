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
/// icon, palette{}. `selected` binds to the currently active theme id (a
/// string). `icon` is a semantic token the backend owns; see
/// [kThemeIconsByToken].
library;

import 'package:flutter/material.dart';

import '../../app_theme.dart';
import '../catalog.dart';
import '../messages.dart';

/// Icon token -> glyph. The ONLY place this renderer decides what a theme
/// looks like, and it decides nothing: the token arrives on the theme payload
/// as `icon`, emitted by `palette.THEME_ICONS` on the Python side.
///
/// This used to be `_iconForTheme(String id)`, which guessed from substrings of
/// the theme id (`contains('rain')`, `contains('fog')`, ...). Four of the eight
/// canonical ids — heatwave_cruise, blue_hour, first_frost, sirocco — matched no
/// branch and all collapsed onto the same grey fallback glyph. Presentation
/// knowledge had leaked into Dart and then drifted from the Python that owns it.
/// Do not reintroduce a guess here: add the token to `THEME_ICONS` in
/// `backend/app/a2ui/palette.py` and give it an entry below.
///
/// TREE-SHAKING: every value is a literal `Icons.*` constant in a `const` map,
/// so `flutter build web --tree-shake-icons` can prove which glyphs survive.
/// Never construct `IconData` from a runtime codepoint here — that defeats the
/// analysis and ships blank boxes in release.
const Map<String, IconData> kThemeIconsByToken = <String, IconData>{
  'water_drop': Icons.water_drop_outlined, // petrichor
  'wb_twilight': Icons.wb_twilight_outlined, // golden_hour
  'foggy': Icons.foggy, // nordic_fog (no outlined variant in Material)
  'thunderstorm': Icons.thunderstorm_outlined, // storm_front
  'wb_sunny': Icons.wb_sunny_outlined, // heatwave_cruise
  'nights_stay': Icons.nights_stay_outlined, // blue_hour
  'ac_unit': Icons.ac_unit_outlined, // first_frost
  'air': Icons.air_outlined, // sirocco
  // Not a theme glyph: the token the backend sends for an id it cannot name.
  // It is in the vocabulary so "unknown theme" looks the same on both sides.
  'graphic_eq': Icons.graphic_eq_outlined,
};

/// THE fallback, and the only one. Reached when the payload carries no `icon`
/// or a token this build does not know — i.e. the backend is ahead of the app.
/// It is deliberately the same glyph as the backend's own `FALLBACK_THEME_ICON`
/// token so the two layers agree on what "unidentified" looks like.
const IconData kThemeIconFallback = Icons.graphic_eq_outlined;

/// Resolve a backend-supplied icon token to a glyph. No guessing, no ids.
IconData themeIconForToken(String? token) =>
    kThemeIconsByToken[token] ?? kThemeIconFallback;

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
                              themeIconForToken(
                                asStringOrNull(theme['icon']),
                              ),
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
