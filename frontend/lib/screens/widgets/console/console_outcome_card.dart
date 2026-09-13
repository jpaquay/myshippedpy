import 'package:flutter/material.dart';

import '../../../app_theme.dart';
import '../../../providers.dart';
import 'console_mode.dart';
import 'console_tokens.dart';
import 'forge_sky_reading.dart';

/// What the forge is about to do, in one headline and one line of reasoning.
///
/// This is the whole of Guided's body (§5.3), so it is deliberately two lines
/// of text: headline clamped to one line, rationale to two, which keeps the
/// card inside the 120 px budget at 390 px.
///
/// The rationale also does the honest work the spec asks for: it names what the
/// request will actually carry. `ForgeSelection.toRequest()` nulls every custom
/// field in Guided and nulls pressure / trend / BPM outside Expert, so each
/// mode says which of its numbers travel.
class ConsoleOutcome {
  const ConsoleOutcome({required this.headline, required this.rationale});

  final String headline;
  final String rationale;

  factory ConsoleOutcome.forMode({
    required ConsoleMode mode,
    required ForgeSelection selection,
    ForgeSkyReading? reading,
  }) {
    switch (mode) {
      case ConsoleMode.guided:
        // Guided sends no overrides at all, so the forecast must come from the
        // live sky, never from the cursor values the user cannot see. The tone
        // is the backend's own verdict on the hero dimension.
        switch (reading?.trendTone) {
          case 'falling':
            return const ConsoleOutcome(
              headline: 'Slower, denser, minor-key.',
              rationale: 'Falling pressure asks for weight.',
            );
          case 'rising':
            return const ConsoleOutcome(
              headline: 'Brighter, faster, major-key.',
              rationale: 'Rising pressure lifts the set.',
            );
          case 'steady':
            return const ConsoleOutcome(
              headline: 'Even-handed, mid-tempo.',
              rationale: 'A steady barometer keeps the set level.',
            );
          default:
            return const ConsoleOutcome(
              headline: 'The sky decides.',
              rationale: 'No live reading yet — we read it when you forge.',
            );
        }

      case ConsoleMode.easy:
        return ConsoleOutcome(
          headline: _cursorHeadline(selection),
          rationale: 'Your three cursors are sent; pressure and tempo stay live.',
        );

      case ConsoleMode.expert:
        return ConsoleOutcome(
          headline: _cursorHeadline(selection),
          rationale: 'All six overrides are sent, pressure and tempo included.',
        );
    }
  }

  static String _cursorHeadline(ForgeSelection selection) {
    if (selection.customLightPct < 30) return 'Low light, deep and slow.';
    if (selection.customTempC < 5) return 'Cold air, sparse and sharp.';
    if (selection.customTempC > 26) return 'Heat, loose and bright.';
    if (selection.customLightPct > 70) return 'High sun, open and bright.';
    return 'Temperate, mid-tempo.';
  }
}

class ConsoleOutcomeCard extends StatelessWidget {
  const ConsoleOutcomeCard({required this.outcome, super.key});

  final ConsoleOutcome outcome;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      key: ForgeKeys.outcomeCard,
      width: double.infinity,
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.br,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text(
            outcome.headline,
            style: text.titleLarge,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: BgSpace.xs),
          Text(
            outcome.rationale,
            style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}
