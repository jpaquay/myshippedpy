/// A labelled section. Shell chrome — a rule, an eyebrow, and whatever the
/// server sent underneath it.
library;

import 'package:flutter/material.dart';

import '../../app_theme.dart';

class Section extends StatelessWidget {
  const Section({
    required this.eyebrow,
    required this.child,
    this.trailing,
    super.key,
  });

  final String eyebrow;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    final ColorScheme colors = Theme.of(context).colorScheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Row(
          children: <Widget>[
            Text(eyebrow, style: text.labelSmall),
            const SizedBox(width: BgSpace.md),
            Expanded(child: Divider(color: colors.outlineVariant)),
            if (trailing != null) ...<Widget>[
              const SizedBox(width: BgSpace.md),
              trailing!,
            ],
          ],
        ),
        const SizedBox(height: BgSpace.lg),
        child,
      ],
    );
  }
}
