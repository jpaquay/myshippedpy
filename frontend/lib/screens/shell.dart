/// The navigation shell.
///
/// This is legitimately hand-built chrome: a rail on wide viewports, a bottom
/// bar on narrow ones, an app bar with the account menu. Nothing inside the
/// content area is built here — each destination fetches a surface and hands
/// it to the renderer.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../app_theme.dart';
import '../auth/auth_service.dart';
import '../auth/sign_in_screen.dart';
import '../providers.dart';
import 'almanac_screen.dart';
import 'home_screen.dart';
import 'playlist_screen.dart';
import 'settings_screen.dart';

/// The four destinations.
enum BgDestination {
  forge('Forge', Icons.explore_outlined, Icons.explore),
  playlist('Set', Icons.queue_music_outlined, Icons.queue_music),
  almanac('Almanac', Icons.auto_stories_outlined, Icons.auto_stories),
  settings('Settings', Icons.tune_outlined, Icons.tune);

  const BgDestination(this.label, this.icon, this.selectedIcon);

  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

class AppShell extends ConsumerStatefulWidget {
  const AppShell({super.key});

  @override
  ConsumerState<AppShell> createState() => AppShellState();
}

class AppShellState extends ConsumerState<AppShell> {
  BgDestination _current = BgDestination.forge;

  /// Lets a screen push the user to another destination — the forge screen
  /// jumps to the set after a successful forge.
  void go(BgDestination destination) {
    if (!mounted) return;
    setState(() => _current = destination);
  }

  /// Nearest shell, so a descendant can navigate without a router.
  static AppShellState? of(BuildContext context) =>
      context.findAncestorStateOfType<AppShellState>();

  @override
  Widget build(BuildContext context) {
    final bool wide = MediaQuery.sizeOf(context).width >= 900;

    final Widget body = switch (_current) {
      BgDestination.forge => const HomeScreen(),
      BgDestination.playlist => const PlaylistScreen(),
      BgDestination.almanac => const AlmanacScreen(),
      BgDestination.settings => const SettingsScreen(),
    };

    return Scaffold(
      appBar: AppBar(
        title: const BarogrooveWordmark(compact: true),
        actions: <Widget>[
          const _HealthPip(),
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
                  setState(() => _current = BgDestination.values[i]),
              labelType: NavigationRailLabelType.all,
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
              child: Align(
                alignment: Alignment.topCenter,
                child: ConstrainedBox(
                  // A capped measure. Full-bleed long-form copy at 2560px is
                  // unreadable and this app is mostly long-form copy.
                  constraints: const BoxConstraints(maxWidth: 1080),
                  child: body,
                ),
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
                  setState(() => _current = BgDestination.values[i]),
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
          'Backend unreachable', <String>['$e'], ref),
      data: (health) {
        if (health.ok && health.degraded.isEmpty) {
          return _pip(context, BgPalette.ok, 'All systems nominal',
              const <String>[], ref);
        }
        return _pip(
          context,
          health.degraded.isEmpty ? BgPalette.warn : BgPalette.warn,
          health.ok ? 'Running degraded' : 'Backend unhealthy',
          health.degraded,
          ref,
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
  ) {
    return Tooltip(
      message: label,
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: () => showDialog<void>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
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
              ],
            ),
            actions: <Widget>[
              TextButton(
                onPressed: () {
                  ref.invalidate(healthProvider);
                  Navigator.of(context).pop();
                },
                child: const Text('Re-check'),
              ),
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
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
