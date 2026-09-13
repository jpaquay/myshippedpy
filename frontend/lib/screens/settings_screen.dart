/// Settings, pairing and About.
///
/// Legitimately hand-built: this page is about the client's relationship with
/// external services (Firebase, Spotify, Last.fm) and its own configuration.
/// The agent has no view on any of that.
///
/// The pairing cards state the degradation consequences up front. A user who
/// declines Spotify should know exactly what they are choosing, not discover
/// it when a forge returns a file.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../app_theme.dart';
import '../auth/auth_service.dart';
import '../auth/pairing_service.dart';
import '../config.dart';
import '../providers.dart';
import '../pwa/pwa_install.dart';
import 'widgets/section.dart';
import 'widgets/service_badge.dart';
import 'widgets/status_notes.dart';
import 'widgets/theme_mode_control.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  PairingProvider? _connecting;
  Completer<void>? _cancel;
  String? _pairingMessage;
  String _spotifyRedirectUri = 'https://bg.netdev.be/api/pair/spotify/callback';
  final TextEditingController _lastfmUserCtrl =
      TextEditingController(text: 'jpaquay');
  final TextEditingController _spotifyManualCtrl = TextEditingController();
  bool _showSpotifyManual = false;
  bool _linkingUsername = false;
  bool _exchangingManual = false;

  late final PwaInstallBridge _pwaBridge;
  bool _showInstallHowTo = false;

  /// Anchors for the deep links set by the account menu and the header
  /// connection badges (`settingsFocusProvider`).
  final GlobalKey _appearanceKey = GlobalKey();
  final GlobalKey _connectionsKey = GlobalKey();
  final GlobalKey _installKey = GlobalKey();

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
    _lastfmUserCtrl.dispose();
    _spotifyManualCtrl.dispose();
    super.dispose();
  }

  /// Consumes a one-shot [SettingsFocus] and brings its section into view.
  void _consumeFocus(SettingsFocus? focus) {
    if (focus == null) return;
    final GlobalKey key = switch (focus.section) {
      SettingsSection.appearance => _appearanceKey,
      SettingsSection.connections => _connectionsKey,
      SettingsSection.install => _installKey,
      SettingsSection.account => _appearanceKey,
    };
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      ref.read(settingsFocusProvider.notifier).state = null;
      final BuildContext? target = key.currentContext;
      if (target == null) return;
      Scrollable.ensureVisible(
        target,
        duration: const Duration(milliseconds: 240),
        curve: Curves.easeOutCubic,
        alignment: 0.05,
      );
    });
  }

  Future<void> _connect(
    PairingProvider provider, {
    String? redirectUri,
  }) async {
    final Completer<void> cancel = Completer<void>();
    setState(() {
      _connecting = provider;
      _cancel = cancel;
      _pairingMessage = null;
    });

    final PairingAttempt attempt = await ref
        .read(pairingServiceProvider)
        .connect(
          provider,
          redirectUri: redirectUri,
          cancelled: cancel.future,
        );

    if (!mounted) return;

    ref.invalidate(pairingStatusProvider);
    setState(() {
      _connecting = null;
      _cancel = null;
      _pairingMessage = attempt.ok ? null : attempt.message;
    });
  }

  Future<void> _connectLastfmByUsername() async {
    final String user = _lastfmUserCtrl.text.trim();
    if (user.isEmpty) return;
    setState(() {
      _linkingUsername = true;
      _pairingMessage = null;
    });
    final PairingAttempt attempt = await ref
        .read(pairingServiceProvider)
        .connectLastfmUsername(user);
    if (!mounted) return;
    ref.invalidate(pairingStatusProvider);
    setState(() {
      _linkingUsername = false;
      _pairingMessage = attempt.ok ? null : attempt.message;
    });
    if (attempt.ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Last.fm connected as $user'),
          backgroundColor: BgPalette.ok,
        ),
      );
    }
  }

  Future<void> _completeSpotifyManual() async {
    final String input = _spotifyManualCtrl.text.trim();
    if (input.isEmpty) return;
    setState(() {
      _exchangingManual = true;
      _pairingMessage = null;
    });
    final PairingAttempt attempt = await ref
        .read(pairingServiceProvider)
        .manualSpotifyExchange(
          input,
          redirectUri: _spotifyRedirectUri,
        );
    if (!mounted) return;
    ref.invalidate(pairingStatusProvider);
    setState(() {
      _exchangingManual = false;
      _pairingMessage = attempt.ok ? null : attempt.message;
      if (attempt.ok) {
        _spotifyManualCtrl.clear();
        _showSpotifyManual = false;
      }
    });
  }

  Future<void> _disconnect(PairingProvider provider) async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text('Disconnect ${provider.label}?'),
        content: Text(provider.degradation),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Keep it'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Disconnect'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    final PairingAttempt attempt =
        await ref.read(pairingServiceProvider).disconnect(provider);
    if (!mounted) return;

    ref.invalidate(pairingStatusProvider);
    setState(() => _pairingMessage = attempt.ok ? null : attempt.message);
  }

  @override
  Widget build(BuildContext context) {
    final BgUser? user = ref.watch(authStateProvider).valueOrNull;
    final pairing = ref.watch(pairingStatusProvider);
    final health = ref.watch(healthProvider).valueOrNull;
    _consumeFocus(ref.watch(settingsFocusProvider));

    return ListView(
      padding: EdgeInsets.fromLTRB(
        BgBreak.gutter(context),
        BgSpace.lg,
        BgBreak.gutter(context),
        BgSpace.bubbleClearance,
      ),
      children: <Widget>[
        Text('Settings', style: BgText.screenTitle(context)),
        const SizedBox(height: BgSpace.xxl),

        // --- Account --------------------------------------------------
        Section(
          eyebrow: 'ACCOUNT',
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(BgSpace.lg),
              child: user == null
                  ? Row(
                      children: <Widget>[
                        const Expanded(
                          child: Text('You are not signed in.'),
                        ),
                        FilledButton(
                          onPressed: () => ref
                              .read(authServiceProvider)
                              .signInWithGoogle(),
                          child: const Text('Sign in'),
                        ),
                      ],
                    )
                  : Row(
                      children: <Widget>[
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: <Widget>[
                              Text(
                                user.displayName,
                                style:
                                    Theme.of(context).textTheme.titleMedium,
                              ),
                              Text(
                                user.email,
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            ],
                          ),
                        ),
                        OutlinedButton(
                          onPressed: () =>
                              ref.read(authServiceProvider).signOut(),
                          child: const Text('Sign out'),
                        ),
                      ],
                    ),
            ),
          ),
        ),

        const SizedBox(height: BgSpace.xxl),

        // --- Appearance -------------------------------------------------
        // The only home of the theme control (spec §7.4). One row, nothing
        // else; the header and the navigation rail no longer carry a copy.
        Section(
          key: _appearanceKey,
          eyebrow: 'APPEARANCE',
          child: const ThemeModeControl(),
        ),

        const SizedBox(height: BgSpace.xxl),

        // --- Pairing --------------------------------------------------
        Section(
          key: _connectionsKey,
          eyebrow: 'CONNECTED SERVICES',
          trailing: IconButton(
            tooltip: 'Refresh',
            visualDensity: VisualDensity.compact,
            icon: const Icon(Icons.refresh, size: 18),
            onPressed: () => ref.invalidate(pairingStatusProvider),
          ),
          child: Column(
            children: <Widget>[
              if (_pairingMessage != null) ...<Widget>[
                DegradedNotes(
                  title: 'Pairing did not complete',
                  notes: <String>[_pairingMessage!],
                ),
                const SizedBox(height: BgSpace.md),
              ],
              // Status row first: two monochrome badges that tell the truth
              // in all three states, including while the status request is
              // still in flight. Same source of truth as the cards below —
              // this is a second view, not a second store.
              for (final BgService service in BgService.values)
                ServiceStatusRow(
                  service: service,
                  link: BgServiceLink.of(pairing, service),
                  onConnect: () => _connect(
                    service.provider,
                    redirectUri: service == BgService.spotify
                        ? _spotifyRedirectUri
                        : null,
                  ),
                  onDisconnect: () => _disconnect(service.provider),
                ),
              const SizedBox(height: BgSpace.md),

              pairing.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(BgSpace.xl),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (Object e, StackTrace _) => DegradedNotes(
                  title: 'Could not read pairing status',
                  notes: <String>['$e'],
                  tone: DegradedTone.error,
                ),
                data: (PairingStatus status) => Column(
                  children: <Widget>[
                    _PairingCard(
                      provider: PairingProvider.spotify,
                      connected: status.spotify,
                      account: status.spotifyAccount,
                      busy: _connecting == PairingProvider.spotify,
                      onConnect: () => _connect(
                        PairingProvider.spotify,
                        redirectUri: _spotifyRedirectUri,
                      ),
                      onDisconnect: () =>
                          _disconnect(PairingProvider.spotify),
                      onCancel: () => _cancel?.complete(),
                      extraChild: status.spotify
                          ? null
                          : _SpotifySetupBox(
                              redirectUri: _spotifyRedirectUri,
                              onRedirectChanged: (String uri) =>
                                  setState(() => _spotifyRedirectUri = uri),
                              showManual: _showSpotifyManual,
                              onToggleManual: () => setState(
                                () => _showSpotifyManual = !_showSpotifyManual,
                              ),
                              manualController: _spotifyManualCtrl,
                              exchangingManual: _exchangingManual,
                              onCompleteManual: _completeSpotifyManual,
                            ),
                    ),
                    const SizedBox(height: BgSpace.md),
                    _PairingCard(
                      provider: PairingProvider.lastfm,
                      connected: status.lastfm,
                      account: status.lastfmAccount,
                      busy: _connecting == PairingProvider.lastfm,
                      onConnect: () => _connect(PairingProvider.lastfm),
                      onDisconnect: () => _disconnect(PairingProvider.lastfm),
                      onCancel: () => _cancel?.complete(),
                      extraChild: status.lastfm
                          ? null
                          : _LastfmQuickLinkBox(
                              controller: _lastfmUserCtrl,
                              busy: _linkingUsername,
                              onLinkUsername: _connectLastfmByUsername,
                            ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),

        const SizedBox(height: BgSpace.xxl),

        // --- Install ---------------------------------------------------
        // Relocated from the AppBar (spec §1, row 2). A one-time action does
        // not earn permanent header space, and the three-step instructions
        // are rung 1 here rather than a bottom sheet.
        if (!_pwaBridge.isStandalone) ...<Widget>[
          Section(
            key: _installKey,
            eyebrow: 'INSTALL',
            child: _InstallCard(
              bridge: _pwaBridge,
              showHowTo: _showInstallHowTo,
              onToggleHowTo: () =>
                  setState(() => _showInstallHowTo = !_showInstallHowTo),
            ),
          ),
          const SizedBox(height: BgSpace.xxl),
        ],

        // --- Backend --------------------------------------------------
        Section(
          eyebrow: 'BACKEND',
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(BgSpace.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  _KeyValue(
                    label: 'API base',
                    value: BgConfig.apiBase.isEmpty
                        ? 'same origin'
                        : BgConfig.apiBase,
                  ),
                  const SizedBox(height: BgSpace.sm),
                  _KeyValue(
                    label: 'Status',
                    value: health?.status ?? 'checking…',
                  ),
                  if (health != null && health.capabilities.isNotEmpty) ...[
                    const SizedBox(height: BgSpace.sm),
                    _KeyValue(
                      label: 'Capabilities',
                      value: health.capabilities.entries
                          .map((MapEntry<String, bool> e) =>
                              '${e.key}${e.value ? '' : ' (off)'}')
                          .join(', '),
                    ),
                  ],
                  if (health != null && health.degraded.isNotEmpty) ...<Widget>[
                    const SizedBox(height: BgSpace.lg),
                    DegradedNotes(
                      title: 'Degraded right now',
                      notes: health.degraded,
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),

        const SizedBox(height: BgSpace.xxl),

        // --- About ----------------------------------------------------
        const Section(eyebrow: 'ABOUT', child: _AboutCard()),

        const SizedBox(height: BgSpace.xxl),
      ],
    );
  }
}

/// The relocated PWA install affordance. Rung 0 is one line and one button;
/// the platform-by-platform instructions are rung 1, because they are long
/// and are needed exactly once.
class _InstallCard extends StatelessWidget {
  const _InstallCard({
    required this.bridge,
    required this.showHowTo,
    required this.onToggleHowTo,
  });

  final PwaInstallBridge bridge;
  final bool showHowTo;
  final VoidCallback onToggleHowTo;

  @override
  Widget build(BuildContext context) {
    final BgColors bg = Theme.of(context).bg;
    final bool ready = bridge.isInstallable;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(BgSpace.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Row(
              children: <Widget>[
                Icon(
                  Icons.add_to_home_screen,
                  size: BgIcon.inline,
                  color: bg.inkSecondary,
                ),
                const SizedBox(width: BgSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Text(
                        'Install BAROGROOVE',
                        style: BgText.rowTitle(context),
                      ),
                      Text(
                        ready
                            ? 'Runs standalone, offline-capable, no browser chrome.'
                            : 'Your browser has not offered an install prompt. '
                                'The steps below always work.',
                        style: BgText.caption(context),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: BgSpace.md),
                if (ready)
                  FilledButton(
                    onPressed: () {
                      HapticFeedback.lightImpact();
                      unawaited(bridge.triggerInstall());
                    },
                    child: const Text('Install'),
                  ),
              ],
            ),
            const SizedBox(height: BgSpace.md),
            Divider(color: bg.hairline),
            InkWell(
              borderRadius: BgSpace.brSm,
              onTap: onToggleHowTo,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: BgSpace.md),
                child: Row(
                  children: <Widget>[
                    Expanded(
                      child: Text(
                        'HOW TO INSTALL',
                        style: BgText.eyebrow(context),
                      ),
                    ),
                    AnimatedRotation(
                      turns: showHowTo ? 0.5 : 0,
                      duration: const Duration(milliseconds: 180),
                      child: Icon(
                        Icons.keyboard_arrow_down,
                        size: BgIcon.inline,
                        color: bg.inkSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            if (showHowTo) ...<Widget>[
              const _InstallStep(
                icon: Icons.computer_outlined,
                title: 'Desktop Chrome / Edge',
                body: 'Use the install icon at the right of the address bar, '
                    'or the browser menu → “Install page as app…”.',
              ),
              const SizedBox(height: BgSpace.sm),
              const _InstallStep(
                icon: Icons.phone_android_outlined,
                title: 'Android Chrome',
                body: 'Browser menu → “Add to Home screen” / “Install app”.',
              ),
              const SizedBox(height: BgSpace.sm),
              const _InstallStep(
                icon: Icons.phone_iphone_outlined,
                title: 'iOS Safari',
                body: 'Share → “Add to Home Screen”.',
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _InstallStep extends StatelessWidget {
  const _InstallStep({
    required this.icon,
    required this.title,
    required this.body,
  });

  final IconData icon;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final BgColors bg = Theme.of(context).bg;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Icon(icon, size: BgIcon.inline, color: bg.inkSecondary),
        const SizedBox(width: BgSpace.sm),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(title, style: BgText.rowSubtitle(context)),
              Text(body, style: BgText.caption(context)),
            ],
          ),
        ),
      ],
    );
  }
}

class _PairingCard extends StatelessWidget {
  const _PairingCard({
    required this.provider,
    required this.connected,
    required this.busy,
    required this.onConnect,
    required this.onDisconnect,
    required this.onCancel,
    this.account,
    this.extraChild,
  });

  final PairingProvider provider;
  final bool connected;
  final bool busy;
  final String? account;
  final VoidCallback onConnect;
  final VoidCallback onDisconnect;
  final VoidCallback onCancel;
  final Widget? extraChild;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(BgSpace.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Row(
              children: <Widget>[
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: connected ? BgPalette.ok : colors.outline,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: BgSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Text(provider.label, style: text.titleMedium),
                      Text(
                        connected
                            ? (account == null
                                ? 'Connected'
                                : 'Connected as $account')
                            : 'Not connected',
                        style: text.bodySmall?.copyWith(
                          color: connected
                              ? BgPalette.ok
                              : colors.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
                if (busy) ...<Widget>[
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  const SizedBox(width: BgSpace.md),
                  TextButton(onPressed: onCancel, child: const Text('Cancel')),
                ] else if (connected)
                  OutlinedButton(
                    onPressed: onDisconnect,
                    child: const Text('Disconnect'),
                  )
                else
                  FilledButton(
                    onPressed: onConnect,
                    child: Text(
                      provider == PairingProvider.spotify
                          ? 'Authorize Spotify'
                          : 'Web OAuth',
                    ),
                  ),
              ],
            ),
            const SizedBox(height: BgSpace.md),
            Text(provider.purpose, style: text.bodyMedium),
            if (!connected) ...<Widget>[
              const SizedBox(height: BgSpace.xs),
              Text(
                provider.degradation,
                style: text.bodySmall?.copyWith(color: BgPalette.gold600),
              ),
            ],
            if (extraChild != null) ...<Widget>[
              const SizedBox(height: BgSpace.md),
              extraChild!,
            ],
            if (busy) ...<Widget>[
              const SizedBox(height: BgSpace.md),
              Text(
                'Finish authorising in the tab that just opened. This page '
                'checks every couple of seconds and will notice when you are '
                'done.',
                style: text.bodySmall,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SpotifySetupBox extends StatelessWidget {
  const _SpotifySetupBox({
    required this.redirectUri,
    required this.onRedirectChanged,
    required this.showManual,
    required this.onToggleManual,
    required this.manualController,
    required this.exchangingManual,
    required this.onCompleteManual,
  });

  final String redirectUri;
  final ValueChanged<String> onRedirectChanged;
  final bool showManual;
  final VoidCallback onToggleManual;
  final TextEditingController manualController;
  final bool exchangingManual;
  final VoidCallback onCompleteManual;

  static const List<String> _presets = <String>[
    'https://bg.netdev.be/api/pair/spotify/callback',
    'https://bg.netdev.be/callback',
    'http://localhost:8080/callback',
  ];

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(Icons.tune, size: 15, color: colors.primary),
              const SizedBox(width: BgSpace.xs),
              Expanded(
                child: Text(
                  'SPOTIFY REDIRECT URI CONFIGURATION',
                  style: text.labelSmall?.copyWith(
                    color: colors.primary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              TextButton.icon(
                style: TextButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                  padding: const EdgeInsets.symmetric(horizontal: BgSpace.sm),
                ),
                onPressed: () {
                  launchUrl(
                    Uri.parse(
                      'https://developer.spotify.com/dashboard/f8e0866e33e645749766395480a380b6/settings',
                    ),
                    mode: LaunchMode.externalApplication,
                  );
                },
                icon: const Icon(Icons.open_in_new, size: 14),
                label: const Text('Spotify App Dashboard'),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.xs),
          Text(
            'Ensure the active Redirect URI below is listed in your Spotify Developer Dashboard settings:',
            style: text.bodySmall,
          ),
          const SizedBox(height: BgSpace.sm),
          Row(
            children: <Widget>[
              Expanded(
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: BgSpace.sm,
                    vertical: 6,
                  ),
                  decoration: BoxDecoration(
                    color: colors.surface,
                    borderRadius: BgSpace.brSm,
                    border: Border.all(color: colors.outlineVariant),
                  ),
                  child: SelectableText(
                    redirectUri,
                    style: text.bodySmall?.copyWith(
                      fontFamily: 'monospace',
                      color: colors.onSurface,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                ),
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: redirectUri));
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('Copied $redirectUri to clipboard'),
                      duration: const Duration(seconds: 2),
                    ),
                  );
                },
                icon: const Icon(Icons.copy, size: 14),
                label: const Text('Copy URI'),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.sm),
          Wrap(
            spacing: BgSpace.xs,
            runSpacing: BgSpace.xs,
            children: <Widget>[
              for (final String preset in _presets)
                ChoiceChip(
                  label: Text(
                    preset.replaceFirst('https://bg.netdev.be', ''),
                    style: text.bodySmall?.copyWith(fontSize: 11),
                  ),
                  selected: redirectUri == preset,
                  onSelected: (_) => onRedirectChanged(preset),
                  visualDensity: VisualDensity.compact,
                ),
            ],
          ),
          const SizedBox(height: BgSpace.xs),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              style: TextButton.styleFrom(
                visualDensity: VisualDensity.compact,
                padding: EdgeInsets.zero,
              ),
              onPressed: onToggleManual,
              icon: Icon(
                showManual ? Icons.expand_less : Icons.expand_more,
                size: 16,
              ),
              label: Text(
                showManual
                    ? 'Hide manual callback paste'
                    : 'Redirected to localhost? Paste callback URL / code here',
                style: text.bodySmall?.copyWith(color: colors.primary),
              ),
            ),
          ),
          if (showManual) ...<Widget>[
            const SizedBox(height: BgSpace.xs),
            Row(
              children: <Widget>[
                Expanded(
                  child: TextField(
                    controller: manualController,
                    style: text.bodySmall,
                    decoration: InputDecoration(
                      isDense: true,
                      hintText:
                          'Paste full callback URL (e.g. http://localhost:8080/callback?code=...)',
                      border: OutlineInputBorder(
                        borderRadius: BgSpace.brSm,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: BgSpace.sm),
                FilledButton.tonal(
                  onPressed: exchangingManual ? null : onCompleteManual,
                  child: Text(exchangingManual ? 'Pairing…' : 'Complete'),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _LastfmQuickLinkBox extends StatelessWidget {
  const _LastfmQuickLinkBox({
    required this.controller,
    required this.busy,
    required this.onLinkUsername,
  });

  final TextEditingController controller;
  final bool busy;
  final VoidCallback onLinkUsername;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            'INSTANT LINK BY USERNAME (RECOMMENDED)',
            style: text.labelSmall?.copyWith(
              color: colors.primary,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: BgSpace.xs),
          Text(
            'Link your public Last.fm taste profile directly in one click — no browser redirect needed:',
            style: text.bodySmall,
          ),
          const SizedBox(height: BgSpace.sm),
          Row(
            children: <Widget>[
              Expanded(
                child: TextField(
                  controller: controller,
                  style: text.bodyMedium,
                  decoration: InputDecoration(
                    isDense: true,
                    prefixIcon: const Icon(Icons.person_outline, size: 18),
                    hintText: 'Last.fm username (e.g. jpaquay)',
                    border: OutlineInputBorder(
                      borderRadius: BgSpace.brSm,
                    ),
                  ),
                  onSubmitted: (_) => onLinkUsername(),
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              FilledButton.icon(
                onPressed: busy ? null : onLinkUsername,
                icon: busy
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.bolt, size: 16),
                label: const Text('Link Username'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// About, including the origin story.
class _AboutCard extends ConsumerStatefulWidget {
  const _AboutCard();

  @override
  ConsumerState<_AboutCard> createState() => _AboutCardState();
}

class _AboutCardState extends ConsumerState<_AboutCard> {
  String? _legacy;
  bool _loading = false;

  Future<void> _fetchLegacy() async {
    setState(() => _loading = true);
    final ApiResult<String> res = await ref.read(apiProvider).legacy();
    if (!mounted) return;
    setState(() {
      _loading = false;
      _legacy = res.valueOrNull ?? '(no answer)';
    });
  }

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    final ColorScheme colors = Theme.of(context).colorScheme;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(BgSpace.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text('BAROGROOVE', style: text.titleMedium),
            const SizedBox(height: BgSpace.xs),
            Text(
              'A weather-driven playlist engine. The interface you are '
              'looking at is described by the server and rendered here; there '
              'is only one definition of it.',
              style: text.bodyMedium,
            ),
            const SizedBox(height: BgSpace.lg),
            Divider(color: colors.outlineVariant),
            const SizedBox(height: BgSpace.md),

            // The easter egg. Understated on purpose.
            Row(
              children: <Widget>[
                Expanded(
                  child: Text(
                    'Origin story',
                    style: text.bodySmall,
                  ),
                ),
                TextButton(
                  onPressed: _loading ? null : _fetchLegacy,
                  child: Text(_loading ? '…' : 'GET /legacy'),
                ),
              ],
            ),
            if (_legacy != null)
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(top: BgSpace.sm),
                padding: const EdgeInsets.all(BgSpace.md),
                decoration: BoxDecoration(
                  color: colors.surfaceContainerLow,
                  borderRadius: BgSpace.brSm,
                  border: Border.all(color: colors.outlineVariant),
                ),
                child: Text(
                  _legacy!,
                  style: text.bodyLarge?.copyWith(
                    fontFamily: 'monospace',
                    fontFamilyFallback: const <String>[
                      'Menlo',
                      'Consolas',
                      'monospace',
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _KeyValue extends StatelessWidget {
  const _KeyValue({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        SizedBox(
          width: 120,
          child: Text(label.toUpperCase(), style: text.labelSmall),
        ),
        Expanded(child: Text(value, style: text.bodyMedium)),
      ],
    );
  }
}
