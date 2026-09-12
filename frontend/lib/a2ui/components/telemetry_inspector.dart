/// TelemetryInspector — A2UI v1.0 component for live AI Telemetry, Trajectories,
/// Sessions, and Semantic Memories.
library;

import 'package:flutter/material.dart';

import '../../app_theme.dart';
import '../catalog.dart';
import '../messages.dart';

class TelemetryInspectorA2uiWidget extends StatelessWidget {
  const TelemetryInspectorA2uiWidget({required this.node, super.key});

  final A2uiNode node;

  @override
  Widget build(BuildContext context) {
    final String title = node.stringOr(
      'title',
      'AI Telemetry & Trajectory Inspector',
    );
    final String subtitle = node.stringOr(
      'subtitle',
      'End-to-end observability across Vertex AI Gemini 2.5 Flash & fallback pipelines',
    );

    final int totalCalls = (node.number('totalCalls') ??
            node.number('total_ai_calls') ??
            0)
        .round();
    final int totalTokens = (node.number('totalTokens') ??
            node.number('total_tokens') ??
            0)
        .round();
    final int activeSessions = (node.number('activeSessions') ??
            node.number('active_sessions') ??
            0)
        .round();
    final int storedMemories = (node.number('storedMemories') ??
            node.number('stored_memories') ??
            0)
        .round();
    final double avgLatencyMs = node.number('avgLatencyMs') ??
        node.number('avg_latency_ms') ??
        0.0;

    // Check if template or explicit child components exist under 'entries' or 'children'
    final ChildList entriesChildList = node.component.children('entries');
    final ChildList defaultChildList = node.component.children('children');
    final bool hasTemplateOrChildren = entriesChildList.isTemplate ||
        entriesChildList.ids.isNotEmpty ||
        defaultChildList.isTemplate ||
        defaultChildList.ids.isNotEmpty;

    final List<Object?> rawList = node.list('entries').isNotEmpty
        ? node.list('entries')
        : (node.list('trajectories').isNotEmpty
            ? node.list('trajectories')
            : node.list('items'));

    return Container(
      decoration: BoxDecoration(
        color: node.colors.surfaceContainerLow,
        borderRadius: BgSpace.br,
        border: Border.all(color: node.colors.outlineVariant),
      ),
      padding: const EdgeInsets.all(BgSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          // Header
          Row(
            children: <Widget>[
              Container(
                padding: const EdgeInsets.all(BgSpace.sm),
                decoration: BoxDecoration(
                  color: node.colors.primary.withValues(alpha: 0.14),
                  borderRadius: BgSpace.brSm,
                  border: Border.all(
                    color: node.colors.primary.withValues(alpha: 0.35),
                  ),
                ),
                child: Icon(
                  Icons.radar,
                  color: node.colors.primary,
                  size: 20,
                ),
              ),
              const SizedBox(width: BgSpace.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      title,
                      style: node.text.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: node.text.bodySmall?.copyWith(
                        color: node.colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.lg),

          // KPI Summary Strip
          Wrap(
            spacing: BgSpace.md,
            runSpacing: BgSpace.md,
            children: <Widget>[
              _KpiBadge(
                label: 'AI CALLS',
                value: '$totalCalls',
                icon: Icons.bolt,
                accent: node.colors.primary,
              ),
              _KpiBadge(
                label: 'TOTAL TOKENS',
                value: '$totalTokens',
                icon: Icons.token_outlined,
                accent: BgPalette.gold500,
              ),
              _KpiBadge(
                label: 'AVG LATENCY',
                value: '${avgLatencyMs.toStringAsFixed(1)} ms',
                icon: Icons.speed,
                accent: BgPalette.ok,
              ),
              _KpiBadge(
                label: 'SESSIONS',
                value: '$activeSessions',
                icon: Icons.hub_outlined,
                accent: BgPalette.sky500,
              ),
              _KpiBadge(
                label: 'MEMORIES',
                value: '$storedMemories',
                icon: Icons.psychology_outlined,
                accent: Colors.purpleAccent,
              ),
            ],
          ),
          const SizedBox(height: BgSpace.lg),
          Divider(color: node.colors.outlineVariant),
          const SizedBox(height: BgSpace.md),

          // Entries list
          if (hasTemplateOrChildren)
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: entriesChildList.isTemplate || entriesChildList.ids.isNotEmpty
                  ? node.childrenOf('entries')
                  : node.childrenOf('children'),
            )
          else if (rawList.isNotEmpty)
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                for (final Object? raw in rawList)
                  if (asJsonMap(raw) case final JsonMap m)
                    Padding(
                      padding: const EdgeInsets.only(bottom: BgSpace.sm),
                      child: _TelemetryEntryCard(entry: m, node: node),
                    ),
              ],
            )
          else
            Container(
              padding: const EdgeInsets.all(BgSpace.lg),
              decoration: BoxDecoration(
                color: node.colors.surfaceContainer,
                borderRadius: BgSpace.brSm,
              ),
              child: Text(
                'No AI trajectories captured in this surface yet.',
                style: node.text.bodySmall?.copyWith(
                  color: node.colors.onSurfaceVariant,
                ),
                textAlign: TextAlign.center,
              ),
            ),
        ],
      ),
    );
  }
}

class TelemetryEntryA2uiWidget extends StatelessWidget {
  const TelemetryEntryA2uiWidget({required this.node, super.key});

  final A2uiNode node;

  @override
  Widget build(BuildContext context) {
    final String trajectoryId = node.stringOr(
      'trajectoryId',
      node.stringOr('trajectory_id', 'traj_000'),
    );
    final String traceId = node.stringOr(
      'traceId',
      node.stringOr('trace_id', ''),
    );
    final String operation = node.stringOr(
      'operation',
      node.stringOr('endpoint', ''),
    );
    final String surface = node.stringOr('surface', 'advisor');
    final String model = node.stringOr(
      'model',
      node.stringOr('requested_model', 'gemini-2.5-flash'),
    );
    final String executionPath = node.stringOr(
      'executionPath',
      node.stringOr('execution_path', 'vertex-ai'),
    );
    final double latencyMs =
        node.number('latencyMs') ?? node.number('latency_ms') ?? 0.0;
    final int totalTokens = (node.number('totalTokens') ??
            node.number('total_tokens') ??
            0)
        .round();
    final String status = node.stringOr('status', '200 OK');
    final String createdAt = node.stringOr(
      'createdAt',
      node.stringOr('created_at', ''),
    );
    final String promptPreview = node.stringOr(
      'promptPreview',
      node.stringOr('prompt', node.stringOr('user_prompt', '')),
    );
    final String responsePreview = node.stringOr(
      'responsePreview',
      node.stringOr('output', node.stringOr('raw_model_response', '')),
    );
    final List<String> toolBadges = node.strings('toolBadges').isNotEmpty
        ? node.strings('toolBadges')
        : node.strings('tool_badges');

    final VoidCallback? onOpen = node.onTap('onOpen');

    final JsonMap syntheticMap = <String, Object?>{
      'trajectory_id': trajectoryId,
      'trace_id': traceId,
      'operation': operation,
      'surface': surface,
      'requested_model': model,
      'execution_path': executionPath,
      'latency_ms': latencyMs,
      'total_tokens': totalTokens,
      'status': status,
      'created_at': createdAt,
      'user_prompt': promptPreview,
      'raw_model_response': responsePreview,
      'tool_badges': toolBadges,
    };

    return _TelemetryEntryCard(
      entry: syntheticMap,
      node: node,
      onTap: onOpen,
    );
  }
}

class _KpiBadge extends StatelessWidget {
  const _KpiBadge({
    required this.label,
    required this.value,
    required this.icon,
    required this.accent,
  });

  final String label;
  final String value;
  final IconData icon;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: BgSpace.md,
        vertical: BgSpace.sm,
      ),
      decoration: BoxDecoration(
        color: colors.surfaceContainer,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(icon, size: 16, color: accent),
          const SizedBox(width: BgSpace.sm),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                label,
                style: text.labelSmall?.copyWith(
                  fontSize: 10,
                  color: colors.onSurfaceVariant,
                  letterSpacing: 0.8,
                ),
              ),
              Text(
                value,
                style: text.titleSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TelemetryEntryCard extends StatelessWidget {
  const _TelemetryEntryCard({
    required this.entry,
    required this.node,
    this.onTap,
  });

  final JsonMap entry;
  final A2uiNode node;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final String id = asStringOrNull(entry['trajectory_id']) ??
        asStringOrNull(entry['trajectoryId']) ??
        'traj';
    final String traceId = asStringOrNull(entry['trace_id']) ??
        asStringOrNull(entry['traceId']) ??
        '';
    final String operation = asStringOrNull(entry['operation']) ??
        asStringOrNull(entry['endpoint']) ??
        '';
    final String surface = asStringOrNull(entry['surface']) ?? 'advisor';
    final String path = asStringOrNull(entry['execution_path']) ??
        asStringOrNull(entry['executionPath']) ??
        'vertex-ai';
    final double latency = asDoubleOrNull(entry['latency_ms']) ??
        asDoubleOrNull(entry['latencyMs']) ??
        0.0;
    final int tokens = (asDoubleOrNull(entry['total_tokens']) ??
            asDoubleOrNull(entry['totalTokens']) ??
            asDoubleOrNull(asJsonMap(entry['token_usage'])?['total_tokens']) ??
            0)
        .round();
    final String prompt = asStringOrNull(entry['user_prompt']) ??
        asStringOrNull(entry['promptPreview']) ??
        '';

    final bool isVertex = path.toLowerCase().contains('vertex');
    final Color pathColor = isVertex ? BgPalette.ok : BgPalette.gold500;

    return InkWell(
      onTap: onTap,
      borderRadius: BgSpace.brSm,
      child: Container(
        padding: const EdgeInsets.all(BgSpace.md),
        decoration: BoxDecoration(
          color: node.colors.surfaceContainer,
          borderRadius: BgSpace.brSm,
          border: Border.all(color: node.colors.outlineVariant),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Wrap(
              spacing: BgSpace.sm,
              runSpacing: BgSpace.xs,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: <Widget>[
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: BgSpace.sm,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: node.colors.primary.withValues(alpha: 0.14),
                    borderRadius: BgSpace.brSm,
                  ),
                  child: Text(
                    surface.toUpperCase(),
                    style: node.text.labelSmall?.copyWith(
                      color: node.colors.primary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: BgSpace.sm,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: pathColor.withValues(alpha: 0.14),
                    borderRadius: BgSpace.brSm,
                  ),
                  child: Text(
                    path,
                    style: node.text.labelSmall?.copyWith(
                      color: pathColor,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (operation.isNotEmpty)
                  Text(
                    operation,
                    style: node.text.labelMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                Text(
                  '${latency.toStringAsFixed(0)} ms',
                  style: node.text.labelSmall?.copyWith(
                    fontFamily: 'monospace',
                    color: node.colors.onSurfaceVariant,
                  ),
                ),
                Text(
                  '$tokens tok',
                  style: node.text.labelSmall?.copyWith(
                    fontFamily: 'monospace',
                    color: node.colors.onSurfaceVariant,
                  ),
                ),
              ],
            ),
            if (prompt.isNotEmpty) ...<Widget>[
              const SizedBox(height: BgSpace.xs),
              Text(
                prompt,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: node.text.bodySmall,
              ),
            ],
            if (traceId.isNotEmpty) ...<Widget>[
              const SizedBox(height: BgSpace.xs),
              Text(
                'trace: $traceId',
                style: node.text.labelSmall?.copyWith(
                  fontFamily: 'monospace',
                  color: node.colors.onSurfaceVariant,
                  fontSize: 11,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
