/// The sign-in screen.
///
/// Legitimately hand-built chrome: there is no surface stream to render
/// before you have a session, and the agent has nothing to say to an
/// anonymous visitor beyond the demo forge. Everything past this screen comes
/// from A2UI.
///
/// The copy does one job: explain what BAROGROOVE is in two lines, and make
/// clear that you can look before you sign in.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../app_theme.dart';
import '../providers.dart';
import 'auth_service.dart';

class SignInScreen extends ConsumerStatefulWidget {
  const SignInScreen({this.onSkip, super.key});

  /// Lets the visitor into the demo forge without an account.
  final VoidCallback? onSkip;

  @override
  ConsumerState<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends ConsumerState<SignInScreen> {
  bool _busy = false;
  String? _error;

  Future<void> _signIn() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authServiceProvider).signInWithGoogle();
      // Routing is driven by authStateProvider; nothing to do here.
    } on AuthFailure catch (e) {
      if (!mounted) return;
      setState(() => _error = e.code == 'cancelled' ? null : e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Scaffold(
      backgroundColor: colors.surfaceContainerLow,
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(BgSpace.xl),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(BgSpace.xxl),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    const BarogrooveWordmark(),
                    const SizedBox(height: BgSpace.xl),
                    Text(
                      'Your sky has a soundtrack.',
                      style: text.headlineMedium,
                    ),
                    const SizedBox(height: BgSpace.md),
                    Text(
                      'BAROGROOVE reads the derivative of your weather — how '
                      'fast the pressure is moving, not just what it says — '
                      'and forges a playlist that argues for itself.',
                      style: text.bodyLarge?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: BgSpace.xxl),

                    if (_error != null) ...<Widget>[
                      _ErrorNote(message: _error!),
                      const SizedBox(height: BgSpace.lg),
                    ],

                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        onPressed: _busy ? null : _signIn,
                        icon: _busy
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Icon(Icons.login, size: 18),
                        label: Text(
                          _busy ? 'Signing in…' : 'Continue with Google',
                        ),
                      ),
                    ),

                    if (widget.onSkip != null) ...<Widget>[
                      const SizedBox(height: BgSpace.md),
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton(
                          onPressed: _busy ? null : widget.onSkip,
                          child: const Text('Try the demo forge instead'),
                        ),
                      ),
                    ],

                    const SizedBox(height: BgSpace.xl),
                    Divider(color: colors.outlineVariant),
                    const SizedBox(height: BgSpace.lg),
                    Text(
                      'An account stores your Almanac and lets you connect '
                      'Spotify and Last.fm. The demo forge needs neither.',
                      style: text.bodySmall,
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The wordmark. A barometer needle over a baseline — flat, two colours, no
/// gradient. It should look like it belongs on an instrument.
class BarogrooveWordmark extends StatelessWidget {
  const BarogrooveWordmark({this.compact = false, super.key});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Container(
          width: compact ? 24 : 32,
          height: compact ? 24 : 32,
          decoration: BoxDecoration(
            color: colors.primary,
            borderRadius: BorderRadius.circular(compact ? 6 : 8),
          ),
          child: Icon(
            Icons.speed_rounded,
            size: compact ? 15 : 20,
            color: colors.onPrimary,
          ),
        ),
        SizedBox(width: compact ? BgSpace.sm : BgSpace.md),
        Text(
          'BAROGROOVE',
          style: (compact ? text.titleMedium : text.titleLarge)?.copyWith(
            letterSpacing: compact ? 1.4 : 2.0,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}

class _ErrorNote extends StatelessWidget {
  const _ErrorNote({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border(
          left: BorderSide(color: colors.error, width: 3),
          top: BorderSide(color: colors.outlineVariant),
          right: BorderSide(color: colors.outlineVariant),
          bottom: BorderSide(color: colors.outlineVariant),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(Icons.error_outline, size: 18, color: colors.error),
          const SizedBox(width: BgSpace.sm),
          Expanded(
            child: Text(
              message,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        ],
      ),
    );
  }
}
