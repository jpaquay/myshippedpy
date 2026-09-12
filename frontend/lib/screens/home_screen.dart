/// The forge screen.
///
/// ## Read this before adding a widget here
///
/// This screen is a FETCHER, not a designer. It does three things:
///
///   1. Asks the backend for `/api/surfaces/sky` and hands the resulting
///      envelopes to an [A2uiSurfaceView].
///   2. Asks for `/api/surfaces/themes` and does the same.
///   3. Owns the Forge button and the location/scenario control, which are
///      shell chrome — they decide *what to ask for*, not *how the answer
///      looks*.
///
/// The sky dial, the theme chips and the genre corridors on this page are all
/// server-described. If a designer wants to reorder them, that is a change to
/// the Python catalog and surface builder, not to this file. The only reason
/// to touch this file is to change how a request is made.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../a2ui/messages.dart';
import '../a2ui/renderer.dart';
import '../api/client.dart';
import '../api/models.dart';
import '../app_theme.dart';
import '../providers.dart';
import 'shell.dart';
import 'widgets/section.dart';
import 'widgets/status_notes.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  bool _loadingSurfaces = true;
  bool _forging = false;
  String? _surfaceError;
  String? _forgeError;

  @override
  void initState() {
    super.initState();
    // Fetch after the first frame so the controllers exist.
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadSurfaces());
  }

  /// Pulls both surfaces and feeds them straight into their controllers.
  /// Note what is absent: any inspection of the messages. We do not look
  /// inside; the renderer does.
  Future<void> _loadSurfaces() async {
    setState(() {
      _loadingSurfaces = true;
      _surfaceError = null;
    });

    final BarogrooveApi api = ref.read(apiProvider);
    final ForgeSelection selection = ref.read(forgeSelectionProvider);

    final List<ApiResult<List<A2uiMessage>>> results =
        await Future.wait(<Future<ApiResult<List<A2uiMessage>>>>[
      api.skySurface(lat: selection.lat, lon: selection.lon),
      api.themesSurface(),
    ]);

    if (!mounted) return;

    final A2uiSurfaceController sky =
        ref.read(surfaceControllerProvider('sky'));
    final A2uiSurfaceController themes =
        ref.read(surfaceControllerProvider('themes'));

    final List<String> problems = <String>[];

    results[0].when(
      ok: sky.applyAll,
      failed: (ApiFailure<List<A2uiMessage>> f) => problems.add(f.message),
    );
    results[1].when(
      ok: themes.applyAll,
      failed: (ApiFailure<List<A2uiMessage>> f) => problems.add(f.message),
    );

    setState(() {
      _loadingSurfaces = false;
      _surfaceError = problems.isEmpty ? null : problems.join(' ');
    });
  }

  Future<void> _forge() async {
    setState(() {
      _forging = true;
      _forgeError = null;
    });

    final BarogrooveApi api = ref.read(apiProvider);
    final bool signedIn = ref.read(isSignedInProvider);
    final A2uiSurfaceController themes =
        ref.read(surfaceControllerProvider('themes'));
    final String? themeFromSurface =
        themes.dataModel.resolveEntry('/themes/selectedThemeId').value as String?;
    final String? genreFromSurface =
        themes.dataModel.resolveEntry('/genres/selectedGenreId').value as String?;
    final ForgeSelection selection = ref.read(forgeSelectionProvider).copyWith(
          themeId: themeFromSurface,
          genreId: genreFromSurface,
        );

    // Signed out gets the zero-credential demo unless they explicitly selected
    // a theme or genre on the surface.
    final ApiResult<ForgeResult> result =
        (signedIn || themeFromSurface != null || genreFromSurface != null)
            ? await api.forge(selection.toRequest())
            : await api.demoForge();

    if (!mounted) return;

    result.when(
      ok: (ForgeResult r) {
        ref.read(lastForgeProvider.notifier).state = r;
        AppShell.of(context)?.go(BgDestination.playlist);
      },
      failed: (ApiFailure<ForgeResult> f) =>
          setState(() => _forgeError = f.message),
    );

    if (mounted) setState(() => _forging = false);
  }

  @override
  Widget build(BuildContext context) {
    final A2uiSurfaceController sky =
        ref.watch(surfaceControllerProvider('sky'));
    final A2uiSurfaceController themes =
        ref.watch(surfaceControllerProvider('themes'));
    final bool signedIn = ref.watch(isSignedInProvider);
    final health = ref.watch(healthProvider).valueOrNull;

    return RefreshIndicator(
      onRefresh: _loadSurfaces,
      child: ListView(
        padding: const EdgeInsets.symmetric(
          horizontal: BgSpace.xl,
          vertical: BgSpace.lg,
        ),
        children: <Widget>[
          _ForgeHeader(onRefresh: _loadingSurfaces ? null : _loadSurfaces),

          if (health != null && health.degraded.isNotEmpty) ...<Widget>[
            const SizedBox(height: BgSpace.lg),
            DegradedNotes(
              title: 'The backend is running degraded',
              notes: health.degraded,
            ),
          ],

          if (_surfaceError != null) ...<Widget>[
            const SizedBox(height: BgSpace.lg),
            DegradedNotes(
              title: 'Some of this page did not load',
              notes: <String>[_surfaceError!],
              tone: DegradedTone.error,
            ),
          ],

          const SizedBox(height: BgSpace.xl),

          // --- SERVER-DESCRIBED: the sky reading ---------------------------
          Section(
            eyebrow: 'CURRENT READING',
            child: _loadingSurfaces && !sky.isCreated
                ? const _SurfaceSkeleton(height: 300)
                : A2uiSurfaceView(
                    controller: sky,
                    padding: EdgeInsets.zero,
                    emptyState: const _SurfaceSkeleton(height: 300),
                  ),
          ),

          const SizedBox(height: BgSpace.xxl),

          // --- SERVER-DESCRIBED: themes and corridors ----------------------
          Section(
            eyebrow: 'SHAPE THE SET',
            child: _loadingSurfaces && !themes.isCreated
                ? const _SurfaceSkeleton(height: 200)
                : A2uiSurfaceView(
                    controller: themes,
                    padding: EdgeInsets.zero,
                    emptyState: const _SurfaceSkeleton(height: 200),
                  ),
          ),

          const SizedBox(height: BgSpace.xxl),

          // --- SHELL CHROME: the trigger -----------------------------------
          if (_forgeError != null) ...<Widget>[
            DegradedNotes(
              title: 'The forge failed',
              notes: <String>[_forgeError!],
              tone: DegradedTone.error,
            ),
            const SizedBox(height: BgSpace.lg),
          ],
          Row(
            children: <Widget>[
              Expanded(
                child: FilledButton.icon(
                  onPressed: _forging ? null : _forge,
                  icon: _forging
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.bolt_outlined, size: 18),
                  label: Text(
                    _forging
                        ? 'Forging…'
                        : signedIn
                            ? 'Forge the set'
                            : 'Forge the demo set',
                  ),
                ),
              ),
            ],
          ),
          if (!signedIn) ...<Widget>[
            const SizedBox(height: BgSpace.md),
            Text(
              'You are not signed in, so this runs the zero-credential demo '
              'forge. It is a real forge — it just cannot read your taste or '
              'write to your Almanac.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
          const SizedBox(height: BgSpace.xxl),
        ],
      ),
    );
  }
}

class _ForgeHeader extends StatelessWidget {
  const _ForgeHeader({this.onRefresh});

  final VoidCallback? onRefresh;

  @override
  Widget build(BuildContext context) {
    final TextTheme text = Theme.of(context).textTheme;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text('Forge', style: text.displaySmall),
              const SizedBox(height: BgSpace.xs),
              Text(
                'Read the sky, then turn it into a set.',
                style: text.bodyLarge?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
        IconButton(
          tooltip: 'Re-read the sky',
          onPressed: onRefresh,
          icon: const Icon(Icons.refresh),
        ),
      ],
    );
  }
}

/// A neutral block while a surface is in flight. Not a shimmer — this is an
/// instrument, and instruments do not shimmer.
class _SurfaceSkeleton extends StatelessWidget {
  const _SurfaceSkeleton({required this.height});

  final double height;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Container(
      height: height,
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BgSpace.br,
        border: Border.all(color: colors.outlineVariant),
      ),
      alignment: Alignment.center,
      child: SizedBox(
        width: 120,
        child: LinearProgressIndicator(
          minHeight: 2,
          backgroundColor: colors.surfaceContainer,
        ),
      ),
    );
  }
}
