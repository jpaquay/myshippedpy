// Data Viz — the answer card.
//
// One card per question, newest first, exactly the anatomy drawn in
// UX_IA_SPEC.md §3.4:
//
//   question (titleMedium, 2 lines max)
//   ──────────────────────────────────  1 px rule
//   answer sentence (bodyMedium)  |  loading shimmer  |  error notice
//   [ chart, fixed height ]       |  chart skeleton   |  —
//   SOURCE QUERY  ⌄               rung 1, collapsed (auto-expanded on failure)
//   Ask a follow-up · Pin to dashboard
//
// All four states live in this one widget on purpose: they are the same card
// at different moments, and building them as separate screens is how a
// loading state ends up a different shape from the answer that replaces it.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app_theme.dart';
import '../../widgets/bg_disclosure.dart';
import 'dataviz_answer_chart.dart';
import 'dataviz_conversation.dart';
import 'dataviz_models.dart';
import 'dataviz_qna_transport.dart';

class DataVizAnswerCard extends StatelessWidget {
  const DataVizAnswerCard({
    super.key,
    required this.turn,
    required this.isExpanded,
    required this.onRetry,
    required this.onCancel,
    required this.onTogglePin,
    required this.onAskFollowUp,
    required this.onWiden,
  });

  final DataVizTurn turn;
  final bool isExpanded;
  final VoidCallback onRetry;
  final VoidCallback onCancel;
  final VoidCallback onTogglePin;

  /// Puts the question back in the entry field, focused, ready to edit.
  final ValueChanged<String> onAskFollowUp;

  /// The single action on the no-rows card.
  final ValueChanged<String> onWiden;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;

    return Container(
      margin: const EdgeInsets.only(bottom: BgSpace.md),
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BgSpace.br,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            '“${turn.question}”',
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.titleMedium,
          ),
          const SizedBox(height: BgSpace.md),
          Divider(height: 1, thickness: 1, color: colors.outlineVariant),
          const SizedBox(height: BgSpace.md),
          ..._body(context),
          if (turn.generatedSql.isNotEmpty) ...<Widget>[
            const SizedBox(height: BgSpace.md),
            SourceQueryDisclosure(
              sql: turn.generatedSql,
              engine: turn.answer?.dataEngine ?? '',
              rowCount: turn.answer?.rowCount ?? 0,
              startsExpanded: turn.sourceQueryStartsExpanded,
            ),
          ],
          const SizedBox(height: BgSpace.sm),
          _actions(context),
        ],
      ),
    );
  }

  // -------------------------------------------------------------------------

  List<Widget> _body(BuildContext context) {
    switch (turn.status) {
      case DataVizTurnStatus.loading:
        return <Widget>[_LoadingBody(turn: turn, isExpanded: isExpanded)];
      case DataVizTurnStatus.failed:
        return <Widget>[
          _ErrorNotice(
            summary: turn.failureSummary,
            recovery: turn.failureRecovery,
            onRetry: onRetry,
          ),
        ];
      case DataVizTurnStatus.noRows:
        return <Widget>[
          _NoRowsBody(
            narrowing: turn.narrowing,
            onWiden: () => onWiden(widenToAllWeather(turn.question)),
          ),
        ];
      case DataVizTurnStatus.answered:
        return _answeredBody(context);
    }
  }

  List<Widget> _answeredBody(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final DataVizQnAResponseModel? a = turn.answer;
    final QnaChartSpecModel? spec = a?.chartSpec;

    return <Widget>[
      Text(
        a?.answerText ?? '',
        style: theme.textTheme.bodyMedium,
      ),
      if (spec != null && spec.hasData) ...<Widget>[
        const SizedBox(height: BgSpace.md),
        if (spec.title.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: BgSpace.sm),
            child: Text(
              spec.title.toUpperCase(),
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            ),
          ),
        AnswerChart(spec: spec, isExpanded: isExpanded),
      ],
    ];
  }

  Widget _actions(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final bool busy = turn.isLoading;

    return Wrap(
      spacing: BgSpace.lg,
      runSpacing: BgSpace.xs,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: <Widget>[
        if (busy)
          // §3.4: "Cancel is available for the whole duration."
          _TextAction(
            label: 'Cancel',
            icon: Icons.close,
            onPressed: onCancel,
          )
        else ...<Widget>[
          _TextAction(
            label: 'Ask a follow-up',
            icon: Icons.subdirectory_arrow_right,
            onPressed: () => onAskFollowUp(turn.question),
          ),
          if (turn.status == DataVizTurnStatus.answered)
            _TextAction(
              label: turn.pinned ? 'Unpin from dashboard' : 'Pin to dashboard',
              icon: turn.pinned ? Icons.push_pin : Icons.push_pin_outlined,
              onPressed: onTogglePin,
            ),
        ],
        if (!busy && (turn.answer?.modelUsed.isNotEmpty ?? false))
          Text(
            turn.answer!.modelUsed,
            style: theme.textTheme.labelSmall
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Loading — never a spinner over nothing. The question is already on screen,
// the answer is a three-line shimmer at the height the real answer will be,
// the chart slot is a skeleton of the real chart, and the status line names
// the stage the pipeline is actually in.
// ---------------------------------------------------------------------------

class _LoadingBody extends StatelessWidget {
  const _LoadingBody({required this.turn, required this.isExpanded});

  final DataVizTurn turn;
  final bool isExpanded;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const _ShimmerLine(widthFactor: 1.0),
        const SizedBox(height: BgSpace.sm),
        const _ShimmerLine(widthFactor: 0.92),
        const SizedBox(height: BgSpace.sm),
        const _ShimmerLine(widthFactor: 0.54),
        const SizedBox(height: BgSpace.md),
        AnswerChartSkeleton(isExpanded: isExpanded),
        const SizedBox(height: BgSpace.md),
        Row(
          children: <Widget>[
            SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(
                strokeWidth: 1.6,
                color: colors.onSurfaceVariant,
              ),
            ),
            const SizedBox(width: BgSpace.sm),
            Text(
              turn.phase.label,
              key: const ValueKey<String>('dataviz-loading-status'),
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: colors.onSurfaceVariant),
            ),
          ],
        ),
      ],
    );
  }
}

class _ShimmerLine extends StatefulWidget {
  const _ShimmerLine({required this.widthFactor});

  final double widthFactor;

  @override
  State<_ShimmerLine> createState() => _ShimmerLineState();
}

class _ShimmerLineState extends State<_ShimmerLine>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return FractionallySizedBox(
      alignment: Alignment.centerLeft,
      widthFactor: widget.widthFactor,
      child: AnimatedBuilder(
        animation: _c,
        builder: (BuildContext context, Widget? child) {
          return Container(
            height: 11,
            decoration: BoxDecoration(
              color: colors.outlineVariant
                  .withValues(alpha: 0.35 + (0.35 * _c.value)),
              borderRadius: BgSpace.brSm,
            ),
          );
        },
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Error — what failed, and what to try. Never collapsed (§2, rule 2).
// ---------------------------------------------------------------------------

class _ErrorNotice extends StatelessWidget {
  const _ErrorNotice({
    required this.summary,
    required this.recovery,
    required this.onRetry,
  });

  final String summary;
  final String recovery;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);

    return Container(
      key: const ValueKey<String>('dataviz-error-notice'),
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        borderRadius: BgSpace.brSm,
        border: Border.all(color: BgPalette.danger.withValues(alpha: 0.45)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const Icon(Icons.error_outline, size: 16, color: BgPalette.danger),
              const SizedBox(width: BgSpace.sm),
              Expanded(
                child: Text(
                  summary,
                  style: theme.textTheme.bodyMedium
                      ?.copyWith(color: BgPalette.danger),
                ),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.sm),
          Padding(
            padding: const EdgeInsets.only(left: 24),
            child: Text(recovery, style: theme.textTheme.bodySmall),
          ),
          const SizedBox(height: BgSpace.md),
          Align(
            alignment: Alignment.centerLeft,
            child: Padding(
              padding: const EdgeInsets.only(left: 24),
              child: OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Retry'),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// No rows — a narrow question, not a broken agent. One action.
// ---------------------------------------------------------------------------

class _NoRowsBody extends StatelessWidget {
  const _NoRowsBody({required this.narrowing, required this.onWiden});

  final String narrowing;
  final VoidCallback onWiden;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;

    return Column(
      key: const ValueKey<String>('dataviz-no-rows'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text('Nothing matched that.', style: theme.textTheme.bodyMedium),
        if (narrowing.isNotEmpty) ...<Widget>[
          const SizedBox(height: BgSpace.xs),
          Text(
            'The query ran, and $narrowing narrowed it to zero rows.',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: colors.onSurfaceVariant),
          ),
        ],
        const SizedBox(height: BgSpace.md),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: onWiden,
            icon: const Icon(Icons.unfold_more, size: 16),
            label: const Text('Widen to all weather'),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// SOURCE QUERY — rung 1. The trust affordance §3.4 says must exist.
//
// The rung-1 chrome is the shared `BgDisclosure` (§2); what is left here is
// the part that is genuinely Data Viz's: mapping an engine id to a provenance
// line, and rendering the SQL body.
// ---------------------------------------------------------------------------

class SourceQueryDisclosure extends StatelessWidget {
  const SourceQueryDisclosure({
    super.key,
    required this.sql,
    required this.engine,
    required this.rowCount,
    this.startsExpanded = false,
  });

  final String sql;
  final String engine;
  final int rowCount;
  final bool startsExpanded;

  String get _provenance {
    switch (engine) {
      case 'bigquery_data_qna_v1beta':
        return 'Gemini Data Analytics · BigQuery';
      case 'local_olap_synthesizer':
        return 'Local OLAP synthesizer · offline';
      case '':
        return '';
      default:
        return engine;
    }
  }

  @override
  Widget build(BuildContext context) {
    return BgDisclosure(
      label: 'Source query',
      // Gives way first: at 390 px the provenance ellipsises rather than
      // pushing the chevron off the card.
      trailingLabel: _provenance,
      initiallyExpanded: startsExpanded,
      bodyPadding: EdgeInsets.zero,
      builder: _buildSql,
    );
  }

  Widget _buildSql(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.45),
        borderRadius: BgSpace.brSm,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          SelectableText(
            sql,
            style: theme.textTheme.bodySmall?.copyWith(
              fontFamily: 'monospace',
              height: 1.45,
            ),
          ),
          const SizedBox(height: BgSpace.sm),
          Row(
            children: <Widget>[
              Text(
                '$rowCount ${rowCount == 1 ? 'row' : 'rows'}',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: colors.onSurfaceVariant),
              ),
              const Spacer(),
              _TextAction(
                label: 'Copy',
                icon: Icons.copy_all_outlined,
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: sql));
                  ScaffoldMessenger.maybeOf(context)?.showSnackBar(
                    const SnackBar(content: Text('Query copied.')),
                  );
                },
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------

class _TextAction extends StatelessWidget {
  const _TextAction({
    required this.label,
    required this.icon,
    required this.onPressed,
  });

  final String label;
  final IconData icon;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return InkWell(
      onTap: onPressed,
      borderRadius: BgSpace.brSm,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: BgSpace.xs),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(icon, size: 16, color: theme.colorScheme.onSurfaceVariant),
            const SizedBox(width: BgSpace.xs),
            Text(label, style: theme.textTheme.labelLarge),
          ],
        ),
      ),
    );
  }
}
