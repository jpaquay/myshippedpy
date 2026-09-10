/// TrackList — the scored tracks, with their arc made visible.
///
/// A ScoredTrack carries a `role` ("opener", "build", "peak", "descent",
/// "closer", "body") and a `position`. That sequence is the shape of the set,
/// and it is the thing a flat list destroys. So each row carries a role
/// marker in a fixed-width gutter, and the rail running down that gutter
/// makes the arc legible at a glance: you can see where the peak is without
/// reading a word.
///
/// The `why` string is per-track explanation. It is collapsed by default —
/// twelve paragraphs of reasoning is not a playlist — but it is one tap away
/// and it is never omitted. The explanation is the product.
///
/// Feedback ("loved" / "skipped") fires the agent's action. We do not
/// optimistically mark the row: the agent owns whether the signal was
/// accepted, and pretending otherwise would put us back in the business of
/// deciding what interactions mean.
library;

import 'package:flutter/material.dart';

import '../../app_theme.dart';
import '../catalog.dart';
import '../messages.dart';

/// The narrative roles a track can occupy in a set.
enum TrackRole {
  opener('opener', 'Opener', Icons.play_arrow_rounded),
  build('build', 'Build', Icons.trending_up_rounded),
  peak('peak', 'Peak', Icons.change_history_rounded),
  descent('descent', 'Descent', Icons.trending_down_rounded),
  closer('closer', 'Closer', Icons.stop_rounded),
  body('body', 'Body', Icons.remove_rounded);

  const TrackRole(this.key, this.label, this.icon);

  final String key;
  final String label;
  final IconData icon;

  static TrackRole from(String? raw) {
    for (final TrackRole r in TrackRole.values) {
      if (r.key == raw) return r;
    }
    return TrackRole.body;
  }

  /// Only the peak gets the gold. Rationing the accent is what makes it read
  /// as significant rather than decorative.
  Color tone(ColorScheme colors) => switch (this) {
        TrackRole.peak => BgPalette.gold600,
        TrackRole.opener || TrackRole.closer => colors.primary,
        _ => BgPalette.slate400,
      };
}

class TrackListComponent extends StatelessWidget {
  const TrackListComponent({required this.node, super.key});

  final A2uiNode node;

  @override
  Widget build(BuildContext context) {
    final List<Object?> tracks = node.list('tracks').isNotEmpty
        ? node.list('tracks')
        : node.list('items');

    if (tracks.isEmpty) {
      return A2uiPlaceholder.binding(
        componentId: node.id,
        detail: 'no tracks bound to "tracks"',
      );
    }

    final String? title = node.string('title');
    final String? subtitle = node.string('subtitle');

    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          if (title != null && title.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  BgSpace.xl, BgSpace.xl, BgSpace.xl, BgSpace.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Text(title, style: node.text.headlineSmall),
                  if (subtitle != null && subtitle.isNotEmpty) ...<Widget>[
                    const SizedBox(height: BgSpace.xs),
                    Text(
                      subtitle,
                      style: node.text.bodyMedium?.copyWith(
                        color: node.colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          Divider(color: node.colors.outlineVariant),
          for (var i = 0; i < tracks.length; i++)
            if (asJsonMap(tracks[i]) case final JsonMap track)
              _TrackRow(
                node: node,
                track: track,
                index: i,
                isFirst: i == 0,
                isLast: i == tracks.length - 1,
              ),
          Divider(color: node.colors.outlineVariant),
          Padding(
            padding: const EdgeInsets.all(BgSpace.lg),
            child: Text(
              '${tracks.length} tracks · '
              '${_totalDuration(tracks)}',
              style: node.text.bodySmall,
            ),
          ),
        ],
      ),
    );
  }

  static String _totalDuration(List<Object?> tracks) {
    var ms = 0;
    for (final Object? t in tracks) {
      final JsonMap? row = asJsonMap(t);
      final JsonMap? inner = asJsonMap(row?['track']) ?? row;
      ms += (asDoubleOrNull(inner?['duration_ms']) ?? 0).round();
    }
    final int minutes = ms ~/ 60000;
    if (minutes < 60) return '$minutes min';
    return '${minutes ~/ 60} h ${minutes % 60} min';
  }
}

class _TrackRow extends StatefulWidget {
  const _TrackRow({
    required this.node,
    required this.track,
    required this.index,
    required this.isFirst,
    required this.isLast,
  });

  final A2uiNode node;
  final JsonMap track;
  final int index;
  final bool isFirst;
  final bool isLast;

  @override
  State<_TrackRow> createState() => _TrackRowState();
}

class _TrackRowState extends State<_TrackRow> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final A2uiNode node = widget.node;
    final ColorScheme colors = node.colors;
    final TextTheme text = node.text;

    // ScoredTrack nests the Track under `track`; tolerate a flattened shape.
    final JsonMap scored = widget.track;
    final JsonMap inner = asJsonMap(scored['track']) ?? scored;

    final String title = asStringOrNull(inner['title']) ?? 'Untitled';
    final String artist = asStringOrNull(inner['artist']) ?? 'Unknown artist';
    final String? album = asStringOrNull(inner['album']);
    final int durationMs = (asDoubleOrNull(inner['duration_ms']) ?? 0).round();
    final String? why = asStringOrNull(scored['why']);
    final TrackRole role = TrackRole.from(asStringOrNull(scored['role']));
    final double? score = asDoubleOrNull(scored['score']);
    final String? trackKey = asStringOrNull(scored['track_key']) ??
        asStringOrNull(inner['spotify_uri']) ??
        asStringOrNull(inner['lastfm_url']);

    final Color tone = role.tone(colors);
    final bool isPeak = role == TrackRole.peak;

    return Container(
      color: isPeak ? BgPalette.gold50.withValues(alpha: 0.55) : null,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          InkWell(
            onTap: (why == null || why.isEmpty)
                ? null
                : () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: BgSpace.lg,
                vertical: BgSpace.md,
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: <Widget>[
                  // The arc gutter: a continuous rail with a role node on it.
                  _RoleGutter(
                    role: role,
                    tone: tone,
                    isFirst: widget.isFirst,
                    isLast: widget.isLast,
                  ),
                  const SizedBox(width: BgSpace.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        Text(
                          title,
                          style: text.titleMedium?.copyWith(
                            fontWeight:
                                isPeak ? FontWeight.w700 : FontWeight.w600,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        const SizedBox(height: 1),
                        Text(
                          album == null || album.isEmpty
                              ? artist
                              : '$artist · $album',
                          style: text.bodySmall,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: BgSpace.md),
                  if (score != null)
                    Padding(
                      padding: const EdgeInsets.only(right: BgSpace.md),
                      child: Tooltip(
                        message: 'Composite score',
                        child: Text(
                          score.toStringAsFixed(2),
                          style: text.bodySmall?.copyWith(
                            fontFeatures: const <FontFeature>[
                              FontFeature.tabularFigures(),
                            ],
                          ),
                        ),
                      ),
                    ),
                  Text(
                    _fmtDuration(durationMs),
                    style: text.bodySmall?.copyWith(
                      fontFeatures: const <FontFeature>[
                        FontFeature.tabularFigures(),
                      ],
                    ),
                  ),
                  if (why != null && why.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(left: BgSpace.xs),
                      child: Icon(
                        _expanded ? Icons.expand_less : Icons.expand_more,
                        size: 18,
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                ],
              ),
            ),
          ),
          AnimatedCrossFade(
            duration: const Duration(milliseconds: 160),
            crossFadeState: _expanded
                ? CrossFadeState.showSecond
                : CrossFadeState.showFirst,
            firstChild: const SizedBox(width: double.infinity),
            secondChild: _WhyPanel(
              node: node,
              why: why ?? '',
              role: role,
              tone: tone,
              trackKey: trackKey,
              externalUrl: asStringOrNull(inner['spotify_uri']) ??
                  asStringOrNull(inner['lastfm_url']),
              tags: asStringList(inner['tags']),
              metrics: <String, double?>{
                'Sonic distance': asDoubleOrNull(scored['sonic_distance']),
                'Taste affinity': asDoubleOrNull(scored['taste_affinity']),
                'Corridor fit': asDoubleOrNull(scored['corridor_fit']),
                'Novelty': asDoubleOrNull(scored['novelty']),
              },
            ),
          ),
        ],
      ),
    );
  }

  static String _fmtDuration(int ms) {
    if (ms <= 0) return '—';
    final int totalSeconds = ms ~/ 1000;
    return '${totalSeconds ~/ 60}:${(totalSeconds % 60).toString().padLeft(2, '0')}';
  }
}

/// The rail plus the role node. Draws a continuous vertical line through the
/// list so the sequence reads as one arc rather than N independent rows.
class _RoleGutter extends StatelessWidget {
  const _RoleGutter({
    required this.role,
    required this.tone,
    required this.isFirst,
    required this.isLast,
  });

  final TrackRole role;
  final Color tone;
  final bool isFirst;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final bool emphasised = role == TrackRole.peak;

    return Tooltip(
      message: role.label,
      child: SizedBox(
        width: 26,
        height: 44,
        child: Stack(
          alignment: Alignment.center,
          children: <Widget>[
            Positioned(
              top: isFirst ? 12 : 0,
              bottom: isLast ? 12 : 0,
              width: 1,
              child: ColoredBox(color: colors.outlineVariant),
            ),
            Container(
              width: emphasised ? 22 : 18,
              height: emphasised ? 22 : 18,
              decoration: BoxDecoration(
                color: colors.surface,
                shape: BoxShape.circle,
                border: Border.all(color: tone, width: emphasised ? 2 : 1.2),
              ),
              child: Icon(role.icon, size: emphasised ? 12 : 10, color: tone),
            ),
          ],
        ),
      ),
    );
  }
}

/// The per-track explanation, plus the score breakdown and the feedback
/// affordances.
class _WhyPanel extends StatelessWidget {
  const _WhyPanel({
    required this.node,
    required this.why,
    required this.role,
    required this.tone,
    required this.metrics,
    required this.tags,
    this.trackKey,
    this.externalUrl,
  });

  final A2uiNode node;
  final String why;
  final TrackRole role;
  final Color tone;
  final Map<String, double?> metrics;
  final List<String> tags;
  final String? trackKey;
  final String? externalUrl;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = node.colors;
    final TextTheme text = node.text;
    final feedback = node.action('feedbackAction');

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(
          BgSpace.lg + 26 + BgSpace.md, 0, BgSpace.lg, BgSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Container(
            padding: const EdgeInsets.only(left: BgSpace.md),
            decoration: BoxDecoration(
              border: Border(left: BorderSide(color: tone, width: 2)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(role.label.toUpperCase(), style: text.labelSmall),
                const SizedBox(height: BgSpace.xs),
                Text(why, style: text.bodyMedium),
              ],
            ),
          ),
          const SizedBox(height: BgSpace.md),
          Wrap(
            spacing: BgSpace.lg,
            runSpacing: BgSpace.sm,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: <Widget>[
              for (final MapEntry<String, double?> m in metrics.entries)
                if (m.value != null)
                  _Metric(label: m.key, value: m.value!),
            ],
          ),
          if (tags.isNotEmpty) ...<Widget>[
            const SizedBox(height: BgSpace.sm),
            Text(
              tags.take(8).join(' · '),
              style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
            ),
          ],
          const SizedBox(height: BgSpace.md),
          Row(
            children: <Widget>[
              if (feedback != null) ...<Widget>[
                OutlinedButton.icon(
                  onPressed: node.host.busy
                      ? null
                      : () => node.fire(
                            feedback,
                            extra: <String, Object?>{
                              'track_key': trackKey,
                              'signal': 'loved',
                            },
                          ),
                  icon: const Icon(Icons.favorite_border, size: 16),
                  label: const Text('Loved'),
                ),
                const SizedBox(width: BgSpace.sm),
                OutlinedButton.icon(
                  onPressed: node.host.busy
                      ? null
                      : () => node.fire(
                            feedback,
                            extra: <String, Object?>{
                              'track_key': trackKey,
                              'signal': 'skipped',
                            },
                          ),
                  icon: const Icon(Icons.skip_next_outlined, size: 16),
                  label: const Text('Skipped'),
                ),
              ],
              const Spacer(),
              if (externalUrl != null && externalUrl!.isNotEmpty)
                Text(
                  externalUrl!,
                  style: text.bodySmall?.copyWith(
                    color: colors.onSurfaceVariant,
                    fontSize: 11.5,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});

  final String label;
  final double value;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(label.toUpperCase(), style: text.labelSmall?.copyWith(fontSize: 10)),
        const SizedBox(height: 2),
        SizedBox(
          width: 92,
          child: Row(
            children: <Widget>[
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(2),
                  child: LinearProgressIndicator(
                    value: value.clamp(0.0, 1.0),
                    minHeight: 4,
                    backgroundColor: colors.surfaceContainer,
                    valueColor:
                        const AlwaysStoppedAnimation<Color>(BgPalette.slate500),
                  ),
                ),
              ),
              const SizedBox(width: BgSpace.xs),
              Text(
                value.toStringAsFixed(2),
                style: text.bodySmall?.copyWith(
                  fontSize: 11,
                  fontFeatures: const <FontFeature>[
                    FontFeature.tabularFigures(),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
