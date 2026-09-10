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

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        if (label != null && label.isNotEmpty) ...<Widget>[
          Text(label.toUpperCase(), style: node.text.labelSmall),
          const SizedBox(height: BgSpace.md),
        ],
        Wrap(
          spacing: BgSpace.sm,
          runSpacing: BgSpace.sm,
          children: <Widget>[
            for (final Object? item in raw)
              if (asJsonMap(item) case final JsonMap theme)
                _ThemeChip(
                  node: node,
                  theme: theme,
                  selected: asStringOrNull(theme['id']) == selectedId,
                  enabled: !busy,
                ),
          ],
        ),
        // The tagline of the active theme, promoted below the row. It is the
        // one line of copy that tells the user what they just chose.
        if (selectedId != null)
          Builder(
            builder: (BuildContext context) {
              final JsonMap? active = _find(raw, selectedId);
              final String? tagline = asStringOrNull(active?['tagline']);
              if (tagline == null || tagline.isEmpty) {
                return const SizedBox.shrink();
              }
              return Padding(
                padding: const EdgeInsets.only(top: BgSpace.md),
                child: Text(
                  tagline,
                  style: node.text.bodyMedium?.copyWith(
                    color: node.colors.onSurfaceVariant,
                    fontStyle: FontStyle.italic,
                  ),
                ),
              );
            },
          ),
      ],
    );
  }

  static JsonMap? _find(List<Object?> items, String id) {
    for (final Object? i in items) {
      final JsonMap? m = asJsonMap(i);
      if (m != null && asStringOrNull(m['id']) == id) return m;
    }
    return null;
  }
}

class _ThemeChip extends StatelessWidget {
  const _ThemeChip({
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

    // Each theme carries a palette; we use it as a small colour swatch on the
    // chip rather than repainting the chip. A row of eight fully-tinted chips
    // would look like a paint catalogue, not an instrument.
    final Color swatch = _swatch(theme, colors.primary);

    return Semantics(
      button: true,
      selected: selected,
      label: '$name theme',
      child: Material(
        color: selected ? colors.primaryContainer : colors.surface,
        borderRadius: BgSpace.brSm,
        child: InkWell(
          borderRadius: BgSpace.brSm,
          onTap: enabled ? _onTap : null,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 140),
            padding: const EdgeInsets.symmetric(
              horizontal: BgSpace.md,
              vertical: BgSpace.sm + 2,
            ),
            decoration: BoxDecoration(
              borderRadius: BgSpace.brSm,
              border: Border.all(
                color: selected ? colors.primary : colors.outline,
                width: selected ? 1.6 : 1,
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Container(
                  width: 10,
                  height: 10,
                  decoration: BoxDecoration(
                    color: swatch,
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: colors.outlineVariant,
                    ),
                  ),
                ),
                const SizedBox(width: BgSpace.sm),
                Text(
                  name,
                  style: text.labelLarge?.copyWith(
                    color: enabled
                        ? (selected
                            ? colors.onPrimaryContainer
                            : colors.onSurface)
                        : colors.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// Fires the agent's action, adding this chip's theme id to the payload.
  ///
  /// The agent may have bound `themeId` itself via a path; adding it here as
  /// a literal covers the common case where the component declares one action
  /// for the whole group and expects the client to say which chip was hit.
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

  static Color _swatch(JsonMap theme, Color fallback) {
    final JsonMap? palette = asJsonMap(theme['palette']);
    if (palette == null) return fallback;
    for (final String key in const <String>[
      'accent',
      'primary',
      'base',
      'ink',
    ]) {
      final String? hex = asStringOrNull(palette[key]);
      if (hex != null) return BgTheme.parseHex(hex, fallback: fallback);
    }
    // Otherwise take the first hex-looking value in the palette.
    for (final Object? v in palette.values) {
      final String? hex = asStringOrNull(v);
      if (hex != null && hex.startsWith('#')) {
        return BgTheme.parseHex(hex, fallback: fallback);
      }
    }
    return fallback;
  }
}
