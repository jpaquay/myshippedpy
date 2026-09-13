// Data Viz — question entry and suggestion chips.
//
// UX_IA_SPEC.md §3.4 items 1 and 2. This is rung 0 and it is the point of the
// destination, so it is never behind a disclosure and never a banner.

import 'package:flutter/material.dart';

import '../../app_theme.dart';

/// The field. One line, 48 high, 1 px outline, no fill, no gradient.
class DataVizQuestionField extends StatelessWidget {
  const DataVizQuestionField({
    super.key,
    required this.controller,
    required this.focusNode,
    required this.onSubmit,
    required this.onMicPressed,
    required this.isDictating,
    required this.isBusy,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final ValueChanged<String> onSubmit;
  final VoidCallback onMicPressed;

  /// Dictation is running. The mic gets a filled glyph while it listens —
  /// which is a state change, not an idle animation. §3.4: the mic "does not
  /// pulse, glow, or animate at rest".
  final bool isDictating;

  final bool isBusy;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;

    return SizedBox(
      height: 48,
      child: TextField(
        key: const ValueKey<String>('dataviz-question-field'),
        controller: controller,
        focusNode: focusNode,
        textInputAction: TextInputAction.search,
        maxLines: 1,
        style: theme.textTheme.bodyMedium,
        onSubmitted: onSubmit,
        decoration: InputDecoration(
          hintText: 'Ask about your listening data',
          hintStyle: theme.textTheme.bodyMedium
              ?.copyWith(color: colors.onSurfaceVariant),
          isDense: true,
          filled: false,
          contentPadding: const EdgeInsets.symmetric(vertical: 12),
          prefixIcon: Icon(Icons.search, size: 18, color: colors.onSurfaceVariant),
          prefixIconConstraints:
              const BoxConstraints(minWidth: 42, minHeight: 18),
          suffixIcon: Row(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              IconButton(
                tooltip: isDictating ? 'Stop dictation' : 'Dictate a question',
                onPressed: onMicPressed,
                iconSize: 18,
                visualDensity: VisualDensity.compact,
                icon: Icon(
                  isDictating ? Icons.mic : Icons.mic_none,
                  color: colors.onSurfaceVariant,
                ),
              ),
              IconButton(
                tooltip: 'Ask',
                onPressed: isBusy ? null : () => onSubmit(controller.text),
                iconSize: 18,
                visualDensity: VisualDensity.compact,
                icon: Icon(Icons.arrow_forward, color: colors.onSurfaceVariant),
              ),
            ],
          ),
          border: _border(colors.outlineVariant),
          enabledBorder: _border(colors.outlineVariant),
          focusedBorder: _border(colors.primary),
        ),
      ),
    );
  }

  OutlineInputBorder _border(Color c) => OutlineInputBorder(
        borderRadius: BgSpace.br,
        borderSide: BorderSide(color: c),
      );
}

/// At most three chips. A `Wrap`, never a horizontal carousel.
class DataVizSuggestionChips extends StatelessWidget {
  const DataVizSuggestionChips({
    super.key,
    required this.suggestions,
    required this.onTap,
    required this.enabled,
  });

  final List<String> suggestions;
  final ValueChanged<String> onTap;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    if (suggestions.isEmpty) return const SizedBox.shrink();
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;

    return Wrap(
      key: const ValueKey<String>('dataviz-suggestions'),
      spacing: BgSpace.sm,
      runSpacing: BgSpace.sm,
      children: <Widget>[
        for (final String s in suggestions.take(3))
          ActionChip(
            label: Text(
              s,
              style: theme.textTheme.labelSmall,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            onPressed: enabled ? () => onTap(s) : null,
            backgroundColor: Colors.transparent,
            side: BorderSide(color: colors.outlineVariant),
            shape: const RoundedRectangleBorder(borderRadius: BgSpace.brSm),
            visualDensity: VisualDensity.compact,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            padding: const EdgeInsets.symmetric(
              horizontal: BgSpace.sm,
              vertical: BgSpace.xs,
            ),
          ),
      ],
    );
  }
}

/// The one line of teaching copy that turns an empty conversation into an
/// invitation. §3.4 forbids a hero illustration and a "Welcome to Data Viz"
/// card — the dashboard *is* the empty state — so this is a single sentence
/// under the chips saying what the agent can actually see.
class DataVizEmptyHint extends StatelessWidget {
  const DataVizEmptyHint({super.key, required this.isDegraded});

  /// True when the starter questions could not be fetched from the backend, so
  /// the ones on screen are the built-in list.
  final bool isDegraded;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Text(
      isDegraded
          ? 'The agent is unreachable, so these are the built-in starters. '
              'Answers below come from the last cached BigQuery run.'
          : 'Ask in plain language. The agent queries 160,717 scrobbles '
              '(2012–2026) — artists, tracks, hours, weather themes — and '
              'shows you the SQL it ran.',
      key: const ValueKey<String>('dataviz-empty-hint'),
      style: theme.textTheme.bodySmall
          ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
    );
  }
}
