import 'package:flutter/material.dart';

import '../../../app_theme.dart';
import 'console_tokens.dart';

/// Rung 2 of the disclosure ladder (`docs/UX_IA_SPEC.md` §2): out of flow, for
/// raw data and diagnostics.
///
/// * `< 900 px` — a scroll-controlled modal bottom sheet, top radius 16 (the
///   one radius above 10 the spec allows, and only here).
/// * `>= 900 px` — a right-anchored panel 420 px wide, full height, 1 px left
///   rule, no scrim. Deliberately not a `Dialog`: §2 forbids new ones.
///
/// Always has a visible Close.
Future<void> showConsoleDetailSheet(
  BuildContext context, {
  required String title,
  required WidgetBuilder builder,
}) {
  final bool expanded = ForgeMetrics.isExpanded(context);
  if (!expanded) {
    return showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      useSafeArea: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (BuildContext sheetContext) => FractionallySizedBox(
        heightFactor: 0.6,
        child: _SheetBody(title: title, builder: builder),
      ),
    );
  }

  return showGeneralDialog<void>(
    context: context,
    barrierDismissible: true,
    barrierLabel: title,
    barrierColor: Colors.transparent,
    transitionDuration: const Duration(milliseconds: 180),
    pageBuilder: (BuildContext dialogContext, _, __) {
      final ColorScheme colors = Theme.of(dialogContext).colorScheme;
      return Align(
        alignment: Alignment.centerRight,
        child: Material(
          color: colors.surface,
          child: Container(
            width: 420,
            height: double.infinity,
            decoration: BoxDecoration(
              border: Border(
                left: BorderSide(color: colors.outlineVariant),
              ),
            ),
            child: _SheetBody(title: title, builder: builder),
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

class _SheetBody extends StatelessWidget {
  const _SheetBody({required this.title, required this.builder});

  final String title;
  final WidgetBuilder builder;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    final ColorScheme colors = Theme.of(context).colorScheme;

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
