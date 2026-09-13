import 'package:flutter/material.dart';

import '../app_theme.dart';

/// The disclosure ladder of `docs/UX_IA_SPEC.md` §2, built once.
///
/// Three workers shipped a local copy of these rules while this file did not
/// exist (the Forge console's `ConsoleDisclosure` /
/// `showConsoleDetailSheet`, and Data Viz's `SOURCE QUERY` / `SUMMARY`
/// disclosures). They are consolidated here; the visual contract below is the
/// union of what all three rendered, so the swap is behaviour-preserving.
///
/// * **Rung 0** is not a widget — it is "always visible".
/// * **Rung 1** is [BgDisclosure]: a styled expansion tile, in place.
/// * **Rung 2** is [showBgDetailSheet]: out of flow, sheet or side panel.
///
/// Nothing here declares a colour, a size or a radius of its own: every value
/// comes from `app_theme.dart` (`BgSpace`, `BgBreak`, the `ColorScheme` and the
/// `TextTheme`). §7 forbids a second palette.

/// How long the chevron takes to rotate 180° (§2, rung 1), and how long the
/// rung-2 side panel takes to slide in.
const Duration _kDisclosureMotion = Duration(milliseconds: 180);

/// Rung 1 of the ladder (§2): an in-place, styled expansion tile.
///
/// Contract, verbatim from the spec:
///
/// * `elevation: 0`, no fill, a 1 px `outlineVariant` rule above the header;
/// * header row `labelSmall` (the eyebrow role), UPPERCASE, `onSurfaceVariant`;
/// * optional trailing count/provenance as plain text — no pill — which gives
///   way first: at 390 px it ellipsises rather than pushing the chevron off the
///   card;
/// * trailing `Icons.keyboard_arrow_down`, 18 px, rotating 180° over 180 ms;
/// * `initiallyExpanded: false` by default. The one sanctioned exception per
///   destination passes [BgBreak.disclosureDefaultOpen] (≥ 900 px opens).
///
/// The body is **built lazily** — while collapsed, [builder] is never called,
/// so a test asserting "Easy does not render the dial" means exactly that,
/// rather than "renders it offstage". Do not replace this with a Material
/// `ExpansionTile`, which builds and merely hides its children.
///
/// Never nest a [BgDisclosure] inside a [BgDisclosure]; the inner level is
/// rung 2 (§2).
class BgDisclosure extends StatefulWidget {
  const BgDisclosure({
    super.key,
    required this.label,
    required this.builder,
    this.trailingLabel,
    this.initiallyExpanded = false,
    this.onExpansionChanged,
    this.bodyPadding = const EdgeInsets.only(bottom: BgSpace.md),
  });

  /// Noun phrase, uppercased for display. "Advanced" is banned (§2, rule 5) —
  /// it is a rung, not a word.
  final String label;

  /// Optional plain-text trailing hint: a count `(3)`, a provenance line.
  final String? trailingLabel;

  /// Built only while expanded, and rebuilt on each open.
  final WidgetBuilder builder;

  /// §2: `false` always, except the one exception named per destination —
  /// typically `BgBreak.disclosureDefaultOpen(context)` (open at ≥ 900 px).
  final bool initiallyExpanded;

  /// Notified when the user toggles the tile. The widget still owns the state;
  /// this is for callers that mirror it (analytics, a parent's layout).
  final ValueChanged<bool>? onExpansionChanged;

  /// Space around the body. Defaults to the 12 px bottom gap the console and
  /// Data Viz both used; a caller whose body already carries its own rhythm
  /// passes its own.
  final EdgeInsetsGeometry bodyPadding;

  @override
  State<BgDisclosure> createState() => _BgDisclosureState();
}

class _BgDisclosureState extends State<BgDisclosure> {
  late bool _expanded = widget.initiallyExpanded;

  @override
  void didUpdateWidget(BgDisclosure oldWidget) {
    super.didUpdateWidget(oldWidget);
    // A width change that crosses 900 px re-applies the default (§4), which is
    // what `initiallyExpanded` carries. A user toggle inside one layout is
    // preserved, because the flag has not moved.
    if (oldWidget.initiallyExpanded != widget.initiallyExpanded) {
      _expanded = widget.initiallyExpanded;
    }
  }

  void _toggle() {
    setState(() => _expanded = !_expanded);
    widget.onExpansionChanged?.call(_expanded);
  }

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;
    final TextTheme text = theme.textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Divider(height: 1, thickness: 1, color: colors.outlineVariant),
        InkWell(
          onTap: _toggle,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: BgSpace.md),
            child: Row(
              children: <Widget>[
                Text(
                  widget.label.toUpperCase(),
                  style: text.labelSmall?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
                const Spacer(),
                if (widget.trailingLabel != null &&
                    widget.trailingLabel!.isNotEmpty)
                  Flexible(
                    child: Padding(
                      padding: const EdgeInsets.only(left: BgSpace.sm),
                      child: Text(
                        widget.trailingLabel!,
                        textAlign: TextAlign.right,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: text.labelSmall?.copyWith(
                          color: colors.onSurfaceVariant,
                        ),
                      ),
                    ),
                  ),
                const SizedBox(width: BgSpace.sm),
                AnimatedRotation(
                  turns: _expanded ? 0.5 : 0.0,
                  duration: _kDisclosureMotion,
                  child: Icon(
                    Icons.keyboard_arrow_down,
                    size: BgIcon.inline,
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
        if (_expanded)
          Padding(
            padding: widget.bodyPadding,
            child: widget.builder(context),
          ),
      ],
    );
  }
}

/// Rung 2 of the ladder (§2): out of flow, for raw data, diagnostics, editors
/// and confirmations.
///
/// * `< 900 px` — a scroll-controlled modal bottom sheet, top radius
///   [BgSpace.radiusSheet] (the one radius above 10 the spec allows, and only
///   here), initial height 60 % of the viewport.
/// * `>= 900 px` — a right-anchored panel [kBgDetailPanelWidth] wide, full
///   height, 1 px left rule, no scrim. Deliberately **not** a `Dialog`: §2
///   forbids new ones. (The telemetry inspector's 1120 × 780 dialog is
///   grandfathered.)
///
/// Always has a visible Close, so focus is never trapped.
Future<void> showBgDetailSheet(
  BuildContext context, {
  required String title,
  required WidgetBuilder builder,
}) {
  if (!BgBreak.isExpanded(context)) {
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      useSafeArea: true,
      shape: const RoundedRectangleBorder(borderRadius: BgSpace.brSheet),
      builder: (BuildContext sheetContext) => FractionallySizedBox(
        heightFactor: _kSheetInitialHeightFactor,
        child: _BgDetailSheetBody(title: title, builder: builder),
      ),
    );
  }

  return showGeneralDialog<void>(
    context: context,
    barrierDismissible: true,
    barrierLabel: title,
    barrierColor: Colors.transparent,
    transitionDuration: _kDisclosureMotion,
    pageBuilder: (BuildContext dialogContext, _, __) {
      final ColorScheme colors = Theme.of(dialogContext).colorScheme;
      return Align(
        alignment: Alignment.centerRight,
        child: Material(
          color: colors.surface,
          child: Container(
            width: kBgDetailPanelWidth,
            height: double.infinity,
            decoration: BoxDecoration(
              border: Border(
                left: BorderSide(color: colors.outlineVariant),
              ),
            ),
            child: _BgDetailSheetBody(title: title, builder: builder),
          ),
        ),
      );
    },
    transitionBuilder: (_, Animation<double> animation, __, Widget child) =>
        SlideTransition(
      position: Tween<Offset>(
        begin: const Offset(1, 0),
        end: Offset.zero,
      ).animate(
        CurvedAnimation(parent: animation, curve: Curves.easeOutCubic),
      ),
      child: child,
    ),
  );
}

/// §2 — the desktop side panel is 420 wide, full height.
const double kBgDetailPanelWidth = 420;

/// §2 — the mobile sheet opens at 60 % of the viewport.
const double _kSheetInitialHeightFactor = 0.6;

class _BgDetailSheetBody extends StatelessWidget {
  const _BgDetailSheetBody({required this.title, required this.builder});

  final String title;
  final WidgetBuilder builder;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final TextTheme text = theme.textTheme;
    final ColorScheme colors = theme.colorScheme;

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          BgSpace.lg,
          BgSpace.md,
          BgSpace.lg,
          BgSpace.lg,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    title.toUpperCase(),
                    style: text.labelSmall?.copyWith(
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                ),
                TextButton(
                  onPressed: () => Navigator.of(context).maybePop(),
                  child: const Text('Close'),
                ),
              ],
            ),
            const SizedBox(height: BgSpace.sm),
            Flexible(
              child: SingleChildScrollView(child: builder(context)),
            ),
          ],
        ),
      ),
    );
  }
}
