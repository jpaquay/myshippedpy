/// The honest-degradation note.
///
/// Used wherever the backend hands us a `degraded[]` list or a call fails.
/// It states what is missing in the backend's own words. We do not summarise
/// it into "something went wrong", and we do not hide it behind a toast that
/// disappears before it is read.
library;

import 'package:flutter/material.dart';

import '../../app_theme.dart';

enum DegradedTone { notice, error }

class DegradedNotes extends StatelessWidget {
  const DegradedNotes({
    required this.title,
    required this.notes,
    this.tone = DegradedTone.notice,
    this.action,
    super.key,
  });

  final String title;
  final List<String> notes;
  final DegradedTone tone;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    final Color accent =
        tone == DegradedTone.error ? colors.error : BgPalette.gold600;
    final Color background = tone == DegradedTone.error
        ? colors.surfaceContainerLow
        : BgPalette.gold50;
    final Color border = tone == DegradedTone.error
        ? colors.error.withValues(alpha: 0.4)
        : BgPalette.gold300;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(
            tone == DegradedTone.error
                ? Icons.error_outline
                : Icons.info_outline,
            size: 18,
            color: accent,
          ),
          const SizedBox(width: BgSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(title, style: text.titleSmall?.copyWith(color: accent)),
                const SizedBox(height: BgSpace.sm),
                for (final String note in notes)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 2),
                    child: Text('· $note', style: text.bodyMedium),
                  ),
                if (action != null) ...<Widget>[
                  const SizedBox(height: BgSpace.md),
                  action!,
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
