import 'package:flutter/material.dart';

import '../../../app_theme.dart';

/// Rung 1 of the disclosure ladder (`docs/UX_IA_SPEC.md` §2), as used by the
/// Forge console.
///
/// The spec asks for one shared `BgDisclosure` in
/// `frontend/lib/screens/widgets/bg_disclosure.dart`. That file does not exist
/// yet and belongs to the design-system item, so item 8 ships the same
/// behaviour locally, styled to the same rules, ready to be swapped out:
///
/// * no fill, no elevation, a 1 px `outlineVariant` rule above the header;
/// * header is `labelSmall`, UPPERCASE, `onSurfaceVariant`, with an optional
///   plain-text trailing count;
/// * trailing `keyboard_arrow_down`, 18 px, rotating 180° over 180 ms;
/// * collapsed by default, and the body is **not built at all** while
///   collapsed — so a widget test asserting "Easy does not render the dial"
///   means exactly that, rather than "renders it offstage".
class ConsoleDisclosure extends StatefulWidget {
  const ConsoleDisclosure({
    required this.label,
    required this.builder,
    this.trailingLabel,
    this.initiallyExpanded = false,
    super.key,
  });

  /// Noun phrase, uppercased by convention. "Advanced" is banned (§2).
  final String label;

  /// Optional plain-text trailing hint, e.g. a count `(3)`.
  final String? trailingLabel;

  /// Built lazily, only while expanded.
  final WidgetBuilder builder;

  final bool initiallyExpanded;

  @override
  State<ConsoleDisclosure> createState() => _ConsoleDisclosureState();
}

class _ConsoleDisclosureState extends State<ConsoleDisclosure> {
  late bool _expanded = widget.initiallyExpanded;

  @override
  void didUpdateWidget(ConsoleDisclosure oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.initiallyExpanded != widget.initiallyExpanded) {
      _expanded = widget.initiallyExpanded;
    }
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Divider(height: 1, thickness: 1, color: colors.outlineVariant),
        InkWell(
          onTap: () => setState(() => _expanded = !_expanded),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: BgSpace.md),
            child: Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    widget.label.toUpperCase(),
                    style: text.labelSmall?.copyWith(
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                ),
                if (widget.trailingLabel != null) ...<Widget>[
                  Text(
                    widget.trailingLabel!,
                    style: text.bodySmall?.copyWith(
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(width: BgSpace.sm),
                ],
                AnimatedRotation(
                  turns: _expanded ? 0.5 : 0.0,
                  duration: const Duration(milliseconds: 180),
                  child: Icon(
                    Icons.keyboard_arrow_down,
                    size: 18,
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
        if (_expanded)
          Padding(
            padding: const EdgeInsets.only(bottom: BgSpace.md),
            child: widget.builder(context),
          ),
      ],
    );
  }
}
