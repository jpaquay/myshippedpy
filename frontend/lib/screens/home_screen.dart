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
import 'widgets/atmospheric_cursors_console.dart';
import 'widgets/console/console_tokens.dart';
import 'widgets/console/forge_sky_block.dart';
import 'widgets/console/forge_sky_reading.dart';
import 'widgets/netdev_footer.dart';
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
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadSurfaces();
      // A forge may already be running on the server from before this screen
      // existed. Rejoin it rather than offering to start a second one.
      _resumeForgeJob();
    });
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

  Future<void> _teleportRandomGeocache() async {
    final BarogrooveApi api = ref.read(apiProvider);
    final ForgeSelection current = ref.read(forgeSelectionProvider);
    final ApiResult<StreetArtGeoCache> res =
        await api.randomGeocache(excludeId: current.geocacheId);
    if (!mounted) return;
    res.when(
      ok: (StreetArtGeoCache gc) {
        ref.read(activeGeocacheProvider.notifier).state = gc;
        ref.read(forgeSelectionProvider.notifier).setGeocache(gc);
        _loadSurfaces();
      },
      failed: (_) {},
    );
  }

  Future<void> _forge() async {
    setState(() {
      _forging = true;
      _forgeError = null;
    });

    final BarogrooveApi api = ref.read(apiProvider);
    final A2uiSurfaceController themes =
        ref.read(surfaceControllerProvider('themes'));
    final String? themeFromSurface =
        themes.dataModel.resolveEntry('/themes/selectedThemeId').value as String?;
    final String? genreFromSurface =
        themes.dataModel.resolveEntry('/genres/selectedGenreId').value as String?;
    final Set<String> seedSet = ref.read(selectedSeedScrobblesProvider);
    final ForgeSelection selection = ref.read(forgeSelectionProvider).copyWith(
          themeId: themeFromSurface,
          genreId: genreFromSurface,
          seedScrobbles: seedSet.toList(),
        );

    // Reuse the id of a run we are already following, so a double tap or a
    // rebuild cannot start a second forge. Otherwise mint a fresh one: it is
    // the idempotency key the backend dedupes on, so a retried start (ours or
    // the transport's) is absorbed rather than duplicated.
    final String jobId = ref.read(forgeJobIdProvider) ?? _newJobId();
    ref.read(forgeJobIdProvider.notifier).state = jobId;

    final ApiResult<ForgeJob> started =
        await api.startForgeJob(selection.toRequest(), jobId: jobId);

    if (!mounted) return;

    final ApiFailure<ForgeJob>? failure = started.failureOrNull;
    if (failure != null) {
      ref.read(forgeJobIdProvider.notifier).state = null;
      setState(() {
        _forgeError = failure.message;
        _forging = false;
      });
      return;
    }

    await _followForgeJob(started.valueOrNull!.id);
  }

  /// An idempotency key. Only needs to be unique per client, not globally.
  String _newJobId() =>
      'bg-${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}'
      '-${identityHashCode(this).toRadixString(36)}';

  /// Rejoins a forge that was already running when this screen appeared.
  ///
  /// Two ways back in: the id we kept in [forgeJobIdProvider] (survives
  /// navigation and backgrounding), or — after a reload wiped that — whatever
  /// the backend still has in flight for this caller.
  Future<void> _resumeForgeJob() async {
    if (_forging) return;

    String? jobId = ref.read(forgeJobIdProvider);
    if (jobId == null) {
      final ApiResult<List<ForgeJob>> active =
          await ref.read(apiProvider).activeForgeJobs();
      final List<ForgeJob> jobs = active.valueOrNull ?? const <ForgeJob>[];
      if (jobs.isEmpty) return;
      jobId = jobs.first.id;
      if (!mounted) return;
      ref.read(forgeJobIdProvider.notifier).state = jobId;
    }

    if (!mounted) return;
    setState(() {
      _forging = true;
      _forgeError = null;
    });
    await _followForgeJob(jobId);
  }

  /// Polls one job to completion and lands the result.
  Future<void> _followForgeJob(String jobId) async {
    try {
      await for (final ForgeJob job
          in ref.read(apiProvider).watchForgeJob(jobId)) {
        if (!mounted) return;
        if (!job.isTerminal) continue;

        ref.read(forgeJobIdProvider.notifier).state = null;
        if (job.isDone && job.result != null) {
          ref.read(lastForgeProvider.notifier).state = job.result;
          AppShell.of(context)?.go(BgDestination.playlist);
        } else {
          setState(() => _forgeError = job.error ?? 'The forge failed.');
        }
      }
    } on ApiFailure<ForgeJob> catch (f) {
      if (!mounted) return;
      // A 404 means this backend no longer knows the job — it restarted, or
      // we polled a different instance. Forget it so the button offers a
      // fresh run rather than pinning us to a ghost.
      if (f.kind == ApiFailureKind.notFound) {
        ref.read(forgeJobIdProvider.notifier).state = null;
      }
      setState(() => _forgeError = f.message);
    } finally {
      if (mounted) setState(() => _forging = false);
    }
  }

  /// Lifts the three at-a-glance values out of the server-described `sky`
  /// surface (§3.1). Nothing is computed here: every string is the `display`
  /// the Python surface builder already published, so the strip and the dial
  /// can never disagree. A surface that has not arrived yields nulls and the
  /// strip prints `—`.
  ForgeSkyReading _readSky(A2uiSurfaceController sky) {
    if (!sky.isCreated) return ForgeSkyReading.unavailable;

    String? dimensionDisplay(String id) {
      final Object? dims = sky.dataModel.resolve('/sky/dimensions');
      if (dims is! List<Object?>) return null;
      for (final Object? entry in dims) {
        if (entry is Map<String, Object?> && entry['dimensionId'] == id) {
          final Object? display = entry['display'];
          return display is String ? display : null;
        }
      }
      return null;
    }

    final Object? heroTone = sky.dataModel.resolve('/sky/heroTone');
    final Object? heroDisplay = sky.dataModel.resolve('/sky/heroDisplay');
    final Object? heroCaption = sky.dataModel.resolve('/sky/heroCaption');

    return ForgeSkyReading(
      trendDisplay: heroDisplay is String ? heroDisplay : null,
      trendTone: heroTone is String ? heroTone : null,
      trendCaption: heroCaption is String ? heroCaption : null,
      tempDisplay: dimensionDisplay('temp_norm_deviation'),
      lightDisplay: dimensionDisplay('sun_elevation'),
      stale: sky.dataModel.resolve('/sky/stale') == true,
    );
  }

  @override
  Widget build(BuildContext context) {
    final A2uiSurfaceController sky =
        ref.watch(surfaceControllerProvider('sky'));
    final A2uiSurfaceController themes =
        ref.watch(surfaceControllerProvider('themes'));
    final bool signedIn = ref.watch(isSignedInProvider);
    final health = ref.watch(healthProvider).valueOrNull;
    final ForgeSelection selection = ref.watch(forgeSelectionProvider);
    final List<StreetArtGeoCache> geocaches =
        ref.watch(geocachesProvider).valueOrNull ?? const <StreetArtGeoCache>[];
    final StreetArtGeoCache? activeGc = ref.watch(activeGeocacheProvider) ??
        (geocaches.isNotEmpty
            ? geocaches.firstWhere(
                (StreetArtGeoCache g) => g.id == selection.geocacheId,
                orElse: () => geocaches.first,
              )
            : null);
    final Set<String> seedScrobbles = ref.watch(selectedSeedScrobblesProvider);
    final String? selectedThemeId =
        themes.dataModel.resolveEntry('/themes/selectedThemeId').value as String?;
    final String? selectedGenreId =
        themes.dataModel.resolveEntry('/genres/selectedGenreId').value as String?;

    final bool isMobile = MediaQuery.sizeOf(context).width < 600;

    return RefreshIndicator(
      onRefresh: _loadSurfaces,
      child: ListView(
        physics: const BouncingScrollPhysics(
          parent: AlwaysScrollableScrollPhysics(),
        ),
        padding: EdgeInsets.symmetric(
          horizontal: isMobile ? BgSpace.md : BgSpace.xl,
          vertical: BgSpace.lg,
        ),
        children: <Widget>[
          // The Gemini Live banner that used to sit here is gone (§6.1). The
          // assistant is app chrome now — one floating bubble in the shell's
          // Stack, reachable from every destination, with one conversation
          // that survives navigation. Forge no longer hosts a copy of it.
          _ForgeHeader(
            selection: selection,
            geocaches: geocaches,
            activeGeocache: activeGc,
            seedScrobbles: seedScrobbles,
            onTeleportRandom: _loadingSurfaces ? null : _teleportRandomGeocache,
            onSelectGeocache: (StreetArtGeoCache gc) {
              ref.read(activeGeocacheProvider.notifier).state = gc;
              ref.read(forgeSelectionProvider.notifier).setGeocache(gc);
              _loadSurfaces();
            },
            onSelectCity: (double lat, double lon, String label) {
              ref.read(activeGeocacheProvider.notifier).state = null;
              ref
                  .read(forgeSelectionProvider.notifier)
                  .setLocation(lat, lon, label: label);
              _loadSurfaces();
            },
            onClearSeedScrobbles: () {
              ref.read(selectedSeedScrobblesProvider.notifier).state = <String>{};
            },
            onRefresh: _loadingSurfaces ? null : _loadSurfaces,
          ),

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
          // How much of it shows is the console's business, not this file's:
          // Guided gets three values, Easy hides the dial behind SKY DETAIL,
          // Expert promotes the dial to first glance (spec §5.2).
          Section(
            eyebrow: 'CURRENT BAROMETRIC READING',
            child: _loadingSurfaces && !sky.isCreated
                ? const _SurfaceSkeleton(height: 300)
                : ForgeSkyBlock(
                    reading: _readSky(sky),
                    dial: A2uiSurfaceView(
                      controller: sky,
                      padding: EdgeInsets.zero,
                      emptyState: const _SurfaceSkeleton(height: 300),
                    ),
                  ),
          ),

          const SizedBox(height: BgSpace.xl),

          // --- THE FORGE CONSOLE: guided / easy / expert -------------------
          AtmosphericCursorsConsole(skyReading: _readSky(sky)),

          const SizedBox(height: BgSpace.xxl),

          // --- SERVER-DESCRIBED: themes and corridors ----------------------
          Section(
            eyebrow: 'SONIC CURATION CONSOLE',
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
          _ForgeActionDeck(
            forging: _forging,
            signedIn: signedIn,
            selection: selection,
            selectedThemeId: selectedThemeId,
            selectedGenreId: selectedGenreId,
            onForge: _forging ? null : _forge,
          ),
          const SizedBox(height: BgSpace.lg),
          const NetdevFooter(),
          // §7.2: bottom padding equals the assistant-bubble clearance, so the
          // floating bubble that replaces the inline Live banners (§6.2) can
          // never sit on top of the FORGE call to action.
          const SizedBox(height: ForgeMetrics.bubbleClearance),
        ],
      ),
    );
  }
}

class _ObservatoryPreset {
  const _ObservatoryPreset(this.label, this.lat, this.lon, this.coordsLabel);
  final String label;
  final double lat;
  final double lon;
  final String coordsLabel;
}

const List<_ObservatoryPreset> _kObservatories = <_ObservatoryPreset>[
  _ObservatoryPreset('Brussels', 50.8503, 4.3517, '50.85°N 4.35°E'),
  _ObservatoryPreset('Reykjavik', 64.1466, -21.9426, '64.15°N 21.94°W'),
  _ObservatoryPreset('Tokyo', 35.6762, 139.6503, '35.68°N 139.65°E'),
  _ObservatoryPreset('Berlin', 52.5200, 13.4050, '52.52°N 13.41°E'),
  _ObservatoryPreset('New York', 40.7128, -74.0060, '40.71°N 74.01°W'),
  _ObservatoryPreset('San Francisco', 37.7749, -122.4194, '37.77°N 122.42°W'),
];

class _ForgeHeader extends StatelessWidget {
  const _ForgeHeader({
    required this.selection,
    required this.geocaches,
    required this.activeGeocache,
    required this.seedScrobbles,
    required this.onTeleportRandom,
    required this.onSelectGeocache,
    required this.onSelectCity,
    required this.onClearSeedScrobbles,
    required this.onRefresh,
  });

  final ForgeSelection selection;
  final List<StreetArtGeoCache> geocaches;
  final StreetArtGeoCache? activeGeocache;
  final Set<String> seedScrobbles;
  final VoidCallback? onTeleportRandom;
  final void Function(StreetArtGeoCache gc) onSelectGeocache;
  final void Function(double lat, double lon, String label) onSelectCity;
  final VoidCallback onClearSeedScrobbles;
  final VoidCallback? onRefresh;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: <Color>[
            colors.surfaceContainerHigh,
            colors.surface,
          ],
        ),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: colors.primary.withValues(alpha: 0.28),
        ),
        boxShadow: <BoxShadow>[
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.22),
            blurRadius: 18,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 4,
                ),
                decoration: BoxDecoration(
                  color: colors.primary.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(
                    color: colors.primary.withValues(alpha: 0.35),
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Icon(
                      Icons.sensors_outlined,
                      size: 13,
                      color: colors.primary,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      'GOOGLE WEATHER API • WORLD STREET-ART GEO-CACHES',
                      style: text.labelSmall?.copyWith(
                        color: colors.primary,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.8,
                      ),
                    ),
                  ],
                ),
              ),
              const Spacer(),
              FilledButton.tonalIcon(
                onPressed: onTeleportRandom,
                icon: const Icon(Icons.casino_outlined, size: 17),
                label: const Text(
                  '🎲 TELEPORT STREET-ART GEO-CACHE',
                  style: TextStyle(fontWeight: FontWeight.w700, fontSize: 12),
                ),
              ),
              const SizedBox(width: BgSpace.xs),
              IconButton(
                tooltip: 'Re-read the sky',
                onPressed: onRefresh,
                icon: const Icon(Icons.refresh, size: 20),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.sm),
          Text(
            'Atmospheric Sonic Forge',
            style: text.headlineMedium?.copyWith(
              fontWeight: FontWeight.w700,
              letterSpacing: -0.4,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Teleport across global street-art landmarks to sample diverse local timezones, barometric fronts, and regional sonic vibes.',
            style: text.bodyMedium?.copyWith(
              color: colors.onSurfaceVariant,
            ),
          ),

          if (seedScrobbles.isNotEmpty) ...<Widget>[
            const SizedBox(height: BgSpace.md),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: colors.tertiaryContainer.withValues(alpha: 0.45),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: colors.tertiary.withValues(alpha: 0.5)),
              ),
              child: Row(
                children: <Widget>[
                  Icon(Icons.auto_awesome, size: 16, color: colors.tertiary),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Almanac Scrobble Seed Active: ${seedScrobbles.length} track(s) selected (${seedScrobbles.take(2).join(", ")}${seedScrobbles.length > 2 ? "..." : ""})',
                      style: text.labelMedium?.copyWith(
                        color: colors.onSurface,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  TextButton.icon(
                    onPressed: onClearSeedScrobbles,
                    icon: const Icon(Icons.clear, size: 14),
                    label: const Text('Clear Seed'),
                  ),
                ],
              ),
            ),
          ],

          if (activeGeocache != null) ...<Widget>[
            const SizedBox(height: BgSpace.md),
            Container(
              padding: const EdgeInsets.all(BgSpace.md),
              decoration: BoxDecoration(
                color: colors.surfaceContainerHighest.withValues(alpha: 0.55),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: colors.primary.withValues(alpha: 0.35)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Row(
                    children: <Widget>[
                      Icon(Icons.palette_rounded, size: 18, color: colors.primary),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          '${activeGeocache!.name} • ${activeGeocache!.city}, ${activeGeocache!.country}',
                          style: text.titleMedium?.copyWith(
                            fontWeight: FontWeight.w800,
                            color: colors.onSurface,
                          ),
                        ),
                      ),
                      // No clock, no chip. `local_time` and `day_period` used
                      // to be parsed with `?? '14:00 (UTC+1)'` and
                      // `?? 'afternoon'`, so a landmark the backend sent no
                      // clock for still wore a confident local time.
                      if (activeGeocache!.localTime.isNotEmpty ||
                          activeGeocache!.dayPeriod.isNotEmpty)
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            color: colors.primary.withValues(alpha: 0.18),
                            borderRadius: BorderRadius.circular(14),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: <Widget>[
                              Icon(Icons.schedule, size: 13, color: colors.primary),
                              const SizedBox(width: 4),
                              Text(
                                <String>[
                                  if (activeGeocache!.localTime.isNotEmpty)
                                    'Local: ${activeGeocache!.localTime}',
                                  if (activeGeocache!.dayPeriod.isNotEmpty)
                                    activeGeocache!.dayPeriod.toUpperCase(),
                                ].join(' • '),
                                style: text.labelSmall?.copyWith(
                                  color: colors.primary,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    activeGeocache!.description,
                    style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
                  ),
                  const SizedBox(height: 6),
                  Row(
                    children: <Widget>[
                      Icon(Icons.brush_outlined, size: 13, color: colors.secondary),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          'Featured Artists: ${activeGeocache!.artistHighlight}',
                          style: text.labelSmall?.copyWith(
                            color: colors.secondary,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      Wrap(
                        spacing: 4,
                        children: activeGeocache!.vibeTags.map((String tag) {
                          return Container(
                            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              color: colors.surface,
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(color: colors.outlineVariant),
                            ),
                            child: Text(
                              '#$tag',
                              style: text.labelSmall?.copyWith(fontSize: 10),
                            ),
                          );
                        }).toList(),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ],

          const SizedBox(height: BgSpace.md),
          Text(
            'GLOBAL STREET-ART LANDMARKS (TAP TO TELEPORT):',
            style: text.labelSmall?.copyWith(
              color: colors.onSurfaceVariant,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.7,
            ),
          ),
          const SizedBox(height: BgSpace.xs),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: geocaches.isNotEmpty
                  ? geocaches.map((StreetArtGeoCache gc) {
                      final bool active = activeGeocache?.id == gc.id;
                      return Padding(
                        padding: const EdgeInsets.only(right: BgSpace.xs),
                        child: InkWell(
                          borderRadius: BorderRadius.circular(20),
                          onTap: () => onSelectGeocache(gc),
                          child: AnimatedContainer(
                            duration: const Duration(milliseconds: 160),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 7,
                            ),
                            decoration: BoxDecoration(
                              color: active
                                  ? colors.primary
                                  : colors.surfaceContainerHighest.withValues(alpha: 0.6),
                              borderRadius: BorderRadius.circular(20),
                              border: Border.all(
                                color: active
                                    ? colors.primary
                                    : colors.outlineVariant,
                              ),
                            ),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: <Widget>[
                                Icon(
                                  active ? Icons.palette : Icons.place_outlined,
                                  size: 13,
                                  color: active
                                      ? colors.onPrimary
                                      : colors.onSurfaceVariant,
                                ),
                                const SizedBox(width: 6),
                                Text(
                                  '${gc.name} (${gc.city})',
                                  style: text.labelMedium?.copyWith(
                                    color: active
                                        ? colors.onPrimary
                                        : colors.onSurface,
                                    fontWeight:
                                        active ? FontWeight.w700 : FontWeight.w500,
                                  ),
                                ),
                                // Omitted rather than guessed when the record
                                // carries no local time.
                                if (gc.localTime.isNotEmpty) ...<Widget>[
                                  const SizedBox(width: 6),
                                  Text(
                                    gc.localTime.split(' ').first,
                                    style: text.labelSmall?.copyWith(
                                      color: active
                                          ? colors.onPrimary.withValues(alpha: 0.8)
                                          : colors.onSurfaceVariant,
                                      fontSize: 10,
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          ),
                        ),
                      );
                    }).toList()
                  : _kObservatories.map((_ObservatoryPreset p) {
                      final bool active =
                          ((selection.lat ?? 50.8503) - p.lat).abs() < 0.05 &&
                          ((selection.lon ?? 4.3517) - p.lon).abs() < 0.05;
                      return Padding(
                        padding: const EdgeInsets.only(right: BgSpace.xs),
                        child: InkWell(
                          borderRadius: BorderRadius.circular(20),
                          onTap: () => onSelectCity(p.lat, p.lon, p.label),
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 7,
                            ),
                            decoration: BoxDecoration(
                              color: active
                                  ? colors.primary
                                  : colors.surfaceContainerHighest.withValues(alpha: 0.6),
                              borderRadius: BorderRadius.circular(20),
                            ),
                            child: Text(
                              p.label,
                              style: text.labelMedium?.copyWith(
                                color: active ? colors.onPrimary : colors.onSurface,
                              ),
                            ),
                          ),
                        ),
                      );
                    }).toList(),
            ),
          ),
        ],
      ),
    );
  }
}

class _ForgeActionDeck extends StatelessWidget {
  const _ForgeActionDeck({
    required this.forging,
    required this.signedIn,
    required this.selection,
    required this.selectedThemeId,
    required this.selectedGenreId,
    required this.onForge,
  });

  final bool forging;
  final bool signedIn;
  final ForgeSelection selection;
  final String? selectedThemeId;
  final String? selectedGenreId;
  final VoidCallback? onForge;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: <Color>[
            colors.surfaceContainerHigh,
            colors.surfaceContainerHighest.withValues(alpha: 0.55),
          ],
        ),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: colors.primary.withValues(alpha: 0.32),
        ),
        boxShadow: <BoxShadow>[
          BoxShadow(
            color: colors.primary.withValues(alpha: 0.12),
            blurRadius: 24,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Wrap(
            spacing: BgSpace.sm,
            runSpacing: BgSpace.xs,
            children: <Widget>[
              _DeckChip(
                icon: Icons.public,
                label: 'OBSERVATORY',
                value: selection.label,
              ),
              _DeckChip(
                icon: Icons.palette_outlined,
                label: 'THEME',
                value: selectedThemeId != null
                    ? selectedThemeId!.toUpperCase()
                    : 'AUTO-CALIBRATED',
              ),
              _DeckChip(
                icon: Icons.graphic_eq,
                label: 'CORRIDOR',
                value: selectedGenreId != null
                    ? selectedGenreId!.replaceAll('_', ' ').toUpperCase()
                    : 'ALL SPECTRUMS',
              ),
              _DeckChip(
                icon: Icons.headphones_outlined,
                label: 'TASTE ENGINE',
                value: signedIn ? 'LAST.FM + SPOTIFY' : 'DEMO TASTE PROFILE',
              ),
            ],
          ),
          const SizedBox(height: BgSpace.md),
          SizedBox(
            height: 52,
            child: FilledButton.icon(
              onPressed: onForge,
              style: FilledButton.styleFrom(
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              icon: forging
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.2,
                        color: Colors.white,
                      ),
                    )
                  // UX_IA_SPEC §1.3: the FORGE CTA is an arrow ("produce
                  // this"), not a lightning bolt. `play_arrow` was taken by the
                  // mini-player, so `east`.
                  : const Icon(Icons.east, size: BgIcon.chrome),
              label: Text(
                forging
                    ? 'SYNTHESIZING ATMOSPHERIC SOUNDTRACK…'
                    : signedIn
                        ? 'FORGE SOUNDTRACK FOR THIS SKY'
                        : 'FORGE DEMO SOUNDTRACK FOR THIS SKY',
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.6,
                ),
              ),
            ),
          ),
          if (!signedIn) ...<Widget>[
            const SizedBox(height: BgSpace.sm),
            Text(
              'Running in zero-credential mode — sign in via Settings to bind your Last.fm taste profile and save playlists directly to Spotify.',
              style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
              textAlign: TextAlign.center,
            ),
          ],
        ],
      ),
    );
  }
}

class _DeckChip extends StatelessWidget {
  const _DeckChip({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: 0.75),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(icon, size: 13, color: colors.primary),
          const SizedBox(width: 6),
          Text(
            '$label: ',
            style: text.labelSmall?.copyWith(
              color: colors.onSurfaceVariant,
              fontSize: 10,
            ),
          ),
          Text(
            value,
            style: text.labelSmall?.copyWith(
              color: colors.onSurface,
              fontWeight: FontWeight.w700,
              fontSize: 11,
            ),
          ),
        ],
      ),
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
