import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../app_theme.dart';

/// Official Agentic Platform Team footer for BAROGROOVE (`v3.netdev.be` standard).
///
/// Renders:
///   Built with ❤️ by the Agentic Platform Team at ⚡web3.netdev.be⚡
class NetdevFooter extends StatelessWidget {
  const NetdevFooter({super.key});

  Future<void> _openWeb3Netdev() async {
    final Uri url = Uri.parse('https://web3.netdev.be/');
    if (await canLaunchUrl(url)) {
      await launchUrl(url, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Padding(
      padding: const EdgeInsets.symmetric(
        vertical: BgSpace.xl,
        horizontal: BgSpace.md,
      ),
      child: Center(
        child: Wrap(
          alignment: WrapAlignment.center,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 4,
          children: <Widget>[
            Text(
              'Built with ❤️ by the Agentic Platform Team at',
              style: text.bodySmall?.copyWith(
                color: colors.onSurfaceVariant,
                fontStyle: FontStyle.italic,
              ),
            ),
            InkWell(
              onTap: _openWeb3Netdev,
              borderRadius: BgSpace.brSm,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                child: Text(
                  '⚡web3.netdev.be⚡',
                  style: text.bodySmall?.copyWith(
                    color: colors.primary,
                    fontWeight: FontWeight.w700,
                    fontStyle: FontStyle.italic,
                    decoration: TextDecoration.underline,
                    decorationColor: colors.primary.withValues(alpha: 0.4),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
