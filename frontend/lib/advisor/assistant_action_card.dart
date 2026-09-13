// The inline confirmation card (UX_IA_SPEC.md §6.5).
//
// Five rules, all of them load-bearing:
//
//   1. It is a card **in the conversation**, full width, never a modal
//      dialog. The page behind stays visible and the user can keep scrolling
//      the history.
//   2. Every argument is visible and editable before anything runs.
//   3. `Confirm` is **not** autofocused. A stray Enter or a screen-reader
//      default action must not spend a write.
//   4. A voice-initiated write needs an explicit affirmative — the card says
//      so, and `AssistantController` only accepts an unambiguous yes.
//   5. Once it has run, the card collapses to a one-line receipt.

import 'package:flutter/material.dart';

import '../app_theme.dart';
import 'assistant_models.dart';

class AssistantActionCard extends StatelessWidget {
  const AssistantActionCard({
    required this.action,
    required this.onConfirm,
    required this.onDecline,
    required this.onEdit,
    super.key,
  });

  final AssistantAction action;
  final VoidCallback onConfirm;
  final VoidCallback onDecline;
  final void Function(String name, String value) onEdit;

  @override
  Widget build(BuildContext context) {
    final BgColors colors = Theme.of(context).bg;

    if (action.isSettled) return _Receipt(action: action);

    final bool running = action.status == AssistantActionStatus.running;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surfaceRaised,
        borderRadius: BgSpace.br,
        border: Border.all(color: colors.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(
                Icons.task_alt_outlined,
                size: BgIcon.inline,
                color: colors.inkSecondary,
              ),
              const SizedBox(width: BgSpace.sm),
              Expanded(
                child: Text(
                  'CONFIRM BEFORE RUNNING',
                  style: BgText.eyebrow(context)?.copyWith(
                    color: colors.inkSecondary,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.sm),
          Text(
            action.title,
            style: BgText.rowTitle(context)?.copyWith(color: colors.inkPrimary),
          ),
          if (action.detail.isNotEmpty) ...<Widget>[
            const SizedBox(height: BgSpace.xs),
            Text(
              action.detail,
              style: BgText.body(context)?.copyWith(color: colors.inkSecondary),
            ),
          ],
          if (action.args.isNotEmpty) ...<Widget>[
            const SizedBox(height: BgSpace.md),
            for (final AssistantArg arg in action.args)
              Padding(
                padding: const EdgeInsets.only(bottom: BgSpace.sm),
                child: _ArgumentRow(
                  arg: arg,
                  enabled: !running && arg.editable,
                  onChanged: (String v) => onEdit(arg.name, v),
                ),
              ),
          ],
          if (action.voiceInitiated) ...<Widget>[
            const SizedBox(height: BgSpace.xs),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Icon(
                  Icons.mic_none,
                  size: BgIcon.inline,
                  color: colors.inkTertiary,
                ),
                const SizedBox(width: BgSpace.xs),
                Expanded(
                  child: Text(
                    'You asked for this out loud. Say “confirm” or tap '
                    'Confirm — anything else is treated as a new question.',
                    style: BgText.meta(context)
                        ?.copyWith(color: colors.inkTertiary),
                  ),
                ),
              ],
            ),
          ],
          const SizedBox(height: BgSpace.md),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: <Widget>[
              TextButton(
                // Explicit: neither button steals focus when the card lands.
                autofocus: false,
                onPressed: running ? null : onDecline,
                child: const Text('Cancel'),
              ),
              const SizedBox(width: BgSpace.sm),
              FilledButton(
                // §6.5 — Confirm is NOT autofocused.
                autofocus: false,
                onPressed: running ? null : onConfirm,
                child: Text(running ? 'Running…' : 'Confirm'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ArgumentRow extends StatefulWidget {
  const _ArgumentRow({
    required this.arg,
    required this.enabled,
    required this.onChanged,
  });

  final AssistantArg arg;
  final bool enabled;
  final ValueChanged<String> onChanged;

  @override
  State<_ArgumentRow> createState() => _ArgumentRowState();
}

class _ArgumentRowState extends State<_ArgumentRow> {
  late final TextEditingController _controller =
      TextEditingController(text: widget.arg.value);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final BgColors colors = Theme.of(context).bg;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          widget.arg.label.toUpperCase(),
          style: BgText.eyebrow(context)?.copyWith(color: colors.inkTertiary),
        ),
        const SizedBox(height: BgSpace.xxs),
        TextField(
          controller: _controller,
          enabled: widget.enabled,
          onChanged: widget.onChanged,
          style: BgText.body(context)?.copyWith(color: colors.inkPrimary),
          decoration: InputDecoration(
            isDense: true,
            filled: true,
            fillColor: colors.surfaceSunken,
            contentPadding: const EdgeInsets.symmetric(
              horizontal: BgSpace.md,
              vertical: BgSpace.sm,
            ),
            border: OutlineInputBorder(
              borderRadius: BgSpace.brSm,
              borderSide: BorderSide(color: colors.hairline),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BgSpace.brSm,
              borderSide: BorderSide(color: colors.hairline),
            ),
          ),
        ),
      ],
    );
  }
}

/// What is left after the card has run: one line, `BgText.meta`, no controls.
class _Receipt extends StatelessWidget {
  const _Receipt({required this.action});

  final AssistantAction action;

  @override
  Widget build(BuildContext context) {
    final BgColors colors = Theme.of(context).bg;
    final bool failed = action.status == AssistantActionStatus.failed;
    final Color tone = failed ? colors.statusDanger : colors.inkSecondary;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: BgSpace.md,
        vertical: BgSpace.sm,
      ),
      decoration: BoxDecoration(
        color: colors.surfaceSunken,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.hairline),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(
            switch (action.status) {
              AssistantActionStatus.done => Icons.check_circle_outline,
              AssistantActionStatus.failed => Icons.error_outline,
              _ => Icons.remove_circle_outline,
            },
            size: BgIcon.inline,
            color: tone,
          ),
          const SizedBox(width: BgSpace.sm),
          Expanded(
            child: Text(
              action.receipt.isEmpty ? action.title : action.receipt,
              style: BgText.meta(context)?.copyWith(color: tone),
            ),
          ),
        ],
      ),
    );
  }
}
