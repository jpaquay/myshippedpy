/// The Sonic Almanac: Forged Daylists, 15-Year Scrobble Catalog & Cohort Matcher.
///
/// Re-engineered for lean visual hierarchy, scannable cards, and effortless flow
/// matching the Forge and Data Viz screens.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../app_theme.dart';
import '../providers.dart';
import 'shell.dart';
import 'widgets/netdev_footer.dart';

enum _AlmanacMode {
  forged('Forged Daylists', Icons.history_edu_rounded),
  catalog('Scrobble Catalog', Icons.library_music_rounded),
  cohort('Cohort Matcher', Icons.donut_large_rounded);

  const _AlmanacMode(this.label, this.icon);
  final String label;
  final IconData icon;
}

class AlmanacScreen extends ConsumerStatefulWidget {
  const AlmanacScreen({super.key});

  @override
  ConsumerState<AlmanacScreen> createState() => _AlmanacScreenState();
}

class _AlmanacScreenState extends ConsumerState<AlmanacScreen> {
  _AlmanacMode _mode = _AlmanacMode.forged;

  bool _loadingHistory = true;
  bool _loadingScrobbles = true;
  bool _loadingCohort = false;
  bool _syncing = false;
  bool _forgingFromScrobbles = false;
  bool _showCustomCohortInput = false;
  String? _error;

  List<AlmanacEntry> _history = const <AlmanacEntry>[];
  Retrospective _retro = Retrospective.empty;
  ScrobbleSearchResponse _scrobbleData = ScrobbleSearchResponse.empty;
  PlaylistCohortResponse? _cohortResult;

  String _searchQuery = '';
  String? _selectedTag;
  String? _selectedTheme;
  String _activeCohortPreset = 'preset:chanson';

  final TextEditingController _searchController = TextEditingController();
  final TextEditingController _cohortInputController = TextEditingController(
    text: 'preset:chanson',
  );

  static const List<Map<String, String>> _weatherFilters = <Map<String, String>>[
    <String, String>{'id': '', 'label': 'All Moods'},
    <String, String>{'id': 'petrichor', 'label': '🌧️ Petrichor'},
    <String, String>{'id': 'golden_hour', 'label': '🌅 Golden Hour'},
    <String, String>{'id': 'nordic_fog', 'label': '🌫️ Nordic Fog'},
    <String, String>{'id': 'storm_front', 'label': '⛈️ Storm Front'},
    <String, String>{'id': 'blue_hour', 'label': '🌌 Blue Hour'},
    <String, String>{'id': 'heatwave_cruise', 'label': '☀️ Heatwave'},
  ];

  static const List<String> _genreFilters = <String>[
    'chanson',
    'trip-hop',
    'indie',
    'ambient',
    'electronic',
    'rock',
  ];

  static const List<Map<String, String>> _cohortPresets = <Map<String, String>>[
    <String, String>{
      'id': 'preset:chanson',
      'label': '🇫🇷 Chanson Classics',
    },
    <String, String>{
      'id': 'preset:triphop',
      'label': '🌧️ Petrichor Trip-Hop',
    },
    <String, String>{
      'id': 'preset:golden',
      'label': '🌅 Golden Hour Acoustic',
    },
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadHistory();
      _loadScrobbles();
      _runCohortCheck('preset:chanson');
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    _cohortInputController.dispose();
    super.dispose();
  }

  Future<void> _loadHistory() async {
    setState(() {
      _loadingHistory = true;
      _error = null;
    });

    final BarogrooveApi api = ref.read(apiProvider);
    final List<Object> results = await Future.wait(<Future<Object>>[
      api.almanacHistory(),
      api.retrospective(),
    ]);

    if (!mounted) return;

    final ApiResult<List<AlmanacEntry>> historyRes =
        results[0] as ApiResult<List<AlmanacEntry>>;
    final ApiResult<Retrospective> retroRes =
        results[1] as ApiResult<Retrospective>;

    setState(() {
      _loadingHistory = false;
      _history = historyRes.valueOrNull ?? const <AlmanacEntry>[];
      _retro = retroRes.valueOrNull ?? Retrospective.empty;
      if (!historyRes.isOk) {
        _error = historyRes.failureOrNull?.message;
      }
    });
  }

  Future<void> _loadScrobbles() async {
    setState(() => _loadingScrobbles = true);
    final BarogrooveApi api = ref.read(apiProvider);
    final ApiResult<ScrobbleSearchResponse> res = await api.scrobbles(
      query: _searchQuery,
      tag: _selectedTag,
      theme: _selectedTheme,
    );
    if (!mounted) return;
    setState(() {
      _loadingScrobbles = false;
      if (res.isOk && res.valueOrNull != null) {
        _scrobbleData = res.valueOrNull!;
      }
    });
  }

  Future<void> _runCohortCheck(String inputText, {String? customTitle}) async {
    setState(() => _loadingCohort = true);
    final BarogrooveApi api = ref.read(apiProvider);
    final ApiResult<PlaylistCohortResponse> res = await api.playlistCohortCheck(
      inputText: inputText,
      playlistTitle: customTitle,
    );
    if (!mounted) return;
    setState(() {
      _loadingCohort = false;
      if (res.isOk && res.valueOrNull != null) {
        _cohortResult = res.valueOrNull!;
      }
    });
  }

  Future<void> _crossCheckForgedSet(AlmanacEntry entry) async {
    final String tracklistText = entry.tracksPreview.join('\n');
    final String payload = tracklistText.isNotEmpty
        ? tracklistText
        : 'preset:chanson';
    setState(() {
      _mode = _AlmanacMode.cohort;
      _activeCohortPreset = 'forged:${entry.id}';
      _cohortInputController.text = payload;
    });
    await _runCohortCheck(
      payload,
      customTitle: 'Forged Set: ${entry.title}',
    );
  }

  Future<void> _syncLastfmToFirestore() async {
    setState(() => _syncing = true);
    final BarogrooveApi api = ref.read(apiProvider);
    final ApiResult<ScrobbleSearchResponse> res =
        await api.syncScrobbles(lastfmUser: 'jpaquay');
    if (!mounted) return;
    setState(() {
      _syncing = false;
      if (res.isOk && res.valueOrNull != null) {
        _scrobbleData = res.valueOrNull!;
      }
    });
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Synced Last.fm scrobbles to BigQuery OLAP & Firestore.'),
          duration: Duration(seconds: 3),
        ),
      );
    }
  }

  Future<void> _reloadForgedPlaylist(AlmanacEntry entry) async {
    final BarogrooveApi api = ref.read(apiProvider);
    final ApiResult<Playlist> res = await api.getForgedPlaylist(entry.id);
    if (!mounted) return;
    res.when(
      ok: (Playlist pl) {
        ref.read(lastForgeProvider.notifier).state = ForgeResult(
          playlist: pl,
          degraded: pl.rationale.degraded,
        );
        AppShell.of(context)?.go(BgDestination.playlist);
      },
      failed: (ApiFailure<Playlist> f) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not load playlist: ${f.message}')),
        );
      },
    );
  }

  Future<void> _forgeWithSelectedScrobbles() async {
    final Set<String> selected = ref.read(selectedSeedScrobblesProvider);
    if (selected.isEmpty) return;

    setState(() => _forgingFromScrobbles = true);
    final BarogrooveApi api = ref.read(apiProvider);
    final ForgeSelection selection = ref.read(forgeSelectionProvider).copyWith(
          seedScrobbles: selected.toList(),
        );
    final ApiResult<ForgeResult> res = await api.forge(selection.toRequest());
    if (!mounted) return;
    setState(() => _forgingFromScrobbles = false);

    res.when(
      ok: (ForgeResult r) {
        ref.read(lastForgeProvider.notifier).state = r;
        AppShell.of(context)?.go(BgDestination.playlist);
      },
      failed: (ApiFailure<ForgeResult> f) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Forge error: ${f.message}')),
        );
      },
    );
  }

  void _toggleTrackSeed(String trackKey) {
    HapticFeedback.selectionClick();
    final Set<String> current =
        Set<String>.from(ref.read(selectedSeedScrobblesProvider));
    if (current.contains(trackKey)) {
      current.remove(trackKey);
    } else {
      current.add(trackKey);
    }
    ref.read(selectedSeedScrobblesProvider.notifier).state = current;
  }

  void _seedFreshDiscoveries() {
    final PlaylistCohortResponse? cohort = _cohortResult;
    if (cohort == null) return;
    final List<String> discoveries = cohort.trackMatches
        .where((PlaylistTrackMatch m) => m.status == 'NEW_DISCOVERY')
        .map((PlaylistTrackMatch m) => m.trackKey)
        .take(5)
        .toList();
    if (discoveries.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('All tracks in this set are already in your cohort!')),
      );
      return;
    }
    final Set<String> current =
        Set<String>.from(ref.read(selectedSeedScrobblesProvider))
          ..addAll(discoveries);
    ref.read(selectedSeedScrobblesProvider.notifier).state = current;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Added ${discoveries.length} fresh discovery track(s) as Forge seeds!'),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final Set<String> selectedSeeds = ref.watch(selectedSeedScrobblesProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      floatingActionButtonLocation: FloatingActionButtonLocation.centerFloat,
      floatingActionButton: selectedSeeds.isNotEmpty
          ? _FloatingSeedBar(
              count: selectedSeeds.length,
              forging: _forgingFromScrobbles,
              onForge: _forgeWithSelectedScrobbles,
              onClear: () {
                ref.read(selectedSeedScrobblesProvider.notifier).state =
                    <String>{};
              },
            )
          : null,
      body: CustomScrollView(
        slivers: <Widget>[
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(
              BgSpace.lg,
              BgSpace.md,
              BgSpace.lg,
              BgSpace.xxl,
            ),
            sliver: SliverList(
              delegate: SliverChildListDelegate(<Widget>[
                // 1. Clean Top Header + Data Viz Shortcut
                _buildHeader(context, colors, text),
                const SizedBox(height: BgSpace.md),

                // 2. Segmented 3-Mode Selector Bar + Action Buttons
                _buildModeBar(context, colors, text),
                const SizedBox(height: BgSpace.md),

                // 3. Adaptive KPI Summary Strip
                _buildKpiStrip(context, colors, text),
                const SizedBox(height: BgSpace.lg),

                // 4. Active Mode Content
                if (_mode == _AlmanacMode.forged)
                  _buildForgedSetsView(context, colors, text)
                else if (_mode == _AlmanacMode.catalog)
                  _buildCatalogView(context, colors, text, selectedSeeds)
                else
                  _buildCohortMatcherView(context, colors, text, selectedSeeds),

                const SizedBox(height: BgSpace.xl),
                const NetdevFooter(),
              ]),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader(
    BuildContext context,
    ColorScheme colors,
    TextTheme text,
  ) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                'Sonic Almanac',
                style: text.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                  letterSpacing: -0.5,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                'Your forged weather-inspired sets, 15-year listening catalog, and cohort matcher.',
                style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
              ),
            ],
          ),
        ),
        const SizedBox(width: BgSpace.sm),
        // Direct shortcut pill to the main-menu Data Viz & Gemini Live QnA Studio
        ActionChip(
          avatar: Icon(Icons.insights_rounded, size: 16, color: colors.primary),
          label: Text(
            'Data Viz & Live QnA →',
            style: text.labelMedium?.copyWith(
              color: colors.primary,
              fontWeight: FontWeight.w700,
            ),
          ),
          backgroundColor: colors.primary.withValues(alpha: 0.1),
          side: BorderSide(color: colors.primary.withValues(alpha: 0.35)),
          onPressed: () => AppShell.of(context)?.go(BgDestination.dataViz),
        ),
      ],
    );
  }

  Widget _buildModeBar(
    BuildContext context,
    ColorScheme colors,
    TextTheme text,
  ) {
    return Wrap(
      alignment: WrapAlignment.spaceBetween,
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: BgSpace.sm,
      runSpacing: BgSpace.sm,
      children: <Widget>[
        // Segmented Pill Bar
        Container(
          padding: const EdgeInsets.all(4),
          decoration: BoxDecoration(
            color: colors.surfaceContainerHighest.withValues(alpha: 0.5),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.6)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: _AlmanacMode.values.map((_AlmanacMode m) {
              final bool active = _mode == m;
              final String labelText = m == _AlmanacMode.forged && _history.isNotEmpty
                  ? '${m.label} (${_history.length})'
                  : m.label;
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2),
                child: InkWell(
                  borderRadius: BorderRadius.circular(10),
                  onTap: () {
                    HapticFeedback.selectionClick();
                    setState(() => _mode = m);
                  },
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 180),
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                    decoration: BoxDecoration(
                      color: active ? colors.primary : Colors.transparent,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        Icon(
                          m.icon,
                          size: 16,
                          color: active ? colors.onPrimary : colors.onSurfaceVariant,
                        ),
                        const SizedBox(width: 6),
                        Text(
                          labelText,
                          style: text.labelMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: active ? colors.onPrimary : colors.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            }).toList(),
          ),
        ),

        // Right side action buttons
        Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            OutlinedButton.icon(
              onPressed: _syncing ? null : _syncLastfmToFirestore,
              icon: _syncing
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.sync_rounded, size: 16),
              label: Text(_syncing ? 'Syncing…' : 'Sync Last.fm'),
              style: OutlinedButton.styleFrom(
                visualDensity: VisualDensity.compact,
              ),
            ),
            const SizedBox(width: 6),
            IconButton(
              tooltip: 'Refresh Almanac',
              onPressed: () {
                _loadHistory();
                _loadScrobbles();
                _runCohortCheck(_cohortInputController.text);
              },
              icon: const Icon(Icons.refresh_rounded, size: 20),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildKpiStrip(
    BuildContext context,
    ColorScheme colors,
    TextTheme text,
  ) {
    final ScrobbleAnalytics stats = _scrobbleData.analytics;
    final int totalScrobbles = stats.totalScrobbles > 0 ? stats.totalScrobbles : 160717;
    final int uniqueTracks = stats.uniqueTracks > 0 ? stats.uniqueTracks : 2649;

    if (_mode == _AlmanacMode.forged) {
      return Wrap(
        spacing: BgSpace.sm,
        runSpacing: BgSpace.sm,
        children: <Widget>[
          _KpiPill(
            icon: Icons.queue_music_rounded,
            label: 'FORGED SETS',
            value: '${_history.length} Daylists',
            accent: colors.primary,
          ),
          _KpiPill(
            icon: Icons.wb_cloudy_rounded,
            label: 'FAVORITE SKY THEME',
            value: _history.isNotEmpty
                ? _formatThemeName(_history.first.themeId)
                : 'Petrichor',
            accent: const Color(0xFF38BDF8),
          ),
          if (_retro.items.isNotEmpty)
            _KpiPill(
              icon: Icons.auto_awesome_rounded,
              label: _retro.items.first.label.toUpperCase(),
              value: _retro.items.first.detail,
              accent: const Color(0xFFF59E0B),
            ),
          _KpiPill(
            icon: Icons.storage_rounded,
            label: 'PERSISTENCE',
            value: 'Firestore + BQ OLAP',
            accent: const Color(0xFF10B981),
          ),
        ],
      );
    }

    if (_mode == _AlmanacMode.catalog) {
      return Wrap(
        spacing: BgSpace.sm,
        runSpacing: BgSpace.sm,
        children: <Widget>[
          _KpiPill(
            icon: Icons.headphones_rounded,
            label: '15-YEAR COHORT',
            value: '$totalScrobbles Scrobbles',
            accent: colors.primary,
          ),
          _KpiPill(
            icon: Icons.album_rounded,
            label: 'INDEXED CATALOG',
            value: '$uniqueTracks Unique Tracks',
            accent: const Color(0xFF38BDF8),
          ),
          _KpiPill(
            icon: Icons.speed_rounded,
            label: 'AVG SONIC TEMPO',
            value: '${stats.avgBpm.toStringAsFixed(0)} BPM',
            accent: const Color(0xFFF59E0B),
          ),
          _KpiPill(
            icon: Icons.bolt_rounded,
            label: 'BIGQUERY CACHE',
            value: '${_scrobbleData.cacheStatus} (${_scrobbleData.executionMs.toStringAsFixed(1)} ms)',
            accent: const Color(0xFF10B981),
          ),
        ],
      );
    }

    // Mode: Cohort Matcher
    final PlaylistCohortResponse? cohort = _cohortResult;
    return Wrap(
      spacing: BgSpace.sm,
      runSpacing: BgSpace.sm,
      children: <Widget>[
        _KpiPill(
          icon: Icons.donut_large_rounded,
          label: 'COHORT OVERLAP',
          value: cohort != null
              ? '${cohort.cohortOverlapPct.toStringAsFixed(1)}% Familiar'
              : '—',
          accent: const Color(0xFF10B981),
        ),
        _KpiPill(
          icon: Icons.favorite_rounded,
          label: 'CORE FAVORITES',
          value: cohort != null ? '${cohort.exactMatchesCount} Tracks' : '—',
          accent: colors.primary,
        ),
        _KpiPill(
          icon: Icons.explore_rounded,
          label: 'FRESH DISCOVERIES',
          value: cohort != null ? '${cohort.newDiscoveryCount} New Tracks' : '—',
          accent: const Color(0xFFF59E0B),
        ),
        _KpiPill(
          icon: Icons.wb_twilight_rounded,
          label: 'DOMINANT MOOD',
          value: cohort != null
              ? _formatThemeName(cohort.dominantWeatherTheme)
              : 'Petrichor',
          accent: const Color(0xFF38BDF8),
        ),
      ],
    );
  }

  // ===========================================================================
  // PILLAR 1: FORGED DAYLISTS VIEW
  // ===========================================================================

  Widget _buildForgedSetsView(
    BuildContext context,
    ColorScheme colors,
    TextTheme text,
  ) {
    if (_loadingHistory) {
      return const Padding(
        padding: EdgeInsets.all(BgSpace.xxl),
        child: Center(child: CircularProgressIndicator()),
      );
    }

    if (_error != null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(BgSpace.lg),
          child: Text('Could not load forged sets: $_error'),
        ),
      );
    }

    if (_history.isEmpty) {
      return Card(
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: colors.outlineVariant),
        ),
        child: Padding(
          padding: const EdgeInsets.all(BgSpace.xl),
          child: Column(
            children: <Widget>[
              Icon(Icons.explore_outlined, size: 44, color: colors.primary),
              const SizedBox(height: BgSpace.md),
              Text(
                'No forged sets in your Almanac yet',
                style: text.titleMedium?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 6),
              Text(
                'Head to the Forge screen or speak to the Gemini Live Advisor to craft your first weather-inspired Daylist.',
                textAlign: TextAlign.center,
                style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
              ),
              const SizedBox(height: BgSpace.md),
              FilledButton.icon(
                onPressed: () => AppShell.of(context)?.go(BgDestination.forge),
                icon: const Icon(Icons.bolt_rounded, size: 18),
                label: const Text('Go to Forge'),
              ),
            ],
          ),
        ),
      );
    }

    return LayoutBuilder(
      builder: (BuildContext ctx, BoxConstraints constraints) {
        final bool twoColumns = constraints.maxWidth >= 780;
        if (!twoColumns) {
          return Column(
            children: _history
                .map((AlmanacEntry e) => Padding(
                      padding: const EdgeInsets.only(bottom: BgSpace.md),
                      child: _ForgedSetCard(
                        entry: e,
                        onPlay: () => _reloadForgedPlaylist(e),
                        onCohortCheck: () => _crossCheckForgedSet(e),
                      ),
                    ))
                .toList(),
          );
        }

        final List<Widget> rows = <Widget>[];
        for (int i = 0; i < _history.length; i += 2) {
          final AlmanacEntry left = _history[i];
          final AlmanacEntry? right =
              (i + 1 < _history.length) ? _history[i + 1] : null;
          rows.add(
            Padding(
              padding: const EdgeInsets.only(bottom: BgSpace.md),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Expanded(
                    child: _ForgedSetCard(
                      entry: left,
                      onPlay: () => _reloadForgedPlaylist(left),
                      onCohortCheck: () => _crossCheckForgedSet(left),
                    ),
                  ),
                  const SizedBox(width: BgSpace.md),
                  Expanded(
                    child: right != null
                        ? _ForgedSetCard(
                            entry: right,
                            onPlay: () => _reloadForgedPlaylist(right),
                            onCohortCheck: () => _crossCheckForgedSet(right),
                          )
                        : const SizedBox.shrink(),
                  ),
                ],
              ),
            ),
          );
        }
        return Column(children: rows);
      },
    );
  }

  // ===========================================================================
  // PILLAR 2: SCROBBLE CATALOG & SEED PICKER VIEW
  // ===========================================================================

  Widget _buildCatalogView(
    BuildContext context,
    ColorScheme colors,
    TextTheme text,
    Set<String> selectedSeeds,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        // Search & Filter Card
        Container(
          padding: const EdgeInsets.all(BgSpace.md),
          decoration: BoxDecoration(
            color: colors.surfaceContainerLow,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.7)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              // Search Bar
              TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  hintText: 'Search 160,717 scrobbles by artist, track, or album…',
                  prefixIcon: const Icon(Icons.search_rounded, size: 20),
                  suffixIcon: _searchQuery.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.clear_rounded, size: 18),
                          onPressed: () {
                            _searchController.clear();
                            setState(() => _searchQuery = '');
                            _loadScrobbles();
                          },
                        )
                      : null,
                  isDense: true,
                  filled: true,
                  fillColor: colors.surface,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(color: colors.outlineVariant),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide(color: colors.outlineVariant),
                  ),
                ),
                onSubmitted: (String val) {
                  setState(() => _searchQuery = val.trim());
                  _loadScrobbles();
                },
              ),
              const SizedBox(height: BgSpace.sm),

              // Weather Mood Filter Pills
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: _weatherFilters.map((Map<String, String> f) {
                    final String id = f['id']!;
                    final bool active = (_selectedTheme ?? '') == id;
                    return Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ChoiceChip(
                        label: Text(f['label']!),
                        selected: active,
                        visualDensity: VisualDensity.compact,
                        onSelected: (_) {
                          setState(() {
                            _selectedTheme = id.isEmpty ? null : id;
                          });
                          _loadScrobbles();
                        },
                      ),
                    );
                  }).toList(),
                ),
              ),
              const SizedBox(height: 6),

              // Genre Tag Filter Pills
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: <Widget>[
                    Text(
                      'GENRE:',
                      style: text.labelSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(width: 8),
                    ..._genreFilters.map((String tag) {
                      final bool active = _selectedTag == tag;
                      return Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: FilterChip(
                          label: Text('#$tag'),
                          selected: active,
                          visualDensity: VisualDensity.compact,
                          onSelected: (bool v) {
                            setState(() {
                              _selectedTag = v ? tag : null;
                            });
                            _loadScrobbles();
                          },
                        ),
                      );
                    }),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: BgSpace.md),

        // Instruction banner for seeding
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: <Widget>[
            Text(
              'Showing ${_scrobbleData.scrobbles.length} catalog tracks • Click any track to seed into your next Forge',
              style: text.labelMedium?.copyWith(color: colors.onSurfaceVariant),
            ),
            if (selectedSeeds.isNotEmpty)
              TextButton.icon(
                onPressed: () {
                  ref.read(selectedSeedScrobblesProvider.notifier).state =
                      <String>{};
                },
                icon: const Icon(Icons.clear_all_rounded, size: 16),
                label: Text('Clear ${selectedSeeds.length} selected'),
              ),
          ],
        ),
        const SizedBox(height: BgSpace.xs),

        if (_loadingScrobbles)
          const Padding(
            padding: EdgeInsets.all(BgSpace.xxl),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (_scrobbleData.scrobbles.isEmpty)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(BgSpace.xl),
              child: Center(
                child: Text(
                  'No scrobble tracks matched your filter.',
                  style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
                ),
              ),
            ),
          )
        else
          Column(
            children: _scrobbleData.scrobbles.take(40).map((ScrobbleEntry item) {
              final bool isSeeded = selectedSeeds.contains(item.trackKey);
              return Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: _ScrobbleTrackRow(
                  entry: item,
                  isSeeded: isSeeded,
                  onToggleSeed: () => _toggleTrackSeed(item.trackKey),
                ),
              );
            }).toList(),
          ),
      ],
    );
  }

  // ===========================================================================
  // PILLAR 3: COHORT MATCHER VIEW
  // ===========================================================================

  Widget _buildCohortMatcherView(
    BuildContext context,
    ColorScheme colors,
    TextTheme text,
    Set<String> selectedSeeds,
  ) {
    final PlaylistCohortResponse? cohort = _cohortResult;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        // Preset Selector & Custom Tracklist Input Bar
        Container(
          padding: const EdgeInsets.all(BgSpace.md),
          decoration: BoxDecoration(
            color: colors.surfaceContainerLow,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.7)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: <Widget>[
                  Text(
                    'COMPARE A PLAYLIST OR SET AGAINST YOUR 15-YEAR COHORT',
                    style: text.labelSmall?.copyWith(
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.8,
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                  TextButton.icon(
                    onPressed: () {
                      setState(() => _showCustomCohortInput = !_showCustomCohortInput);
                    },
                    icon: Icon(
                      _showCustomCohortInput
                          ? Icons.expand_less_rounded
                          : Icons.edit_note_rounded,
                      size: 18,
                    ),
                    label: Text(
                      _showCustomCohortInput
                          ? 'Hide Custom Input'
                          : 'Paste Tracklist / URL',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: <Widget>[
                  ..._cohortPresets.map((Map<String, String> p) {
                    final String id = p['id']!;
                    final bool active = _activeCohortPreset == id;
                    return ChoiceChip(
                      label: Text(p['label']!),
                      selected: active,
                      onSelected: (_) {
                        setState(() {
                          _activeCohortPreset = id;
                          _cohortInputController.text = id;
                        });
                        _runCohortCheck(id);
                      },
                    );
                  }),
                  if (_history.isNotEmpty)
                    ChoiceChip(
                      label: Text('⚡ Latest Forged: ${_history.first.title}'),
                      selected: _activeCohortPreset == 'forged:${_history.first.id}',
                      onSelected: (_) => _crossCheckForgedSet(_history.first),
                    ),
                ],
              ),
              if (_showCustomCohortInput) ...<Widget>[
                const SizedBox(height: BgSpace.md),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Expanded(
                      child: TextField(
                        controller: _cohortInputController,
                        maxLines: 3,
                        decoration: InputDecoration(
                          hintText:
                              'Paste "Artist - Track" lines or a Spotify/Last.fm playlist identifier…',
                          filled: true,
                          fillColor: colors.surface,
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: BgSpace.sm),
                    FilledButton.icon(
                      onPressed: _loadingCohort
                          ? null
                          : () => _runCohortCheck(_cohortInputController.text),
                      icon: const Icon(Icons.analytics_rounded, size: 18),
                      label: const Text('Analyze'),
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: BgSpace.md),

        if (_loadingCohort)
          const Padding(
            padding: EdgeInsets.all(BgSpace.xxl),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (cohort == null)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(BgSpace.xl),
              child: Center(
                child: Text(
                  'Select a preset above or paste a tracklist to analyze cohort familiarity.',
                  style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
                ),
              ),
            ),
          )
        else
          LayoutBuilder(
            builder: (BuildContext ctx, BoxConstraints constraints) {
              final bool wide = constraints.maxWidth >= 820;
              final Widget donutCard = _CohortDonutCard(
                cohort: cohort,
                onSeedDiscoveries: _seedFreshDiscoveries,
              );
              final Widget tracksCard = _CohortTrackListCard(
                cohort: cohort,
                selectedSeeds: selectedSeeds,
                onToggleSeed: _toggleTrackSeed,
              );

              if (wide) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    SizedBox(width: 360, child: donutCard),
                    const SizedBox(width: BgSpace.md),
                    Expanded(child: tracksCard),
                  ],
                );
              }
              return Column(
                children: <Widget>[
                  donutCard,
                  const SizedBox(height: BgSpace.md),
                  tracksCard,
                ],
              );
            },
          ),
      ],
    );
  }
}

// =============================================================================
// SUB-WIDGETS & CLEAN CARDS
// =============================================================================

class _KpiPill extends StatelessWidget {
  const _KpiPill({
    required this.icon,
    required this.label,
    required this.value,
    required this.accent,
  });

  final IconData icon;
  final String label;
  final String value;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.6)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Container(
            padding: const EdgeInsets.all(7),
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, size: 17, color: accent),
          ),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(
                label,
                style: text.labelSmall?.copyWith(
                  fontSize: 9,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 0.7,
                  color: colors.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                value,
                style: text.titleSmall?.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ForgedSetCard extends StatelessWidget {
  const _ForgedSetCard({
    required this.entry,
    required this.onPlay,
    required this.onCohortCheck,
  });

  final AlmanacEntry entry;
  final VoidCallback onPlay;
  final VoidCallback onCohortCheck;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final Color themeColor = _themeAccentColor(entry.themeId);

    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.7)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // Header badges
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: <Widget>[
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: themeColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: themeColor.withValues(alpha: 0.5)),
                ),
                child: Text(
                  _formatThemeName(entry.themeId).toUpperCase(),
                  style: text.labelSmall?.copyWith(
                    color: themeColor,
                    fontWeight: FontWeight.w800,
                    fontSize: 10,
                    letterSpacing: 0.7,
                  ),
                ),
              ),
              Text(
                _formatShortTimestamp(entry.createdAt),
                style: text.labelSmall?.copyWith(color: colors.onSurfaceVariant),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.sm),

          // Title & Headline
          Text(
            entry.title,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: text.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          if (entry.headline != null && entry.headline!.isNotEmpty) ...<Widget>[
            const SizedBox(height: 3),
            Text(
              entry.headline!,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
            ),
          ],
          const SizedBox(height: BgSpace.sm),

          // Track preview chips
          if (entry.tracksPreview.isNotEmpty) ...<Widget>[
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: <Widget>[
                ...entry.tracksPreview.take(3).map((String t) {
                  return Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: colors.surfaceContainerHighest.withValues(alpha: 0.6),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      t,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: text.labelSmall?.copyWith(fontSize: 11),
                    ),
                  );
                }),
                if (entry.trackCount > 3)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: colors.primary.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      '+${entry.trackCount - 3} more',
                      style: text.labelSmall?.copyWith(
                        color: colors.primary,
                        fontWeight: FontWeight.w700,
                        fontSize: 11,
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: BgSpace.md),
          ],

          // Action buttons
          Row(
            children: <Widget>[
              Expanded(
                child: FilledButton.tonalIcon(
                  onPressed: onPlay,
                  icon: const Icon(Icons.play_arrow_rounded, size: 18),
                  label: const Text('Play in Set'),
                  style: FilledButton.styleFrom(
                    visualDensity: VisualDensity.compact,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: onCohortCheck,
                icon: const Icon(Icons.donut_large_rounded, size: 16),
                label: const Text('Cohort Match'),
                style: OutlinedButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ScrobbleTrackRow extends StatelessWidget {
  const _ScrobbleTrackRow({
    required this.entry,
    required this.isSeeded,
    required this.onToggleSeed,
  });

  final ScrobbleEntry entry;
  final bool isSeeded;
  final VoidCallback onToggleSeed;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final Color moodColor = _themeAccentColor(entry.weatherTheme);

    return Material(
      color: isSeeded
          ? colors.primaryContainer.withValues(alpha: 0.35)
          : colors.surfaceContainerLow,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(
          color: isSeeded
              ? colors.primary
              : colors.outlineVariant.withValues(alpha: 0.6),
          width: isSeeded ? 1.4 : 1.0,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onToggleSeed,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Row(
            children: <Widget>[
              // Checkbox / Seed icon
              Icon(
                isSeeded
                    ? Icons.check_circle_rounded
                    : Icons.add_circle_outline_rounded,
                size: 20,
                color: isSeeded ? colors.primary : colors.onSurfaceVariant,
              ),
              const SizedBox(width: 12),

              // Track & Artist
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      entry.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: text.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      entry.album != null && entry.album!.isNotEmpty
                          ? '${entry.artist} • ${entry.album}'
                          : entry.artist,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: text.bodySmall?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),

              // Right Badges
              Wrap(
                spacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: <Widget>[
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: moodColor.withValues(alpha: 0.14),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      '${entry.bpmEstimate} BPM • ${_formatThemeName(entry.weatherTheme)}',
                      style: text.labelSmall?.copyWith(
                        color: moodColor,
                        fontWeight: FontWeight.w700,
                        fontSize: 10,
                      ),
                    ),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: const Color(0xFF10B981).withValues(alpha: 0.14),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      '${entry.playCount} plays',
                      style: text.labelSmall?.copyWith(
                        color: const Color(0xFF10B981),
                        fontWeight: FontWeight.w800,
                        fontSize: 10,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CohortDonutCard extends StatelessWidget {
  const _CohortDonutCard({
    required this.cohort,
    required this.onSeedDiscoveries,
  });

  final PlaylistCohortResponse cohort;
  final VoidCallback onSeedDiscoveries;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.7)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            'COHORT FAMILIARITY BREAKDOWN',
            style: text.labelSmall?.copyWith(
              fontWeight: FontWeight.w800,
              letterSpacing: 0.8,
              color: colors.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            cohort.playlistTitle,
            style: text.titleMedium?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: BgSpace.lg),

          // Donut Chart
          Center(
            child: SizedBox(
              width: 180,
              height: 180,
              child: CustomPaint(
                painter: _CohortDonutPainter(
                  slices: cohort.cohortPieSlices,
                  centerLabel: '${cohort.cohortOverlapPct.toStringAsFixed(0)}%',
                  centerSublabel: 'Familiar',
                  textColor: colors.onSurface,
                ),
              ),
            ),
          ),
          const SizedBox(height: BgSpace.lg),

          // Legend Rows
          ...cohort.cohortPieSlices.map((CohortPieSlice slice) {
            final Color c = _parseHexColor(slice.colorHex);
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                children: <Widget>[
                  Container(
                    width: 12,
                    height: 12,
                    decoration: BoxDecoration(
                      color: c,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      slice.label,
                      style: text.bodySmall?.copyWith(fontWeight: FontWeight.w600),
                    ),
                  ),
                  Text(
                    '${slice.count} tracks (${slice.percentage.toStringAsFixed(0)}%)',
                    style: text.labelSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            );
          }),
          const SizedBox(height: BgSpace.md),

          SizedBox(
            width: double.infinity,
            child: FilledButton.tonalIcon(
              onPressed: onSeedDiscoveries,
              icon: const Icon(Icons.auto_awesome_rounded, size: 16),
              label: const Text('Seed Fresh Discoveries into Forge'),
            ),
          ),
        ],
      ),
    );
  }
}

class _CohortTrackListCard extends StatelessWidget {
  const _CohortTrackListCard({
    required this.cohort,
    required this.selectedSeeds,
    required this.onToggleSeed,
  });

  final PlaylistCohortResponse cohort;
  final Set<String> selectedSeeds;
  final ValueChanged<String> onToggleSeed;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: colors.outlineVariant.withValues(alpha: 0.7)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: <Widget>[
              Text(
                'TRACK-BY-TRACK COHORT ANALYSIS (${cohort.trackMatches.length} TRACKS)',
                style: text.labelSmall?.copyWith(
                  fontWeight: FontWeight.w800,
                  letterSpacing: 0.8,
                  color: colors.onSurfaceVariant,
                ),
              ),
              Text(
                'Click any track to seed',
                style: text.labelSmall?.copyWith(color: colors.primary),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.md),
          ...cohort.trackMatches.map((PlaylistTrackMatch m) {
            final bool isSeeded = selectedSeeds.contains(m.trackKey);
            final (String badgeLabel, Color badgeColor) = switch (m.status) {
              'IN_COHORT_EXACT' => (
                  '★ Core Favorite (${m.scrobbleCount} plays)',
                  const Color(0xFF10B981)
                ),
              'ARTIST_FAMILIAR_NEW_TRACK' => (
                  '✓ Familiar Artist (${m.artistTotalScrobbles} artist plays)',
                  const Color(0xFF38BDF8)
                ),
              _ => ('✨ Fresh Discovery', const Color(0xFFF59E0B)),
            };

            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Material(
                color: isSeeded
                    ? colors.primaryContainer.withValues(alpha: 0.3)
                    : colors.surface,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                  side: BorderSide(
                    color: isSeeded
                        ? colors.primary
                        : colors.outlineVariant.withValues(alpha: 0.5),
                  ),
                ),
                child: InkWell(
                  borderRadius: BorderRadius.circular(10),
                  onTap: () => onToggleSeed(m.trackKey),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 8,
                    ),
                    child: Row(
                      children: <Widget>[
                        Icon(
                          isSeeded
                              ? Icons.check_circle_rounded
                              : Icons.add_circle_outline_rounded,
                          size: 18,
                          color: isSeeded ? colors.primary : colors.onSurfaceVariant,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: <Widget>[
                              Text(
                                m.title,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: text.titleSmall?.copyWith(
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              Text(
                                m.artist,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: text.bodySmall?.copyWith(
                                  color: colors.onSurfaceVariant,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: badgeColor.withValues(alpha: 0.14),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            badgeLabel,
                            style: text.labelSmall?.copyWith(
                              color: badgeColor,
                              fontWeight: FontWeight.w700,
                              fontSize: 10,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          }),
        ],
      ),
    );
  }
}

class _FloatingSeedBar extends StatelessWidget {
  const _FloatingSeedBar({
    required this.count,
    required this.forging,
    required this.onForge,
    required this.onClear,
  });

  final int count;
  final bool forging;
  final VoidCallback onForge;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: BgSpace.lg),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        color: colors.primaryContainer,
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: colors.primary, width: 1.5),
        boxShadow: <BoxShadow>[
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.35),
            blurRadius: 20,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(Icons.auto_awesome_rounded, color: colors.onPrimaryContainer, size: 18),
          const SizedBox(width: 8),
          Text(
            '$count seed track(s)',
            style: text.labelLarge?.copyWith(
              color: colors.onPrimaryContainer,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(width: 12),
          FilledButton.icon(
            onPressed: forging ? null : onForge,
            icon: forging
                ? const SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Icon(Icons.bolt_rounded, size: 16),
            label: Text(
              forging ? 'FORGING…' : 'FORGE DAYLIST WITH SEEDS',
              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12),
            ),
          ),
          const SizedBox(width: 4),
          IconButton(
            tooltip: 'Clear seeds',
            onPressed: onClear,
            icon: Icon(Icons.close_rounded, size: 18, color: colors.onPrimaryContainer),
          ),
        ],
      ),
    );
  }
}

class _CohortDonutPainter extends CustomPainter {
  _CohortDonutPainter({
    required this.slices,
    required this.centerLabel,
    required this.centerSublabel,
    required this.textColor,
  });

  final List<CohortPieSlice> slices;
  final String centerLabel;
  final String centerSublabel;
  final Color textColor;

  @override
  void paint(Canvas canvas, Size size) {
    final double cx = size.width / 2;
    final double cy = size.height / 2;
    final double radius = math.min(cx, cy) * 0.85;
    final double strokeWidth = radius * 0.38;

    double startAngle = -math.pi / 2;
    final double total =
        slices.fold<double>(0.0, (double s, CohortPieSlice p) => s + p.count);
    final double denom = total > 0 ? total : 1.0;

    for (final CohortPieSlice slice in slices) {
      final double sweep = (slice.count / denom) * (2 * math.pi);
      final Paint paint = Paint()
        ..color = _parseHexColor(slice.colorHex)
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.butt;

      canvas.drawArc(
        Rect.fromCircle(
          center: Offset(cx, cy),
          radius: radius - strokeWidth / 2,
        ),
        startAngle,
        math.max(sweep - 0.04, 0.02),
        false,
        paint,
      );
      startAngle += sweep;
    }

    final TextPainter tpMain = TextPainter(
      text: TextSpan(
        text: centerLabel,
        style: TextStyle(
          color: textColor,
          fontSize: 22,
          fontWeight: FontWeight.w800,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tpMain.paint(
      canvas,
      Offset(cx - tpMain.width / 2, cy - tpMain.height / 2 - 8),
    );

    final TextPainter tpSub = TextPainter(
      text: TextSpan(
        text: centerSublabel.toUpperCase(),
        style: TextStyle(
          color: textColor.withValues(alpha: 0.65),
          fontSize: 10,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.8,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tpSub.paint(
      canvas,
      Offset(cx - tpSub.width / 2, cy + tpMain.height / 2 - 4),
    );
  }

  @override
  bool shouldRepaint(covariant _CohortDonutPainter oldDelegate) =>
      oldDelegate.slices != slices || oldDelegate.centerLabel != centerLabel;
}

// =============================================================================
// FORMATTING HELPERS
// =============================================================================

String _formatThemeName(String raw) {
  if (raw.isEmpty) return 'Petrichor';
  return raw
      .split('_')
      .map((String w) =>
          w.isEmpty ? '' : '${w[0].toUpperCase()}${w.substring(1)}')
      .join(' ');
}

String _formatShortTimestamp(String iso) {
  if (iso.isEmpty) return '';
  final DateTime? dt = DateTime.tryParse(iso)?.toLocal();
  if (dt == null) return iso;
  final String month = const <String>[
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ][dt.month - 1];
  final String hh = dt.hour.toString().padLeft(2, '0');
  final String mm = dt.minute.toString().padLeft(2, '0');
  return '$month ${dt.day}, $hh:$mm';
}

Color _themeAccentColor(String themeId) {
  return switch (themeId) {
    'petrichor' => const Color(0xFF38BDF8),
    'golden_hour' => const Color(0xFFF59E0B),
    'nordic_fog' => const Color(0xFF94A3B8),
    'storm_front' => const Color(0xFF818CF8),
    'heatwave_cruise' => const Color(0xFFFB7185),
    'blue_hour' => const Color(0xFF60A5FA),
    'first_frost' => const Color(0xFF2DD4BF),
    'sirocco' => const Color(0xFFF97316),
    _ => const Color(0xFF38BDF8),
  };
}

Color _parseHexColor(String hex) {
  final String clean = hex.replaceAll('#', '').trim();
  if (clean.length == 6) {
    return Color(int.parse('FF$clean', radix: 16));
  }
  return const Color(0xFF10B981);
}
