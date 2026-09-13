/// The navigation shell.
///
/// This is legitimately hand-built chrome: a rail on wide viewports, a bottom
/// bar on narrow ones, an app bar with the account menu. Nothing inside the
/// content area is built here — each destination fetches a surface and hands
/// it to the renderer.
///
/// Header budget (spec §1): wordmark · connection badges (expanded only) ·
/// health pip (amber/red only) · account menu. Everything else that used to
/// live up here — the PWA install pill, the telemetry inspector button, the
/// theme toggle — moved to Settings or to the account menu. A header is not
/// a toolbox.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../advisor/assistant_overlay.dart';
import '../advisor/assistant_providers.dart';
import '../api/models.dart';
import '../app_theme.dart';
import '../auth/auth_service.dart';
import '../auth/pairing_service.dart';
import '../auth/sign_in_screen.dart';
import '../providers.dart';
import 'almanac_screen.dart';
import 'dataviz_screen.dart';
import 'home_screen.dart';
import 'playlist_screen.dart';
import 'settings_screen.dart';
import 'widgets/service_badge.dart';
import 'widgets/telemetry_inspector_panel.dart';

/// The five destinations.
///
/// Icons are monochrome instruments, outlined at rest and filled when
/// selected (spec §1.3). No sparkles, no gradients, no placeholders.
enum BgDestination {
  forge('Forge', Icons.explore_outlined, Icons.explore),
  playlist('Set', Icons.queue_music_outlined, Icons.queue_music),
  // A ledger, not a spellbook: `auto_stories` is the magic-book glyph.
  almanac('Almanac', Icons.menu_book_outlined, Icons.menu_book),
  // A magnifier over a line chart — asking questions of data, which is
  // exactly what the BigQuery QnA agent does. Replaces the `insights`
  // placeholder, whose glyph carries a sparkle.
  dataViz('Data Viz', Icons.query_stats_outlined, Icons.query_stats),
  // `tune` is sliders, which collides with the Forge cursor sliders.
  settings('Settings', Icons.settings_outlined, Icons.settings);

  const BgDestination(this.label, this.icon, this.selectedIcon);

  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key});

  /// Nearest shell, so a descendant can navigate without a router.
  static AppShellState? of(BuildContext context) =>
      context.findAncestorStateOfType<AppShellState>();

  @override
  ConsumerState<AppShell> createState() => AppShellState();
}

class AppShellState extends ConsumerState<AppShell> {
  BgDestination _current = BgDestination.forge;

  /// Lets a screen push the user to another destination — the forge screen
  /// jumps to the set after a successful forge.
  void go(BgDestination destination) {
    if (!mounted) return;
    HapticFeedback.selectionClick();
    // A destination you arrive at has not been scrolled yet, so the assistant
    // bubble comes back with it (spec §6.2).
    ref.read(bubbleVisibilityProvider.notifier).state = true;
    setState(() => _current = destination);
  }

  /// Sends the user to Settings → CONNECTED SERVICES with [provider]'s card
  /// brought into view. Used by the header badges and the account menu: a
  /// badge never starts an OAuth flow from the header (spec §7.5).
  void goToConnections([PairingProvider? provider]) {
    ref.read(settingsFocusProvider.notifier).state =
        SettingsFocus(section: SettingsSection.connections, provider: provider);
    go(BgDestination.settings);
  }

  /// Sends the user to Settings → APPEARANCE. The account menu's only job
  /// where theming is concerned (spec §7.4).
  void goToAppearance() {
    ref.read(settingsFocusProvider.notifier).state =
        const SettingsFocus(section: SettingsSection.appearance);
    go(BgDestination.settings);
  }

  @override
  Widget build(BuildContext context) {
    final BgBreakpoint breakpoint = BgBreak.of(context);
    final bool expanded = breakpoint == BgBreakpoint.expanded;
    final ForgeResult? lastForge = ref.watch(lastForgeProvider);
    final bool miniPlayerVisible =
        lastForge != null && _current != BgDestination.playlist;

    return Scaffold(
      appBar: AppBar(
        title: const BarogrooveWordmark(compact: true),
        actions: <Widget>[
          // Badges are desktop-only. On compact and medium the header budget
          // is wordmark + status + avatar, so they live in Settings and in
          // the account sheet instead (spec §7.5).
          if (expanded) ...<Widget>[
            const ServiceBadgeStrip(),
            const SizedBox(width: BgSpace.md),
          ],
          const _HealthPip(),
          const SizedBox(width: BgSpace.sm),
          const _AccountMenu(),
          const SizedBox(width: BgSpace.sm),
        ],
      ),
      body: Stack(
        children: <Widget>[
          // §6.2 — the bubble hides on scroll-down and returns on scroll-up.
          // Listening HERE rather than inside each destination means all five
          // drive it, including the ones this worker does not own, and no
          // screen has to remember to opt in. `UserScrollNotification` bubbles
          // up from whichever scroll view is the primary content; the guard
          // ignores nested scrollables (depth > 0) so a horizontal chip row
          // never hides the assistant.
          BubbleVisibilityScrollGuard(
            child: Row(
              children: <Widget>[
                if (expanded) ...<Widget>[
                  NavigationRail(
                    selectedIndex: _current.index,
                    onDestinationSelected: (int i) =>
                        go(BgDestination.values[i]),
                    labelType: NavigationRailLabelType.all,
                    // `trailing` is deliberately null. It used to carry a second
                    // copy of the theme toggle; the theme control now lives in
                    // Settings → APPEARANCE and nowhere else (spec §1, row 7).
                    destinations: <NavigationRailDestination>[
                      for (final BgDestination d in BgDestination.values)
                        NavigationRailDestination(
                          icon: Icon(d.icon),
                          selectedIcon: Icon(d.selectedIcon),
                          label: Text(d.label),
                        ),
                    ],
                  ),
                  VerticalDivider(
                    width: 1,
                    color: Theme.of(context).bg.hairline,
                  ),
                ],
                Expanded(
                  child: SafeArea(
                    bottom: false,
                    child: Column(
                      children: <Widget>[
                        Expanded(
                          child: Align(
                            alignment: Alignment.topCenter,
                            child: ConstrainedBox(
                              constraints: const BoxConstraints(
                                maxWidth: BgBreak.shellMaxWidth,
                              ),
                              // IndexedStack keeps all 5 screens mounted in
                              // memory so tab transitions take 0ms, preserve
                              // scroll position on mobile, and keep active audio
                              // playback uninterrupted.
                              child: IndexedStack(
                                index: _current.index,
                                children: const <Widget>[
                                  HomeScreen(),
                                  PlaylistScreen(),
                                  AlmanacScreen(),
                                  DataVizScreen(),
                                  SettingsScreen(),
                                ],
                              ),
                            ),
                          ),
                        ),
                        if (miniPlayerVisible)
                          _FloatingMiniPlayerBar(
                            forge: lastForge,
                            onOpenSet: () => go(BgDestination.playlist),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),

          // ---------------------------------------------------------------
          // THE ASSISTANT (spec §6.2) — items 10 + 11.
          //
          // Last child of this Stack: above the IndexedStack and above the
          // floating mini-player, but outside `Scaffold.bottomNavigationBar`,
          // so it structurally cannot overlap the tab bar. One instance for
          // the whole app — this is what replaced the two inline Gemini Live
          // banners on Forge and Data Viz (§6.1). Conversation state lives in
          // `advisor/assistant_providers.dart`, above this widget, so
          // switching destinations never loses history (§6.4).
          //
          // [assistantBubbleInset] supplies the offsets: it already clears
          // the tab bar, the viewport's bottom safe area and the mini-player
          // when it is showing. Scroll views reserve
          // `BgSpace.bubbleClearance` (96) at the bottom so the bubble never
          // covers content.
          // ---------------------------------------------------------------
          Builder(
            builder: (BuildContext context) {
              final EdgeInsets inset = assistantBubbleInset;
              return Positioned(
                right: inset.right,
                bottom: inset.bottom,
                child: const BgAssistantBubble(),
              );
            },
          ),
        ],
      ),
      bottomNavigationBar: expanded
          ? null
          : NavigationBar(
              selectedIndex: _current.index,
              onDestinationSelected: (int i) => go(BgDestination.values[i]),
              destinations: <NavigationDestination>[
                for (final BgDestination d in BgDestination.values)
                  NavigationDestination(
                    icon: Icon(d.icon),
                    selectedIcon: Icon(d.selectedIcon),
                    label: d.label,
                  ),
              ],
            ),
    );
  }

  /// Where the floating assistant bubble must sit so it clears the tab bar,
  /// the safe area and the mini-player (spec §6.2). Exposed on the state so
  /// the overlay worker does not have to re-derive it.
  EdgeInsets get assistantBubbleInset {
    final bool expanded = BgBreak.isExpanded(context);
    final ForgeResult? lastForge = ref.read(lastForgeProvider);
    final bool miniPlayerVisible =
        lastForge != null && _current != BgDestination.playlist;
    if (expanded) {
      return const EdgeInsets.only(right: BgSpace.xl, bottom: BgSpace.xl);
    }
    return EdgeInsets.only(
      right: BgSpace.lg,
      bottom: kBottomNavigationBarHeight +
          MediaQuery.viewPaddingOf(context).bottom +
          BgSpace.lg +
          (miniPlayerVisible ? BgSpace.miniPlayerHeight : 0),
    );
  }
}

/// The only thing besides the assistant bubble allowed to float above the tab
/// bar. Flat fill, one hairline rule, no elevation and no accent-alpha glow.
class _FloatingMiniPlayerBar extends StatelessWidget {
  const _FloatingMiniPlayerBar({
    required this.forge,
    required this.onOpenSet,
  });

  final ForgeResult forge;
  final VoidCallback onOpenSet;

  @override
  Widget build(BuildContext context) {
    final BgColors bg = Theme.of(context).bg;
    final int trackCount = forge.playlist.tracks.length;
    final bool narrow =
        MediaQuery.sizeOf(context).width < BgBreak.narrowPhone;

    return Material(
      color: bg.surfaceRaised,
      child: InkWell(
        onTap: onOpenSet,
        child: Container(
          height: BgSpace.miniPlayerHeight,
          padding: const EdgeInsets.symmetric(horizontal: BgSpace.lg),
          decoration: BoxDecoration(
            border: Border(top: BorderSide(color: bg.hairline)),
          ),
          child: Row(
            children: <Widget>[
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: bg.surfaceSunken,
                  borderRadius: BgSpace.brSm,
                  border: Border.all(color: bg.hairline),
                ),
                child: Icon(
                  Icons.graphic_eq_rounded,
                  color: bg.inkSecondary,
                  size: BgIcon.inline,
                ),
              ),
              const SizedBox(width: BgSpace.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Text(
                      forge.playlist.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: BgText.action(context),
                    ),
                    Text(
                      narrow
                          ? '$trackCount tracks'
                          : '$trackCount-Track Daylist · Active in Player Deck',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: BgText.meta(context),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              OutlinedButton(
                onPressed: onOpenSet,
                style: OutlinedButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                ),
                child: const Text('OPEN DECK'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The telemetry inspector's one remaining entry point is the health sheet.
/// The 1120×780 dialog is grandfathered (spec §2) — it is a genuine
/// full-screen tool — but nothing new may use a `Dialog`.
void _showTelemetryInspectorModal(BuildContext context) {
  showDialog<void>(
    context: context,
    builder: (BuildContext ctx) => Dialog(
      insetPadding: const EdgeInsets.all(BgSpace.lg),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1120, maxHeight: 780),
        child: const TelemetryInspectorPanel(isModal: true),
      ),
    ),
  );
}

/// A small dot reporting backend health.
///
/// Demoted (spec §1, row 4). Healthy is **silent**: nothing at all below
/// 900 px, a hairline dot on desktop so the health sheet stays reachable.
/// Never green. Amber and red only, because a status light that is always lit
/// stops being a status light.
class _HealthPip extends ConsumerWidget {
  const _HealthPip();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AsyncValue<HealthStatus> health = ref.watch(healthProvider);
    final BgColors bg = Theme.of(context).bg;
    final bool expanded = BgBreak.isExpanded(context);

    return health.when(
      // Loading is not a fault. We do not put a spinner in the header.
      loading: () => _quiet(context, bg, expanded, null),
      error: (Object e, StackTrace _) => _pip(
        context,
        bg.statusDanger,
        'Backend unreachable',
        <String>['$e'],
        null,
      ),
      data: (HealthStatus healthData) {
        if (healthData.ok && healthData.degraded.isEmpty) {
          return _quiet(context, bg, expanded, healthData);
        }
        return _pip(
          context,
          bg.statusWarn,
          healthData.ok ? 'Running degraded' : 'Backend unhealthy',
          healthData.degraded,
          healthData,
        );
      },
    );
  }

  /// Nothing is wrong. Show nothing on a phone; a hairline dot on desktop.
  Widget _quiet(
    BuildContext context,
    BgColors bg,
    bool expanded,
    HealthStatus? healthData,
  ) {
    if (!expanded) return const SizedBox.shrink();
    return _pip(
      context,
      bg.hairline,
      healthData == null ? 'Checking the backend' : 'All systems nominal',
      const <String>[],
      healthData,
    );
  }

  Widget _pip(
    BuildContext context,
    Color tone,
    String label,
    List<String> details,
    HealthStatus? healthStatus,
  ) {
    return Tooltip(
      message: label,
      child: InkWell(
        borderRadius: BgSpace.br,
        onTap: () => _showHealthSheet(
          context,
          label: label,
          details: details,
          telemetry: healthStatus?.telemetry,
        ),
        // 40×40 target around an 8 px dot.
        child: SizedBox(
          width: 40,
          height: 40,
          child: Center(
            child: Container(
              width: BgIcon.dot,
              height: BgIcon.dot,
              decoration: BoxDecoration(color: tone, shape: BoxShape.circle),
            ),
          ),
        ),
      ),
    );
  }
}

/// Rung 2: the health sheet. Replaces the old `AlertDialog` and keeps its two
/// actions — "Open Telemetry Inspector" and "Re-check".
void _showHealthSheet(
  BuildContext context, {
  required String label,
  required List<String> details,
  required TelemetrySummaryModel? telemetry,
}) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (BuildContext sheetContext) {
      final BgColors bg = Theme.of(sheetContext).bg;
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
            BgSpace.xl,
            BgSpace.sm,
            BgSpace.xl,
            BgSpace.xl,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(label, style: BgText.cardTitle(sheetContext)),
              const SizedBox(height: BgSpace.md),
              if (details.isEmpty)
                Text(
                  'Nothing to report.',
                  style: BgText.body(sheetContext),
                )
              else ...<Widget>[
                Text(
                  'The backend reports these as degraded:',
                  style: BgText.body(sheetContext),
                ),
                const SizedBox(height: BgSpace.sm),
                for (final String d in details)
                  Padding(
                    padding: const EdgeInsets.only(bottom: BgSpace.xxs),
                    child: Text('· $d', style: BgText.body(sheetContext)),
                  ),
              ],
              if (telemetry != null) ...<Widget>[
                const SizedBox(height: BgSpace.lg),
                Divider(color: bg.hairline),
                const SizedBox(height: BgSpace.md),
                Text(
                  'LIVE AI TELEMETRY SUMMARY',
                  style: BgText.eyebrow(sheetContext),
                ),
                const SizedBox(height: BgSpace.sm),
                _TelemetryRow('Total AI calls', '${telemetry.totalCalls}'),
                _TelemetryRow('Token usage', '${telemetry.totalTokens}'),
                _TelemetryRow(
                    'Active sessions', '${telemetry.activeSessions}'),
                _TelemetryRow(
                    'Stored memories', '${telemetry.storedMemories}'),
              ],
              const SizedBox(height: BgSpace.xl),
              Wrap(
                spacing: BgSpace.sm,
                runSpacing: BgSpace.sm,
                alignment: WrapAlignment.end,
                children: <Widget>[
                  TextButton.icon(
                    onPressed: () {
                      Navigator.of(sheetContext).pop();
                      _showTelemetryInspectorModal(context);
                    },
                    icon: const Icon(
                      Icons.monitor_heart_outlined,
                      size: BgIcon.inline,
                    ),
                    label: const Text('Open Telemetry Inspector'),
                  ),
                  Consumer(
                    builder: (BuildContext c, WidgetRef ref, _) =>
                        OutlinedButton(
                      onPressed: () {
                        ref.invalidate(healthProvider);
                        Navigator.of(sheetContext).pop();
                      },
                      child: const Text('Re-check'),
                    ),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.of(sheetContext).pop(),
                    child: const Text('Close'),
                  ),
                ],
              ),
            ],
          ),
        ),
      );
    },
  );
}

class _TelemetryRow extends StatelessWidget {
  const _TelemetryRow(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: BgSpace.xxs),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: <Widget>[
          Text(label, style: BgText.body(context)),
          Text(value, style: BgText.numeric(BgText.rowTitle(context))),
        ],
      ),
    );
  }
}

/// The header's overflow host (spec §1, row 6): avatar → Appearance,
/// Connections, Install app, Sign out. A popup menu on desktop, a bottom
/// sheet on a phone, because a 200 px popup anchored to a 30 px avatar on a
/// 390 px screen is not a menu.
class _AccountMenu extends ConsumerWidget {
  const _AccountMenu();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final BgUser? user = ref.watch(authStateProvider).valueOrNull;

    if (user == null) {
      return TextButton(
        onPressed: () => ref.read(authServiceProvider).signInWithGoogle(),
        child: const Text('Sign in'),
      );
    }

    final Widget avatar = _Avatar(user: user);

    if (BgBreak.isExpanded(context)) {
      return PopupMenuButton<_AccountAction>(
        tooltip: user.email,
        position: PopupMenuPosition.under,
        onSelected: (_AccountAction a) => _run(context, ref, a),
        itemBuilder: (BuildContext context) => <PopupMenuEntry<_AccountAction>>[
          PopupMenuItem<_AccountAction>(
            enabled: false,
            child: _Identity(user: user),
          ),
          const PopupMenuDivider(),
          for (final _AccountAction a in _AccountAction.navigable)
            PopupMenuItem<_AccountAction>(
              value: a,
              child: Row(
                children: <Widget>[
                  Icon(a.icon, size: BgIcon.chrome),
                  const SizedBox(width: BgSpace.md),
                  Expanded(child: Text(a.label)),
                  Text(
                    a.valueLabel(ref) ?? '',
                    style: BgText.meta(context),
                  ),
                  const SizedBox(width: BgSpace.xs),
                  const Icon(Icons.chevron_right, size: BgIcon.inline),
                ],
              ),
            ),
          const PopupMenuDivider(),
          PopupMenuItem<_AccountAction>(
            value: _AccountAction.signOut,
            child: Row(
              children: <Widget>[
                const Icon(Icons.logout, size: BgIcon.chrome),
                const SizedBox(width: BgSpace.md),
                Text(_AccountAction.signOut.label),
              ],
            ),
          ),
        ],
        child: avatar,
      );
    }

    return Tooltip(
      message: user.email,
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: () => _showAccountSheet(context, ref, user),
        child: Padding(
          padding: const EdgeInsets.all(BgSpace.xs),
          child: avatar,
        ),
      ),
    );
  }

  void _showAccountSheet(BuildContext context, WidgetRef ref, BgUser user) {
    showModalBottomSheet<void>(
      context: context,
      builder: (BuildContext sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.fromLTRB(
                BgSpace.xl,
                BgSpace.sm,
                BgSpace.xl,
                BgSpace.md,
              ),
              child: _Identity(user: user),
            ),
            // Not in the header at this width — here instead.
            const Padding(
              padding: EdgeInsets.fromLTRB(
                BgSpace.xl,
                0,
                BgSpace.xl,
                BgSpace.md,
              ),
              child: Align(
                alignment: Alignment.centerLeft,
                child: ServiceBadgeStrip(),
              ),
            ),
            Divider(color: Theme.of(sheetContext).bg.hairline),
            for (final _AccountAction a in _AccountAction.navigable)
              ListTile(
                leading: Icon(a.icon, size: BgIcon.chrome),
                title: Text(a.label),
                trailing: Text(
                  a.valueLabel(ref) ?? '',
                  style: BgText.meta(sheetContext),
                ),
                onTap: () {
                  Navigator.of(sheetContext).pop();
                  _run(context, ref, a);
                },
              ),
            Divider(color: Theme.of(sheetContext).bg.hairline),
            ListTile(
              leading: const Icon(Icons.logout, size: BgIcon.chrome),
              title: Text(_AccountAction.signOut.label),
              onTap: () {
                Navigator.of(sheetContext).pop();
                _run(context, ref, _AccountAction.signOut);
              },
            ),
            const SizedBox(height: BgSpace.sm),
          ],
        ),
      ),
    );
  }

  void _run(BuildContext context, WidgetRef ref, _AccountAction action) {
    final AppShellState? shell = AppShell.of(context);
    switch (action) {
      case _AccountAction.appearance:
        shell?.goToAppearance();
      case _AccountAction.connections:
        shell?.goToConnections();
      case _AccountAction.install:
        ref.read(settingsFocusProvider.notifier).state =
            const SettingsFocus(section: SettingsSection.install);
        shell?.go(BgDestination.settings);
      case _AccountAction.signOut:
        ref.read(authServiceProvider).signOut();
    }
  }
}

enum _AccountAction {
  appearance('Appearance', Icons.contrast),
  connections('Connections', Icons.link_outlined),
  install('Install app', Icons.add_to_home_screen),
  signOut('Sign out', Icons.logout);

  const _AccountAction(this.label, this.icon);

  final String label;
  final IconData icon;

  /// The rows that deep-link into Settings, in menu order.
  static const List<_AccountAction> navigable = <_AccountAction>[
    appearance,
    connections,
    install,
  ];

  /// Read-only current value shown on the right of the row — the account
  /// menu reports the appearance setting, it does not change it.
  String? valueLabel(WidgetRef ref) => switch (this) {
        // `read`, not `watch`: menus and sheets are built outside the
        // widget's build phase.
        _AccountAction.appearance => ref.read(bgThemeChoiceProvider).label,
        _ => null,
      };
}

class _Identity extends StatelessWidget {
  const _Identity({required this.user});

  final BgUser user;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Text(user.displayName, style: BgText.rowTitle(context)),
        Text(user.email, style: BgText.caption(context)),
      ],
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.user});

  final BgUser user;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return CircleAvatar(
      radius: 15,
      backgroundColor: colors.primaryContainer,
      foregroundImage:
          user.photoUrl == null ? null : NetworkImage(user.photoUrl!),
      child: Text(
        user.initials,
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: colors.onPrimaryContainer,
        ),
      ),
    );
  }
}
