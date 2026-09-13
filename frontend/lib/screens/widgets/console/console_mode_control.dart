import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../app_theme.dart';
import 'console_mode.dart';
import 'console_tokens.dart';

/// §5.1 — the affordance.
///
/// One full-width `SegmentedButton<String>` with three equal segments and no
/// icons, and directly beneath it a permanent one-line helper that changes with
/// the mode. This replaces the three `_ModePillButton`s, which read as "two and
/// a half" choices because the labels were long, the icons were decorative and
/// the selected state was an accent-filled block (also an accent-budget breach,
/// §7.3).
class ConsoleModeControl extends StatelessWidget {
  const ConsoleModeControl({
    required this.mode,
    required this.onChanged,
    super.key,
  });

  final ConsoleMode mode;
  final ValueChanged<ConsoleMode> onChanged;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        SizedBox(
          width: double.infinity,
          child: SegmentedButton<String>(
            key: ForgeKeys.modeControl,
            showSelectedIcon: false,
            style: SegmentedButton.styleFrom(
              textStyle: text.labelLarge,
              side: BorderSide(color: colors.outlineVariant),
              shape: const RoundedRectangleBorder(
                borderRadius: BgSpace.brSm,
              ),
            ),
            segments: <ButtonSegment<String>>[
              for (final ConsoleMode m in ConsoleMode.values)
                ButtonSegment<String>(
                  value: m.id,
                  label: Text(m.label),
                  tooltip: m.helper,
                ),
            ],
            selected: <String>{mode.id},
            onSelectionChanged: (Set<String> selection) {
              if (selection.isEmpty) return;
              HapticFeedback.selectionClick();
              onChanged(ConsoleMode.fromId(selection.first));
            },
          ),
        ),
        const SizedBox(height: BgSpace.sm),
        Text(
          mode.helper,
          key: ForgeKeys.modeHelper,
          style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
      ],
    );
  }
}
