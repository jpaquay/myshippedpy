/// The navigation shell.
///
/// This is legitimately hand-built chrome: a rail on wide viewports, a bottom
/// bar on narrow ones, an app bar with the account menu. Nothing inside the
/// content area is built here — each destination fetches a surface and hands
/// it to the renderer.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models.dart';
import '../app_theme.dart';
import '../auth/auth_service.dart';
import '../auth/sign_in_screen.dart';
import '../providers.dart';
import '../pwa/pwa_install.dart';
import 'almanac_screen.dart';
import 'dataviz_screen.dart';
import 'home_screen.dart';
import 'playlist_screen.dart';
import 'settings_screen.dart';
import 'widgets/telemetry_inspector_panel.dart';

/// The five destinations.
enum BgDestination {
  forge('Forge', Icons.explore_outlined, Icons.explore),
  playlist('Set', Icons.queue_music_outlined, Icons.queue_music),
  almanac('Almanac', Icons.auto_stories_outlined, Icons.auto_stories),
  dataViz('Data Viz', Icons.insights_outlined, Icons.insights),
  settings('Settings', Icons.tune_outlined, Icons.tune);

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
  late final PwaInstallBridge _pwaBridge;

  @override
  void initState() {
    super.initState();
    _pwaBridge = PwaInstallBridge(
      onStateChanged: () {
        if (mounted) setState(() {});
      },
    );
  }

  @override
  void dispose() {
    _pwaBridge.dispose();
    super.dispose();
  }

  /// Lets a screen push the user to another destination — the forge screen
  /// jumps to the set after a successful forge.
  void go(BgDestination destination) {
    if (!mounted) return;
    HapticFeedback.selectionClick();
    setState(() => _current = destination);
  }

  @override
  Widget build(BuildContext context) {
    final Size screenSize = MediaQuery.sizeOf(context);
    final bool wide = screenSize.width >= 900;
    final bool isMobile = screenSize.width < 600;
    final ForgeResult? lastForge = ref.watch(lastForgeProvider);

    return Scaffold(
      appBar: AppBar(
        title: const BarogrooveWordmark(compact: true),
        actions: <Widget>[
          _PwaInstallButton(bridge: _pwaBridge, compact: isMobile),
          const SizedBox(width: BgSpace.xs),
          const _TelemetryInspectorAppBarButton(),
          const SizedBox(width: BgSpace.xs),
          const _HealthPip(),
          const SizedBox(width: BgSpace.sm),
          const _ThemeModeSwitchButton(),
          const SizedBox(width: BgSpace.sm),
          const _AccountMenu(),
          const SizedBox(width: BgSpace.sm),
        ],
      ),
      body: Row(
        children: <Widget>[
          if (wide) ...<Widget>[
            NavigationRail(
              selectedIndex: _current.index,
              onDestinationSelected: (int i) =>
                  go(BgDestination.values[i]),
              labelType: NavigationRailLabelType.all,
              trailing: Expanded(
                child: Align(
                  alignment: Alignment.bottomCenter,
                  child: Padding(
                    padding: const EdgeInsets.only(bottom: BgSpace.lg),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        const _ThemeModeSwitchButton(),
                        const SizedBox(height: 6),
                        Text(
                          'THEME',
                          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                                fontSize: 9,
                                fontWeight: FontWeight.w700,
                                letterSpacing: 1.0,
                                color: Theme.of(context).colorScheme.onSurfaceVariant,
                              ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
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
              color: Theme.of(context).colorScheme.outlineVariant,
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
                        constraints: const BoxConstraints(maxWidth: 1080),
                        // IndexedStack keeps all 5 screens mounted in memory so tab
                        // transitions take 0ms, preserve scroll position on mobile,
                        // and keep active audio playback uninterrupted.
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
                  if (lastForge != null && _current != BgDestination.playlist)
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
      bottomNavigationBar: wide
          ? null
          : NavigationBar(
              selectedIndex: _current.index,
              onDestinationSelected: (int i) =>
                  go(BgDestination.values[i]),
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
}

class _PwaInstallButton extends StatelessWidget {
  const _PwaInstallButton({required this.bridge, required this.compact});

  final PwaInstallBridge bridge;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    if (bridge.isStandalone) {
      return const SizedBox.shrink();
    }
    final ColorScheme colors = Theme.of(context).colorScheme;
    final bool ready = bridge.isInstallable;

    return Tooltip(
      message: ready
          ? 'Install BaroGroove App (1-Click Chrome App)'
          : 'Install BaroGroove as Desktop/Mobile App',
      child: Material(
        color: colors.primary.withValues(alpha: ready ? 0.14 : 0.08),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(
            color: colors.primary.withValues(alpha: ready ? 0.65 : 0.3),
            width: 1.2,
          ),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: () async {
            HapticFeedback.lightImpact();
            if (ready) {
              await bridge.triggerInstall();
            } else {
              _showInstallInstructions(context);
            }
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
            child: Icon(
              ready ? Icons.install_desktop_rounded : Icons.download_for_offline_rounded,
              size: 17,
              color: colors.primary,
            ),
          ),
        ),
      ),
    );
  }

  void _showInstallInstructions(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: colors.surfaceContainerHigh,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (BuildContext ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(BgSpace.xl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Row(
                  children: <Widget>[
                    Icon(Icons.install_desktop_rounded, color: colors.primary),
                    const SizedBox(width: BgSpace.sm),
                    Expanded(
                      child: Text(
                        'Install BAROGROOVE Chrome App',
                        style: text.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: BgSpace.md),
                Text(
                  'BAROGROOVE is a full Progressive Web App (PWA) engineered for standalone desktop and mobile performance:',
                  style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
                ),
                const SizedBox(height: BgSpace.md),
                _installStep(
                  context,
                  Icons.computer_rounded,
                  'Desktop Chrome / Edge',
                  'Click the "Install BAROGROOVE" icon in the right side of the address bar (omnibox), or open Chrome menu (⋮) → "Save and share" → "Install page as app...".',
                ),
                const SizedBox(height: BgSpace.sm),
                _installStep(
                  context,
                  Icons.phone_android_rounded,
                  'Android Chrome',
                  'Tap the Chrome menu (⋮) → "Add to Home screen" / "Install app".',
                ),
                const SizedBox(height: BgSpace.sm),
                _installStep(
                  context,
                  Icons.phone_iphone_rounded,
                  'iOS Safari',
                  'Tap the Share button (↑) at the bottom of Safari → "Add to Home Screen".',
                ),
                const SizedBox(height: BgSpace.lg),
                Align(
                  alignment: Alignment.centerRight,
                  child: FilledButton(
                    onPressed: () => Navigator.of(ctx).pop(),
                    child: const Text('GOT IT'),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _installStep(
    BuildContext context,
    IconData icon,
    String title,
    String body,
  ) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(icon, size: 18, color: colors.primary),
        const SizedBox(width: BgSpace.sm),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                title,
                style: text.labelLarge?.copyWith(fontWeight: FontWeight.w700),
              ),
              Text(
                body,
                style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _FloatingMiniPlayerBar extends StatelessWidget {
  const _FloatingMiniPlayerBar({
    required this.forge,
    required this.onOpenSet,
  });

  final ForgeResult forge;
  final VoidCallback onOpenSet;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final int trackCount = forge.playlist.tracks.length;

    return Material(
      color: colors.surfaceContainerHighest.withValues(alpha: 0.96),
      elevation: 8,
      child: InkWell(
        onTap: onOpenSet,
        child: Container(
          padding: const EdgeInsets.symmetric(
            horizontal: BgSpace.lg,
            vertical: BgSpace.sm,
          ),
          decoration: BoxDecoration(
            border: Border(
              top: BorderSide(color: colors.primary.withValues(alpha: 0.35)),
            ),
          ),
          child: Row(
            children: <Widget>[
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: colors.primary.withValues(alpha: 0.16),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  Icons.graphic_eq_rounded,
                  color: colors.primary,
                  size: 20,
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
                      style: text.labelLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      '$trackCount-Track Daylist • Active in Player Deck',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: text.bodySmall?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              FilledButton.tonalIcon(
                onPressed: onOpenSet,
                icon: const Icon(Icons.play_arrow_rounded, size: 18),
                label: const Text('OPEN DECK'),
                style: FilledButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

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

class _TelemetryInspectorAppBarButton extends ConsumerWidget {
  const _TelemetryInspectorAppBarButton();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(healthProvider).valueOrNull;
    final int totalCalls = health?.telemetry?.totalCalls ?? 0;

    return Tooltip(
      message: 'Live AI Telemetry & Trace Inspector ($totalCalls calls)',
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: () => _showTelemetryInspectorModal(context),
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: BgSpace.sm,
            vertical: BgSpace.xs,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              const Icon(Icons.radar, size: 18),
              if (totalCalls > 0) ...<Widget>[
                const SizedBox(width: 4),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: BgPalette.sky700.withValues(alpha: 0.18),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: BgPalette.sky700.withValues(alpha: 0.5),
                    ),
                  ),
                  child: Text(
                    '$totalCalls',
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          fontSize: 10,
                        ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// A small dot reporting backend health. Green is silent; anything else is
/// tappable and says what is wrong. We do not hide a degraded backend.
class _HealthPip extends ConsumerWidget {
  const _HealthPip();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(healthProvider);

    return health.when(
      loading: () => const SizedBox(
        width: 14,
        height: 14,
        child: CircularProgressIndicator(strokeWidth: 1.6),
      ),
      error: (Object e, StackTrace _) => _pip(context, BgPalette.danger,
          'Backend unreachable', <String>['$e'], ref, null),
      data: (healthData) {
        if (healthData.ok && healthData.degraded.isEmpty) {
          return _pip(context, BgPalette.ok, 'All systems nominal',
              const <String>[], ref, healthData);
        }
        return _pip(
          context,
          healthData.degraded.isEmpty ? BgPalette.warn : BgPalette.warn,
          healthData.ok ? 'Running degraded' : 'Backend unhealthy',
          healthData.degraded,
          ref,
          healthData,
        );
      },
    );
  }

  Widget _pip(
    BuildContext context,
    Color tone,
    String label,
    List<String> details,
    WidgetRef ref,
    HealthStatus? healthStatus,
  ) {
    final TelemetrySummaryModel? telemetry = healthStatus?.telemetry;
    return Tooltip(
      message: label,
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: () => showDialog<void>(
          context: context,
          builder: (BuildContext dialogContext) => AlertDialog(
            title: Text(label),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                if (details.isEmpty)
                  const Text('Nothing to report.')
                else ...<Widget>[
                  const Text('The backend reports these as degraded:'),
                  const SizedBox(height: BgSpace.md),
                  for (final String d in details) Text('· $d'),
                ],
                if (telemetry != null) ...<Widget>[
                  const SizedBox(height: BgSpace.md),
                  const Divider(),
                  const SizedBox(height: BgSpace.xs),
                  Text(
                    'LIVE AI TELEMETRY SUMMARY',
                    style: Theme.of(dialogContext).textTheme.labelSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          letterSpacing: 0.8,
                        ),
                  ),
                  const SizedBox(height: BgSpace.xs),
                  Text('Total AI Calls: ${telemetry.totalCalls}'),
                  Text('Token Usage: ${telemetry.totalTokens}'),
                  Text('Active Sessions: ${telemetry.activeSessions}'),
                  Text('Stored Memories: ${telemetry.storedMemories}'),
                ],
              ],
            ),
            actions: <Widget>[
              TextButton.icon(
                onPressed: () {
                  Navigator.of(dialogContext).pop();
                  _showTelemetryInspectorModal(context);
                },
                icon: const Icon(Icons.radar, size: 16),
                label: const Text('Open Telemetry Inspector'),
              ),
              TextButton(
                onPressed: () {
                  ref.invalidate(healthProvider);
                  Navigator.of(dialogContext).pop();
                },
                child: const Text('Re-check'),
              ),
              TextButton(
                onPressed: () => Navigator.of(dialogContext).pop(),
                child: const Text('Close'),
              ),
            ],
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.all(BgSpace.sm),
          child: Container(
            width: 9,
            height: 9,
            decoration: BoxDecoration(color: tone, shape: BoxShape.circle),
          ),
        ),
      ),
    );
  }
}

class _AccountMenu extends ConsumerWidget {
  const _AccountMenu();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final BgUser? user = ref.watch(authStateProvider).valueOrNull;
    final ColorScheme colors = Theme.of(context).colorScheme;

    if (user == null) {
      return TextButton(
        onPressed: () => ref.read(authServiceProvider).signInWithGoogle(),
        child: const Text('Sign in'),
      );
    }

    return PopupMenuButton<String>(
      tooltip: user.email,
      position: PopupMenuPosition.under,
      onSelected: (String value) async {
        if (value == 'signout') {
          await ref.read(authServiceProvider).signOut();
        }
      },
      itemBuilder: (BuildContext context) => <PopupMenuEntry<String>>[
        PopupMenuItem<String>(
          enabled: false,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(user.displayName,
                  style: Theme.of(context).textTheme.titleSmall),
              Text(user.email, style: Theme.of(context).textTheme.bodySmall),
            ],
          ),
        ),
        const PopupMenuDivider(),
        const PopupMenuItem<String>(
          value: 'signout',
          child: Text('Sign out'),
        ),
      ],
      child: CircleAvatar(
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
      ),
    );
  }
}

/// Top-right AppBar & NavigationRail switch between Dark and Light mode.
class _ThemeModeSwitchButton extends ConsumerWidget {
  const _ThemeModeSwitchButton();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ThemeMode mode = ref.watch(themeModeProvider);
    final bool isDark = mode == ThemeMode.dark ||
        (mode == ThemeMode.system &&
            Theme.of(context).brightness == Brightness.dark);
    final ColorScheme colors = Theme.of(context).colorScheme;

    return Tooltip(
      message: isDark
          ? 'Dark Theme active • Click for Light Theme'
          : 'Light Theme active • Click for Dark Theme',
      child: Material(
        color: colors.surfaceContainerHighest.withValues(alpha: 0.55),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(
            color: colors.outlineVariant.withValues(alpha: 0.7),
            width: 1.1,
          ),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: () {
            HapticFeedback.selectionClick();
            ref.read(themeModeProvider.notifier).state =
                isDark ? ThemeMode.light : ThemeMode.dark;
          },
          child: Padding(
            padding: const EdgeInsets.all(3.0),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                // Light / Sun segment
                AnimatedContainer(
                  duration: const Duration(milliseconds: 180),
                  curve: Curves.easeOutCubic,
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
                  decoration: BoxDecoration(
                    color: !isDark
                        ? const Color(0xFFF59E0B).withValues(alpha: 0.22)
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(16),
                    border: !isDark
                        ? Border.all(color: const Color(0xFFF59E0B), width: 1.1)
                        : null,
                  ),
                  child: Icon(
                    Icons.wb_sunny_rounded,
                    size: 15,
                    color: !isDark
                        ? const Color(0xFFF59E0B)
                        : colors.onSurfaceVariant.withValues(alpha: 0.55),
                  ),
                ),
                const SizedBox(width: 2),
                // Dark / Moon segment
                AnimatedContainer(
                  duration: const Duration(milliseconds: 180),
                  curve: Curves.easeOutCubic,
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
                  decoration: BoxDecoration(
                    color: isDark
                        ? colors.primary.withValues(alpha: 0.22)
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(16),
                    border: isDark
                        ? Border.all(color: colors.primary, width: 1.1)
                        : null,
                  ),
                  child: Icon(
                    Icons.nightlight_round,
                    size: 15,
                    color: isDark
                        ? colors.primary
                        : colors.onSurfaceVariant.withValues(alpha: 0.55),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

