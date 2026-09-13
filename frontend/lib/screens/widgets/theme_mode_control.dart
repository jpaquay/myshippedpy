/// The appearance control: Dark / Light / As host.
///
/// Spec §7.4. It lives in Settings → APPEARANCE and nowhere else; the account
/// menu shows the current value and deep-links here. The old binary Sun/Moon
/// toggle in the AppBar and its duplicate in `NavigationRail.trailing` are
/// both gone.
///
/// "As host" is the default and follows the operating system. It is worded
/// that way rather than "System" because on the web the host is the browser,
/// which is in turn following the OS, and "As host" is honest about the chain.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app_theme.dart';
import '../../providers.dart';

class ThemeModeControl extends ConsumerWidget {
  const ThemeModeControl({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final BgThemeChoice choice = ref.watch(bgThemeChoiceProvider);
    final BgColors bg = Theme.of(context).bg;
    final bool expanded = BgBreak.isExpanded(context);

    final Widget control = SegmentedButton<BgThemeChoice>(
      segments: <ButtonSegment<BgThemeChoice>>[
        for (final BgThemeChoice c in BgThemeChoice.values)
          ButtonSegment<BgThemeChoice>(
            value: c,
            label: Text(c.label),
            icon: Icon(c.icon, size: BgIcon.inline),
            tooltip: switch (c) {
              BgThemeChoice.dark => 'Always dark',
              BgThemeChoice.light => 'Always light',
              BgThemeChoice.host => 'Follow this device’s setting',
            },
          ),
      ],
      selected: <BgThemeChoice>{choice},
      showSelectedIcon: false,
      onSelectionChanged: (Set<BgThemeChoice> selection) {
        HapticFeedback.selectionClick();
        ref.read(bgThemeChoiceProvider.notifier).choose(selection.first);
      },
    );

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(BgSpace.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            SizedBox(
              width: expanded ? 320 : double.infinity,
              child: control,
            ),
            const SizedBox(height: BgSpace.sm),
            Text(
              choice == BgThemeChoice.host
                  ? 'Following this device — currently '
                      '${Theme.of(context).brightness == Brightness.dark ? 'dark' : 'light'}.'
                  : 'Fixed to ${choice.label.toLowerCase()}, whatever this '
                      'device is set to.',
              style: BgText.caption(context)?.copyWith(color: bg.inkSecondary),
            ),
          ],
        ),
      ),
    );
  }
}
