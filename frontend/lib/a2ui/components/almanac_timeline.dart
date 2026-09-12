/// AlmanacTimeline — past forges as a record, not a feed.
///
/// The Almanac's promise is retrospective: "your rain sound", "your
/// first-frost record". That is a claim about a *series*, so the component is
/// laid out as a dated spine with one entry per forge, grouped by month. A
/// reverse-chronological card grid would have been easier and would have said
/// "recent activity" instead of "record".
///
/// Each entry shows the date, the theme, the headline the rationale gave it
/// at the time, and the pressure trend that produced it — the derivative
/// again, because scanning the trend column down the page is how you notice
/// that all your favourite sets happened on a falling barometer.
///
/// Entries are tappable when the agent attaches an action. This component
/// also supports the ChildList template form: if the server prefers to
/// describe each row as its own component, bind `children` to a template and
/// this widget will render those instead of its built-in row.
library;

import 'package:flutter/material.dart';

import '../../app_theme.dart';
import '../catalog.dart';
import '../messages.dart';

class AlmanacTimelineComponent extends StatelessWidget {
  const AlmanacTimelineComponent({required this.node, super.key});

  final A2uiNode node;

  @override
  Widget build(BuildContext context) {
    // Template form takes precedence: if the agent described the rows, render
    // the agent's rows. Our built-in row is a convenience, not a mandate.
    final childList = node.component.children();
    if (childList.isTemplate || childList.ids.isNotEmpty) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: node.childrenOf(),
      );
    }

    final List<Object?> entries = node.list('entries').isNotEmpty
        ? node.list('entries')
        : node.list('items');

    final String? title = node.string('title');
    final String? retrospective = node.string('retrospective');

    if (entries.isEmpty) {
      return _EmptyAlmanac(
        node: node,
        message: node.stringOr(
          'emptyMessage',
          'Nothing recorded yet. Forge a set and it starts here.',
        ),
      );
    }

    // Group by year-month so the spine gets headers. The wire gives us
    // `created_at` as an ISO string; anything unparseable lands in "Undated"
    // rather than being dropped.
    final Map<String, List<JsonMap>> groups = <String, List<JsonMap>>{};
    for (final Object? raw in entries) {
      final JsonMap? entry = asJsonMap(raw);
      if (entry == null) continue;
      groups.putIfAbsent(_monthKey(entry), () => <JsonMap>[]).add(entry);
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        if (title != null && title.isNotEmpty) ...<Widget>[
          Text(title, style: node.text.headlineSmall),
          const SizedBox(height: BgSpace.sm),
        ],
        if (retrospective != null && retrospective.isNotEmpty) ...<Widget>[
          _RetrospectiveBanner(text: retrospective),
          const SizedBox(height: BgSpace.lg),
        ],
        for (final MapEntry<String, List<JsonMap>> group in groups.entries) ...<Widget>[
          Padding(
            padding: const EdgeInsets.only(
              top: BgSpace.lg,
              bottom: BgSpace.sm,
            ),
            child: Row(
              children: <Widget>[
                Text(group.key.toUpperCase(), style: node.text.labelSmall),
                const SizedBox(width: BgSpace.md),
                Expanded(
                  child: Divider(color: node.colors.outlineVariant),
                ),
                const SizedBox(width: BgSpace.md),
                Text(
                  '${group.value.length}',
                  style: node.text.labelSmall,
                ),
              ],
            ),
          ),
          for (var i = 0; i < group.value.length; i++)
            _AlmanacRow(
              node: node,
              entry: group.value[i],
              isLast: i == group.value.length - 1,
            ),
        ],
      ],
    );
  }

  static const List<String> _months = <String>[
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ];

  static String _monthKey(JsonMap entry) {
    final String? iso = asStringOrNull(entry['created_at']) ??
        asStringOrNull(entry['observed_at']) ??
        asStringOrNull(entry['date']);
    final DateTime? dt = iso == null ? null : DateTime.tryParse(iso);
    if (dt == null) return 'Undated';
    return '${_months[dt.month - 1]} ${dt.year}';
  }
}

class _AlmanacRow extends StatelessWidget {
  const _AlmanacRow({
    required this.node,
    required this.entry,
    required this.isLast,
  });

  final A2uiNode node;
  final JsonMap entry;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = node.colors;
    final TextTheme text = node.text;

    final String? iso = asStringOrNull(entry['created_at']) ??
        asStringOrNull(entry['date']);
    final DateTime? when = iso == null ? null : DateTime.tryParse(iso);

    final String themeId = asStringOrNull(entry['theme_id']) ?? '';
    final String themeName =
        asStringOrNull(entry['theme_name']) ?? _humanise(themeId);
    final String title = asStringOrNull(entry['title']) ??
        asStringOrNull(entry['headline']) ??
        'Untitled set';
    final String? headline =
        asStringOrNull(asJsonMap(entry['rationale'])?['headline']) ??
            asStringOrNull(entry['subtitle']);
    final int trackCount = (asDoubleOrNull(entry['track_count']) ??
            (asJsonList(entry['tracks'])?.length ?? 0))
        .round();

    // The derivative, again. Scanning this column is the point of the page.
    final double? trend = asDoubleOrNull(
          asJsonMap(entry['sky'])?['pressure_trend_6h'],
        ) ??
        asDoubleOrNull(entry['pressure_trend_6h']);

    final action = node.action();
    final bool tappable = action != null && !node.host.busy;

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          // Spine
          SizedBox(
            width: 56,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: <Widget>[
                const SizedBox(height: BgSpace.lg),
                Text(
                  when == null ? '—' : when.day.toString().padLeft(2, '0'),
                  style: text.titleMedium?.copyWith(
                    fontFeatures: const <FontFeature>[
                      FontFeature.tabularFigures(),
                    ],
                  ),
                ),
                Text(
                  when == null ? '' : _weekday(when),
                  style: text.labelSmall?.copyWith(fontSize: 10),
                ),
                const SizedBox(height: BgSpace.sm),
                Expanded(
                  child: Container(
                    width: 1,
                    color: isLast
                        ? Colors.transparent
                        : colors.outlineVariant,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: BgSpace.sm),
              child: Material(
                color: colors.surface,
                borderRadius: BgSpace.brSm,
                child: InkWell(
                  borderRadius: BgSpace.brSm,
                  onTap: tappable
                      ? () => node.fire(
                            action,
                            extra: <String, Object?>{
                              'playlist_id': asStringOrNull(entry['id']),
                            },
                          )
                      : null,
                  child: Container(
                    padding: const EdgeInsets.all(BgSpace.lg),
                    decoration: BoxDecoration(
                      borderRadius: BgSpace.brSm,
                      border: Border.all(color: colors.outlineVariant),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: <Widget>[
                              Text(
                                title,
                                style: text.titleMedium,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              if (headline != null && headline.isNotEmpty) ...[
                                const SizedBox(height: 2),
                                Text(
                                  headline,
                                  style: text.bodySmall,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ],
                              const SizedBox(height: BgSpace.sm),
                              Row(
                                children: <Widget>[
                                  if (themeName.isNotEmpty)
                                    _Pill(label: themeName),
                                  if (trackCount > 0) ...<Widget>[
                                    const SizedBox(width: BgSpace.xs),
                                    _Pill(label: '$trackCount tracks'),
                                  ],
                                ],
                              ),
                            ],
                          ),
                        ),
                        if (trend != null) ...<Widget>[
                          const SizedBox(width: BgSpace.md),
                          _TrendChip(value: trend),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  static const List<String> _days = <String>[
    'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun',
  ];

  static String _weekday(DateTime d) => _days[(d.weekday - 1) % 7];

  static String _humanise(String id) => id.isEmpty
      ? ''
      : id
          .split('_')
          .map((String w) =>
              w.isEmpty ? w : '${w[0].toUpperCase()}${w.substring(1)}')
          .join(' ');
}

/// Compact signed trend, so the column scans vertically.
class _TrendChip extends StatelessWidget {
  const _TrendChip({required this.value});

  final double value;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final Color tone = value.abs() < 0.05
        ? BgPalette.slate400
        : value < 0
            ? colors.primary
            : BgPalette.gold600;

    return Tooltip(
      message: '6-hour pressure trend at forge time',
      child: Container(
        padding:
            const EdgeInsets.symmetric(horizontal: BgSpace.sm, vertical: 4),
        decoration: BoxDecoration(
          borderRadius: BgSpace.brSm,
          border: Border.all(color: tone.withValues(alpha: 0.5)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(
              value.abs() < 0.05
                  ? Icons.remove
                  : value < 0
                      ? Icons.south_east
                      : Icons.north_east,
              size: 12,
              color: tone,
            ),
            const SizedBox(width: 3),
            Text(
              value == 0
                  ? '0.00'
                  : '${value > 0 ? '+' : '−'}${value.abs().toStringAsFixed(2)}',
              style: text.bodySmall?.copyWith(
                color: tone,
                fontSize: 11.5,
                fontFeatures: const <FontFeature>[
                  FontFeature.tabularFigures(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// "Your rain sound." The retrospective line the agent computed.
class _RetrospectiveBanner extends StatelessWidget {
  const _RetrospectiveBanner({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final TextTheme t = Theme.of(context).textTheme;
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border(
          left: const BorderSide(color: BgPalette.gold500, width: 3),
          top: BorderSide(color: colors.outlineVariant),
          right: BorderSide(color: colors.outlineVariant),
          bottom: BorderSide(color: colors.outlineVariant),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text('RETROSPECTIVE', style: t.labelSmall),
          const SizedBox(height: BgSpace.xs),
          Text(text, style: t.bodyLarge),
        ],
      ),
    );
  }
}

class _EmptyAlmanac extends StatelessWidget {
  const _EmptyAlmanac({required this.node, required this.message});

  final A2uiNode node;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(BgSpace.xxl),
      decoration: BoxDecoration(
        color: node.colors.surface,
        borderRadius: BgSpace.br,
        border: Border.all(color: node.colors.outlineVariant),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(Icons.auto_stories_outlined,
              size: 28, color: node.colors.onSurfaceVariant),
          const SizedBox(height: BgSpace.md),
          Text(
            message,
            textAlign: TextAlign.center,
            style: node.text.bodyMedium?.copyWith(
              color: node.colors.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 11.5),
      ),
    );
  }
}
