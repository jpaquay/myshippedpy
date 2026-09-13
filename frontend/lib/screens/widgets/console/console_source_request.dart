import 'dart:convert';

import 'package:flutter/material.dart';

import '../../../api/models.dart';
import '../../../app_theme.dart';
import '../../../providers.dart';
import '../../../widgets/bg_disclosure.dart';
import 'console_tokens.dart';

/// Expert-only rung 2 (§5.2): the exact `ForgeRequest` body this console will
/// POST, opened from a plain text link.
///
/// This is the sharpest version of "the UI tells the truth about
/// `toRequest()`": the JSON omits every field the current mode nulls, so a user
/// in Expert can see that `custom_pressure_hpa` is present here and would not
/// be in Easy.
class ConsoleSourceRequestLink extends StatelessWidget {
  const ConsoleSourceRequestLink({required this.selection, super.key});

  final ForgeSelection selection;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: TextButton(
        key: ForgeKeys.sourceRequest,
        onPressed: () => showBgDetailSheet(
          context,
          title: 'Source request',
          builder: (BuildContext sheetContext) =>
              _RequestJson(selection: selection),
        ),
        child: const Text('Source request'),
      ),
    );
  }
}

class _RequestJson extends StatelessWidget {
  const _RequestJson({required this.selection});

  final ForgeSelection selection;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final ForgeRequest request = selection.toRequest();
    final String pretty =
        const JsonEncoder.withIndent('  ').convert(request.toJson());

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(
          'POST /api/forge — fields your current mode does not send are absent, '
          'not zeroed.',
          style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
        ),
        const SizedBox(height: BgSpace.md),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(BgSpace.md),
          decoration: BoxDecoration(
            color: colors.surfaceContainerLow,
            borderRadius: BgSpace.brSm,
            border: Border.all(color: colors.outlineVariant),
          ),
          child: SelectableText(
            pretty,
            style: text.bodySmall?.copyWith(fontFamily: 'monospace'),
          ),
        ),
      ],
    );
  }
}
