/// BAROGROOVE — your sky has a soundtrack.
///
/// App bootstrap. Firebase init, theme, and the one routing decision this app
/// makes: signed in -> the shell, signed out -> the sign-in screen (with an
/// escape hatch to the demo forge, because the product should be legible
/// before you hand over an account).
///
/// Everything past that point is rendered from A2UI. See lib/a2ui/renderer.dart
/// and the note in README.md before you add a screen.
library;

import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app_theme.dart';
import 'auth/sign_in_screen.dart';
import 'firebase_options.dart';
import 'providers.dart';
import 'screens/shell.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(BgTheme.lightOverlay);

  // Firebase init can fail for reasons the user can act on (placeholder
  // config, an offline first run, a domain that is not authorised). We catch
  // it and render an explanation instead of a grey screen and a console
  // stack trace nobody will read.
  String? bootError;
  if (DefaultFirebaseOptions.isPlaceholder) {
    bootError = 'Firebase is still configured with placeholders. Run '
        '`flutterfire configure` to generate lib/firebase_options.dart, then '
        'restart.';
  } else {
    try {
      await Firebase.initializeApp(
        options: DefaultFirebaseOptions.currentPlatform,
      );
    } on FirebaseException catch (e) {
      bootError = 'Firebase failed to start: ${e.message ?? e.code}';
    } catch (e) {
      bootError = 'Firebase failed to start: $e';
    }
  }

  runApp(
    ProviderScope(
      child: BarogrooveApp(bootError: bootError),
    ),
  );
}

class BarogrooveApp extends ConsumerWidget {
  const BarogrooveApp({this.bootError, super.key});

  final String? bootError;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp(
      title: 'BAROGROOVE',
      debugShowCheckedModeBanner: false,

      // Light is the default and the intended register. The dark variant
      // exists because a system-wide dark preference is not something to
      // override, but the app was designed light.
      theme: BgTheme.light(),
      darkTheme: BgTheme.dark(),
      themeMode: ThemeMode.light,

      home: bootError != null
          ? _BootFailure(message: bootError!)
          : const _RootRouter(),
    );
  }
}

/// The whole router. Four lines, because everything interesting is inside the
/// shell and the shell's content comes from the server.
class _RootRouter extends ConsumerStatefulWidget {
  const _RootRouter();

  @override
  ConsumerState<_RootRouter> createState() => _RootRouterState();
}

class _RootRouterState extends ConsumerState<_RootRouter> {
  /// Set when the visitor chooses the demo instead of signing in.
  bool _browsingAnonymously = false;

  @override
  void initState() {
    super.initState();
    // Try to restore a mobile session silently before showing sign-in.
    // Deliberately not awaited: the sign-in screen is a fine thing to show
    // while this runs, and it swallows its own failures.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      unawaited(ref.read(authServiceProvider).restoreSession());
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authStateProvider);

    return auth.when(
      loading: () => const _Splash(),
      error: (Object e, StackTrace _) => _BootFailure(
        message: 'Could not read the auth state: $e',
      ),
      data: (user) {
        if (user != null || _browsingAnonymously) {
          return const AppShell();
        }
        return SignInScreen(
          onSkip: () => setState(() => _browsingAnonymously = true),
        );
      },
    );
  }
}

class _Splash extends StatelessWidget {
  const _Splash();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).colorScheme.surfaceContainerLow,
      body: const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            BarogrooveWordmark(),
            SizedBox(height: BgSpace.xl),
            SizedBox(
              width: 120,
              child: LinearProgressIndicator(minHeight: 2),
            ),
          ],
        ),
      ),
    );
  }
}

/// Shown when the app cannot start. States the problem and what to do about
/// it, which is more than a stack trace does.
class _BootFailure extends StatelessWidget {
  const _BootFailure({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    final ColorScheme colors = Theme.of(context).colorScheme;

    return Scaffold(
      backgroundColor: colors.surfaceContainerLow,
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Padding(
            padding: const EdgeInsets.all(BgSpace.xl),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(BgSpace.xxl),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    const BarogrooveWordmark(),
                    const SizedBox(height: BgSpace.xl),
                    Text('Cannot start', style: text.headlineSmall),
                    const SizedBox(height: BgSpace.md),
                    Text(message, style: text.bodyMedium),
                    if (kDebugMode) ...<Widget>[
                      const SizedBox(height: BgSpace.lg),
                      Text(
                        'This screen only appears when Firebase could not be '
                        'initialised. The rest of the app never white-screens '
                        'on a bad response — see the renderer\'s placeholder '
                        'policy.',
                        style: text.bodySmall,
                      ),
                    ],
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
