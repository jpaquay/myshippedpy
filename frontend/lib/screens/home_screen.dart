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
import 'widgets/gemini_live_advisor.dart';
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

    final ApiResult<ForgeResult> result =
        await api.forge(selection.toRequest());

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
          GeminiLiveAdvisorBanner(
            onSurfaceRefreshNeeded: _loadSurfaces,
          ),
          const SizedBox(height: BgSpace.lg),
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
          Section(
            eyebrow: 'CURRENT BAROMETRIC READING',
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
          const SizedBox(height: BgSpace.xxl),
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
                              'Local: ${activeGeocache!.localTime} • ${activeGeocache!.dayPeriod.toUpperCase()}',
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
                  : const Icon(Icons.bolt, size: 20),
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
