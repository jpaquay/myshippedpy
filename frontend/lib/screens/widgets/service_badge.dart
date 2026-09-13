/// Spotify / Last.fm connection badges (spec §7.5, plan item 14).
///
/// ## One source of truth
///
/// These widgets **read** `pairingStatusProvider`, which is fed by
/// `PairingService.status()` → `GET /api/pair/status`. They hold no state of
/// their own, they cache nothing, and they never start an OAuth flow: tapping
/// a badge navigates to Settings → CONNECTED SERVICES, where the existing
/// `_PairingCard` owns the actual connect/disconnect logic. A badge in the
/// header that could half-complete a pairing is a second source of truth, and
/// two sources of truth about whether you are logged in is worse than none.
///
/// ## Three states, said out loud
///
/// `linked`, `unlinked` and **`unknown`**. Unknown is what you get while the
/// status request is in flight, and what you get if it fails — the backend
/// being unreachable is not evidence that the user is disconnected, and
/// rendering it as "Not linked" would be a lie that invites them to re-pair an
/// account that is already fine.
///
/// ## Monochrome
///
/// No Spotify green, no Last.fm red, no brand logos (none ship with Material
/// and we are not adding an asset or a dependency). The single drop of colour
/// in the whole component is a 4 px `statusOk` dot, and only when linked.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/models.dart';
import '../../app_theme.dart';
import '../../auth/pairing_service.dart';
import '../../providers.dart';
import '../shell.dart';

/// The two services the badges can describe.
enum BgService {
  spotify(PairingProvider.spotify, 'SP'),
  lastfm(PairingProvider.lastfm, 'FM');

  const BgService(this.provider, this.monogram);

  /// The pairing provider this badge reports on. The badge is a view of it,
  /// not a parallel definition.
  final PairingProvider provider;

  /// Two letters, because there is no logo and there is no room.
  final String monogram;

  String get label => provider.label;
}

/// Linked / unlinked / unknown, plus the account name when we have one.
@immutable
class BgServiceLink {
  const BgServiceLink.linked(this.account)
      : isLinked = true,
        isKnown = true;

  const BgServiceLink.unlinked()
      : isLinked = false,
        isKnown = true,
        account = null;

  const BgServiceLink.unknown()
      : isLinked = false,
        isKnown = false,
        account = null;

  final bool isLinked;
  final bool isKnown;
  final String? account;

  /// The status word shown in Settings, and in the badge tooltip.
  String get statusWord {
    if (!isKnown) return 'Status unknown';
    if (!isLinked) return 'Not linked';
    return account == null ? 'Linked' : 'Linked as $account';
  }

  /// Reads one service's state out of the shared pairing status.
  static BgServiceLink of(AsyncValue<PairingStatus> status, BgService s) {
    return status.when(
      loading: () => const BgServiceLink.unknown(),
      error: (Object _, StackTrace __) => const BgServiceLink.unknown(),
      data: (PairingStatus p) {
        final bool linked =
            s == BgService.spotify ? p.spotify : p.lastfm;
        if (!linked) return const BgServiceLink.unlinked();
        final String? account =
            s == BgService.spotify ? p.spotifyAccount : p.lastfmAccount;
        return BgServiceLink.linked(account);
      },
    );
  }
}

/// The 4 px `statusOk` dot, present only on a linked badge. Named so tests
/// can assert its absence, which is the interesting half.
const Key linkedDotKey = ValueKey<String>('service-badge-linked-dot');

/// The 24 px monogram pill. Header form.
class ServiceBadge extends StatelessWidget {
  const ServiceBadge({
    required this.service,
    required this.linked,
    this.account,
    this.onTap,
    super.key,
  })  : _known = true;

  /// Status not yet established, or unreadable. Rendered as a muted pill with
  /// no dot — never as "not linked".
  const ServiceBadge.unknown({
    required this.service,
    this.onTap,
    super.key,
  })  : linked = false,
        account = null,
        _known = false;

  final BgService service;
  final bool linked;
  final String? account;
  final VoidCallback? onTap;
  final bool _known;

  BgServiceLink get _state => !_known
      ? const BgServiceLink.unknown()
      : linked
          ? BgServiceLink.linked(account)
          : const BgServiceLink.unlinked();

  @override
  Widget build(BuildContext context) {
    final BgColors bg = Theme.of(context).bg;
    final BgServiceLink state = _state;

    final Color border =
        state.isLinked ? bg.hairline : bg.hairline.withValues(alpha: 0.5);
    final Color ink = state.isLinked ? bg.connected : bg.disconnected;

    final Widget pill = Container(
      height: 24,
      padding: const EdgeInsets.symmetric(horizontal: BgSpace.sm),
      decoration: BoxDecoration(
        color: Colors.transparent,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text(
            service.monogram,
            style: BgText.meta(context)?.copyWith(color: ink),
          ),
          // The only colour in the component, and only when linked.
          if (state.isLinked) ...<Widget>[
            const SizedBox(width: BgSpace.xs),
            Container(
              key: linkedDotKey,
              width: 4,
              height: 4,
              decoration: BoxDecoration(
                color: bg.statusOk,
                shape: BoxShape.circle,
              ),
            ),
          ],
        ],
      ),
    );

    return Tooltip(
      // No icon in the header is ever the sole carrier of meaning.
      message: '${service.label} · ${state.statusWord}',
      child: onTap == null
          ? pill
          : InkWell(
              borderRadius: BgSpace.brSm,
              onTap: onTap,
              child: pill,
            ),
    );
  }
}

/// The two header badges, live. Desktop header and the account sheet only —
/// on compact and medium the header budget is wordmark + status + avatar, so
/// the badges live in Settings and in the account sheet instead (spec §7.5).
class ServiceBadgeStrip extends ConsumerWidget {
  const ServiceBadgeStrip({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<PairingStatus> status = ref.watch(pairingStatusProvider);

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        for (final BgService service in BgService.values) ...<Widget>[
          _badgeFor(context, status, service),
          if (service != BgService.values.last)
            const SizedBox(width: BgSpace.sm),
        ],
      ],
    );
  }

  Widget _badgeFor(
    BuildContext context,
    AsyncValue<PairingStatus> status,
    BgService service,
  ) {
    final BgServiceLink link = BgServiceLink.of(status, service);
    // Never an OAuth flow from the header — always a trip to Settings.
    void open() => AppShell.of(context)?.goToConnections(service.provider);

    if (!link.isKnown) {
      return ServiceBadge.unknown(service: service, onTap: open);
    }
    return ServiceBadge(
      service: service,
      linked: link.isLinked,
      account: link.account,
      onTap: open,
    );
  }
}

/// The Settings form: full name, status word, and one action.
///
/// The action is a callback so that connecting and disconnecting stay in
/// `settings_screen.dart` with the rest of the pairing flow. This row states
/// what is true; it does not know how to change it.
class ServiceStatusRow extends StatelessWidget {
  const ServiceStatusRow({
    required this.service,
    required this.link,
    this.onConnect,
    this.onDisconnect,
    super.key,
  });

  final BgService service;
  final BgServiceLink link;
  final VoidCallback? onConnect;
  final VoidCallback? onDisconnect;

  @override
  Widget build(BuildContext context) {
    final BgColors bg = Theme.of(context).bg;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: BgSpace.xs),
      child: Row(
        children: <Widget>[
          link.isKnown
              ? ServiceBadge(
                  service: service,
                  linked: link.isLinked,
                  account: link.account,
                )
              : ServiceBadge.unknown(service: service),
          const SizedBox(width: BgSpace.md),
          Expanded(
            child: Text(
              '${service.label} · ${link.statusWord}',
              style: BgText.body(context)?.copyWith(
                color: link.isLinked ? bg.inkPrimary : bg.inkSecondary,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          // Unknown offers no action: we do not invite a user to re-pair an
          // account that may well be connected.
          if (link.isKnown)
            link.isLinked
                ? TextButton(
                    onPressed: onDisconnect,
                    child: const Text('Disconnect'),
                  )
                : OutlinedButton(
                    onPressed: onConnect,
                    child: const Text('Connect'),
                  ),
        ],
      ),
    );
  }
}
