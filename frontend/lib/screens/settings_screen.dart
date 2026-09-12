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
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../app_theme.dart';
import '../auth/auth_service.dart';
import '../auth/pairing_service.dart';
import '../config.dart';
import '../providers.dart';
import 'widgets/section.dart';
import 'widgets/status_notes.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  PairingProvider? _connecting;
  Completer<void>? _cancel;
  String? _pairingMessage;

  Future<void> _connect(PairingProvider provider) async {
    final Completer<void> cancel = Completer<void>();
    setState(() {
      _connecting = provider;
      _cancel = cancel;
      _pairingMessage = null;
    });

    final PairingAttempt attempt = await ref
        .read(pairingServiceProvider)
        .connect(provider, cancelled: cancel.future);

    if (!mounted) return;

    ref.invalidate(pairingStatusProvider);
    setState(() {
      _connecting = null;
      _cancel = null;
      _pairingMessage = attempt.ok ? null : attempt.message;
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

    return ListView(
      padding: const EdgeInsets.symmetric(
        horizontal: BgSpace.xl,
        vertical: BgSpace.lg,
      ),
      children: <Widget>[
        Text('Settings', style: Theme.of(context).textTheme.displaySmall),
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

        // --- Pairing --------------------------------------------------
        Section(
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
                      onConnect: () => _connect(PairingProvider.spotify),
                      onDisconnect: () =>
                          _disconnect(PairingProvider.spotify),
                      onCancel: () => _cancel?.complete(),
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
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),

        const SizedBox(height: BgSpace.xxl),

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

class _PairingCard extends StatelessWidget {
  const _PairingCard({
    required this.provider,
    required this.connected,
    required this.busy,
    required this.onConnect,
    required this.onDisconnect,
    required this.onCancel,
    this.account,
  });

  final PairingProvider provider;
  final bool connected;
  final bool busy;
  final String? account;
  final VoidCallback onConnect;
  final VoidCallback onDisconnect;
  final VoidCallback onCancel;

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
                    child: const Text('Connect'),
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
