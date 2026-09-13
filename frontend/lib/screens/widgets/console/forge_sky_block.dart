import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app_theme.dart';
import '../../../providers.dart';
import 'console_disclosure.dart';
import 'console_mode.dart';
import 'console_tokens.dart';
import 'forge_sky_reading.dart';

/// How much of the sky the Forge shows, which is a function of the console
/// mode (`docs/UX_IA_SPEC.md` §5.2, rows "`_SkyStrip`" and "A2UI SkyDial"):
///
/// * **Guided** — the three-value strip. The dial is not built at all.
/// * **Easy**   — the strip, plus `SKY DETAIL` at rung 1, collapsed; the dial is
///   built only once the tile is opened.
/// * **Expert** — the dial replaces the strip and sits at rung 0, expanded.
///
/// The dial itself is the server-described A2UI `sky` surface; this widget only
/// decides whether and where it appears, which is exactly the boundary
/// `A2UI_HANDOFF.md` draws: the backend describes the instrument, the client
/// decides the rung.
class ForgeSkyBlock extends ConsumerWidget {
  const ForgeSkyBlock({
    required this.dial,
    required this.reading,
    super.key,
  });

  final Widget dial;
  final ForgeSkyReading reading;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ConsoleMode mode = ConsoleMode.fromId(
      ref.watch(forgeSelectionProvider).consoleMode,
    );

    if (mode.showsSkyDialAtGlance) {
      return KeyedSubtree(key: ForgeKeys.skyDial, child: dial);
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        _SkyStrip(reading: reading),
        if (mode.showsSkyDialBehindDisclosure) ...<Widget>[
          const SizedBox(height: BgSpace.md),
          ConsoleDisclosure(
            key: ForgeKeys.skyDetail,
            label: 'Sky detail',
            // §4: rung-1 tiles default expanded at >= 900, collapsed below.
            initiallyExpanded: ForgeMetrics.isExpanded(context),
            builder: (BuildContext context) =>
                KeyedSubtree(key: ForgeKeys.skyDial, child: dial),
          ),
        ],
      ],
    );
  }
}

/// Three values, one line each on a phone: temperature, pressure + trend,
/// light. Every string is formatted by the backend; a missing surface prints
/// `—` rather than a fabricated number.
class _SkyStrip extends StatelessWidget {
  const _SkyStrip({required this.reading});

  final ForgeSkyReading reading;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    final List<Widget> cells = <Widget>[
      _SkyCell(label: 'TEMP VS NORM', value: reading.tempDisplay),
      _SkyCell(
        label: 'PRESSURE 6H',
        value: reading.trendDisplay,
        caption: reading.trendCaption,
      ),
      _SkyCell(label: 'SUN', value: reading.lightDisplay),
    ];

    return Column(
      key: ForgeKeys.skyStrip,
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            for (int i = 0; i < cells.length; i++) ...<Widget>[
              if (i > 0) const SizedBox(width: BgSpace.md),
              Expanded(child: cells[i]),
            ],
          ],
        ),
        if (reading.stale) ...<Widget>[
          const SizedBox(height: BgSpace.xs),
          Text(
            'Last observation is stale.',
            style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
          ),
        ],
      ],
    );
  }
}

class _SkyCell extends StatelessWidget {
  const _SkyCell({required this.label, required this.value, this.caption});

  final String label;
  final String? value;
  final String? caption;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(
          label,
          style: text.labelSmall?.copyWith(color: colors.onSurfaceVariant),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        Text(
          value ?? '—',
          style: text.titleMedium,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        if (caption != null)
          Text(
            caption!,
            style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
      ],
    );
  }
}
