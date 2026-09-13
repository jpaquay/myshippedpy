import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../api/models.dart';
import '../../../app_theme.dart';
import '../../../providers.dart';
import 'console_tokens.dart';

/// Expert-only telemetry badges (§5.2).
///
/// Every number comes from `GET /api/health`'s telemetry block. When the
/// backend is unreachable the provider yields `HealthStatus.unknown`, whose
/// telemetry is null, and each badge shows `—`: the degraded path prints a dash,
/// never a plausible-looking zero (§2 rule 4).
///
/// Note the spec asks for "model, latency, tokens". `/api/health` publishes no
/// model name — see the report for the backend field that would be needed —
/// so the third badge is the call count, which it does publish.
class ConsoleTelemetryRow extends ConsumerWidget {
  const ConsoleTelemetryRow({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final HealthStatus? health = ref.watch(healthProvider).valueOrNull;
    final TelemetrySummaryModel? t = health?.telemetry;

    String latency() {
      if (t == null || t.avgLatencyMs <= 0) return '—';
      return '${t.avgLatencyMs.round()} ms';
    }

    String tokens() {
      if (t == null || t.totalTokens <= 0) return '—';
      return '${t.totalTokens}';
    }

    String calls() {
      if (t == null) return '—';
      return '${t.totalAiCalls}';
    }

    return Wrap(
      key: ForgeKeys.telemetryRow,
      spacing: BgSpace.lg,
      runSpacing: BgSpace.sm,
      children: <Widget>[
        _TelemetryBadge(
          icon: Icons.speed_rounded,
          label: 'AVG LATENCY',
          value: latency(),
        ),
        _TelemetryBadge(
          icon: Icons.data_usage_rounded,
          label: 'TOKENS',
          value: tokens(),
        ),
        _TelemetryBadge(
          icon: Icons.bolt_rounded,
          label: 'AI CALLS',
          value: calls(),
        ),
      ],
    );
  }
}

class _TelemetryBadge extends StatelessWidget {
  const _TelemetryBadge({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Icon(icon, size: 14, color: colors.onSurfaceVariant),
        const SizedBox(width: BgSpace.xs),
        Text(
          label,
          style: text.labelSmall?.copyWith(color: colors.onSurfaceVariant),
        ),
        const SizedBox(width: BgSpace.xs),
        Text(value, style: text.labelMedium),
      ],
    );
  }
}
