/// The Sonic Almanac, BigQuery OLAP Scrobble Explorer & Playlist Cohort Analysis Screen.
///
/// Backed by Dual-Store Architecture (`netdev-firebase:barogroove_analytics` BigQuery OLAP
/// + Firestore collections `forges`, `scrobbles`, `track_catalog`, `scrobble_summaries`), offering:
/// 1. Forged Sets History: view every Weather-Inspired Daylist forged, reload into Player, or
///    cross-check any forged set against your 15-year scrobble cohort.
/// 2. Scrobble Explorer & Sonic DNA Analytics: search, filter, and analyse 160,717 scrobbles
///    with Two-Tier BigQuery Cache telemetry ($0.00 cost guardrails) and 15-year volume charts.
/// 3. Playlist & Song Cohort Analysis: paste any Spotify/Last.fm playlist or song link/ID
///    or tracklist to generate visual Donut/Pie & 15-Year Timeline Bar charts comparing the
///    playlist against your 160,717-scrobble listening cohort.
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../a2ui/messages.dart';
import '../api/client.dart';
import '../api/models.dart';
import '../app_theme.dart';
import '../providers.dart';
import 'shell.dart';
import 'widgets/status_notes.dart';

class AlmanacScreen extends ConsumerStatefulWidget {
  const AlmanacScreen({super.key});

  @override
  ConsumerState<AlmanacScreen> createState() => _AlmanacScreenState();
}

class _AlmanacScreenState extends ConsumerState<AlmanacScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  bool _loadingHistory = true;
  bool _loadingScrobbles = true;
  bool _loadingCohort = false;
  bool _syncing = false;
  bool _forgingFromScrobbles = false;
  String? _error;

  List<AlmanacEntry> _history = const <AlmanacEntry>[];
  Retrospective _retro = Retrospective.empty;
  ScrobbleSearchResponse _scrobbleData = ScrobbleSearchResponse.empty;
  PlaylistCohortResponse? _cohortResult;

  String _searchQuery = '';
  String? _selectedTag;
  String? _selectedTheme;
  final TextEditingController _searchController = TextEditingController();
  final TextEditingController _cohortInputController = TextEditingController(
    text: 'preset:chanson',
  );

  // Toggles for Visual Charts in Playlist Cohort Tab
  bool _pieShowWeather = false;
  bool _graphShowCircadian = false;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadHistory();
      _loadScrobbles();
      _runCohortCheck('preset:chanson');
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
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
    final results = await Future.wait(<Future<Object>>[
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
    _cohortInputController.text = tracklistText.isNotEmpty
        ? tracklistText
        : 'preset:chanson';
    _tabController.animateTo(2);
    await _runCohortCheck(
      _cohortInputController.text,
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

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final Set<String> selectedScrobbles = ref.watch(selectedSeedScrobblesProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      floatingActionButtonLocation: FloatingActionButtonLocation.centerFloat,
      floatingActionButton: selectedScrobbles.isNotEmpty
          ? Container(
              margin: const EdgeInsets.symmetric(horizontal: BgSpace.xl),
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
                  Icon(Icons.auto_awesome, color: colors.onPrimaryContainer, size: 18),
                  const SizedBox(width: 8),
                  Text(
                    '${selectedScrobbles.length} track(s) selected',
                    style: text.labelLarge?.copyWith(
                      color: colors.onPrimaryContainer,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(width: 12),
                  FilledButton.icon(
                    onPressed: _forgingFromScrobbles ? null : _forgeWithSelectedScrobbles,
                    icon: _forgingFromScrobbles
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.bolt, size: 16),
                    label: Text(
                      _forgingFromScrobbles
                          ? 'FORGING DAYLIST…'
                          : 'FORGE DAYLIST WITH COHORT SEEDS',
                      style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12),
                    ),
                  ),
                  const SizedBox(width: 6),
                  IconButton(
                    tooltip: 'Clear selection',
                    onPressed: () {
                      ref.read(selectedSeedScrobblesProvider.notifier).state = <String>{};
                    },
                    icon: Icon(Icons.close, size: 18, color: colors.onPrimaryContainer),
                  ),
                ],
              ),
            )
          : null,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(BgSpace.xl, BgSpace.lg, BgSpace.xl, BgSpace.sm),
            child: Row(
              children: <Widget>[
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Wrap(
                        crossAxisAlignment: WrapCrossAlignment.center,
                        spacing: BgSpace.sm,
                        runSpacing: 4,
                        children: <Widget>[
                          Text('Sonic Almanac & BigQuery OLAP', style: text.displaySmall),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: const Color(0xFF10B981).withValues(alpha: 0.15),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(color: const Color(0xFF10B981).withValues(alpha: 0.4)),
                            ),
                            child: Text(
                              'BQ OLAP + 2-TIER CACHE • \$0.00 COST',
                              style: text.labelSmall?.copyWith(
                                color: const Color(0xFF10B981),
                                fontWeight: FontWeight.w800,
                                fontSize: 10,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Explore your 15-year 160,717-scrobble cohort in BigQuery OLAP, filter by BaroGroove Sonic DNA, and cross-check any playlist or song link with visual Donut & Timeline charts.',
                        style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: 'Refresh Almanac, BigQuery Cache & Cohort',
                  onPressed: () {
                    _loadHistory();
                    _loadScrobbles();
                    _runCohortCheck(_cohortInputController.text);
                  },
                  icon: const Icon(Icons.refresh),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: BgSpace.xl),
            child: TabBar(
              controller: _tabController,
              isScrollable: true,
              tabAlignment: TabAlignment.start,
              tabs: <Widget>[
                Tab(
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      const Icon(Icons.history_edu_outlined, size: 18),
                      const SizedBox(width: 8),
                      Text('FORGE HISTORY (${_history.length})'),
                    ],
                  ),
                ),
                Tab(
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      const Icon(Icons.analytics_outlined, size: 18),
                      const SizedBox(width: 8),
                      Text('SCROBBLE EXPLORER & DNA (${_scrobbleData.analytics.uniqueTracks})'),
                    ],
                  ),
                ),
                const Tab(
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Icon(Icons.pie_chart_outline, size: 18),
                      SizedBox(width: 8),
                      Text('PLAYLIST COHORT ANALYSIS (CROSS-CHECK)'),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: BgSpace.sm),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: <Widget>[
                _buildForgeHistoryTab(context),
                _buildScrobbleExplorerTab(context),
                _buildPlaylistCohortAnalysisTab(context),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ===========================================================================
  // TAB 1: FORGE HISTORY
  // ===========================================================================
  Widget _buildForgeHistoryTab(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    if (_loadingHistory) {
      return const Center(child: CircularProgressIndicator());
    }

    return RefreshIndicator(
      onRefresh: _loadHistory,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(BgSpace.xl, BgSpace.sm, BgSpace.xl, 100),
        children: <Widget>[
          if (_error != null) ...<Widget>[
            DegradedNotes(
              title: 'Almanac note',
              notes: <String>[_error!],
              tone: DegradedTone.notice,
            ),
            const SizedBox(height: BgSpace.md),
          ],
          if (_retro.items.isNotEmpty) ...<Widget>[
            Text(
              'ATMOSPHERIC SIGNATURES',
              style: text.labelSmall?.copyWith(
                color: colors.primary,
                fontWeight: FontWeight.w800,
                letterSpacing: 0.9,
              ),
            ),
            const SizedBox(height: BgSpace.xs),
            Wrap(
              spacing: BgSpace.md,
              runSpacing: BgSpace.md,
              children: _retro.items.map((RetrospectiveItem item) {
                return Container(
                  width: 260,
                  padding: const EdgeInsets.all(BgSpace.md),
                  decoration: BoxDecoration(
                    color: colors.surfaceContainerHigh,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: colors.outlineVariant),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        item.label.toUpperCase(),
                        style: text.labelSmall?.copyWith(
                          color: colors.primary,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        item.detail,
                        style: text.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                );
              }).toList(),
            ),
            const SizedBox(height: BgSpace.lg),
          ],
          Text(
            'FORGED WEATHER DAYLISTS (FIRESTORE `forges` COLLECTION)',
            style: text.labelSmall?.copyWith(
              color: colors.onSurfaceVariant,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.9,
            ),
          ),
          const SizedBox(height: BgSpace.sm),
          if (_history.isEmpty)
            Container(
              padding: const EdgeInsets.all(BgSpace.xl),
              decoration: BoxDecoration(
                color: colors.surfaceContainer,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: colors.outlineVariant),
              ),
              child: Column(
                children: <Widget>[
                  Icon(Icons.cloud_queue, size: 42, color: colors.onSurfaceVariant),
                  const SizedBox(height: BgSpace.sm),
                  Text(
                    'No Daylists forged in this session yet.',
                    style: text.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Head to the Forge screen or select tracks in the Cohort Analysis tab to synthesize your first weather-inspired Daylist.',
                    style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            )
          else
            ..._history.map((AlmanacEntry entry) {
              final double? trend = entry.pressureTrend6h;
              final String trendBadge = trend != null
                  ? '${trend >= 0 ? "+" : ""}${(trend * 12.0).toStringAsFixed(1)} hPa/6h'
                  : 'Barometric Front';
              return Container(
                margin: const EdgeInsets.only(bottom: BgSpace.md),
                padding: const EdgeInsets.all(BgSpace.md),
                decoration: BoxDecoration(
                  color: colors.surfaceContainerHigh,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: colors.outlineVariant),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Row(
                      children: <Widget>[
                        Icon(Icons.album_outlined, color: colors.primary, size: 20),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            entry.title,
                            style: text.titleMedium?.copyWith(fontWeight: FontWeight.w800),
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: colors.secondaryContainer,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            trendBadge,
                            style: text.labelSmall?.copyWith(
                              color: colors.onSecondaryContainer,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Theme: ${entry.themeId} • ${entry.trackCount} tracks • Forged ${entry.createdAt}',
                      style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
                    ),
                    if (entry.tracksPreview.isNotEmpty) ...<Widget>[
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 6,
                        runSpacing: 4,
                        children: entry.tracksPreview.map((String tr) {
                          return Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: colors.surface,
                              borderRadius: BorderRadius.circular(6),
                              border: Border.all(color: colors.outlineVariant),
                            ),
                            child: Text(
                              tr,
                              style: text.labelSmall?.copyWith(fontSize: 10),
                            ),
                          );
                        }).toList(),
                      ),
                    ],
                    const SizedBox(height: 10),
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      alignment: WrapAlignment.end,
                      children: <Widget>[
                        OutlinedButton.icon(
                          onPressed: () => _crossCheckForgedSet(entry),
                          icon: const Icon(Icons.pie_chart_outline, size: 16),
                          label: const Text(
                            'CROSS-CHECK IN COHORT',
                            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 11),
                          ),
                        ),
                        FilledButton.tonalIcon(
                          onPressed: () => _reloadForgedPlaylist(entry),
                          icon: const Icon(Icons.play_circle_outline, size: 17),
                          label: const Text(
                            'OPEN & PLAY DAYLIST',
                            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 11),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              );
            }),
        ],
      ),
    );
  }

  // ===========================================================================
  // TAB 2: SCROBBLE EXPLORER & DNA (BIGQUERY OLAP + 2-TIER CACHE)
  // ===========================================================================
  Widget _buildScrobbleExplorerTab(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final ScrobbleAnalytics analytics = _scrobbleData.analytics;
    final Set<String> selectedScrobbles = ref.watch(selectedSeedScrobblesProvider);

    return ListView(
      padding: const EdgeInsets.fromLTRB(BgSpace.xl, BgSpace.sm, BgSpace.xl, 110),
      children: <Widget>[
        // BigQuery OLAP & Two-Tier Cache Telemetry Banner
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          margin: const EdgeInsets.only(bottom: BgSpace.md),
          decoration: BoxDecoration(
            color: colors.surfaceContainerHigh,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFF10B981).withValues(alpha: 0.45)),
          ),
          child: Wrap(
            spacing: 16,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: <Widget>[
              Row(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  const Icon(Icons.bolt, color: Color(0xFF10B981), size: 18),
                  const SizedBox(width: 6),
                  Text(
                    'QUERY ENGINE: ${_scrobbleData.queryEngine.toUpperCase()}',
                    style: text.labelSmall?.copyWith(
                      color: const Color(0xFF10B981),
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: const Color(0xFF10B981).withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  'CACHE: ${_scrobbleData.cacheStatus}',
                  style: text.labelSmall?.copyWith(
                    color: const Color(0xFF10B981),
                    fontWeight: FontWeight.w800,
                    fontSize: 10,
                  ),
                ),
              ),
              Text(
                'Latency: ${_scrobbleData.executionMs.toStringAsFixed(1)} ms',
                style: text.labelSmall?.copyWith(fontWeight: FontWeight.w700),
              ),
              Text(
                'Bytes Billed: ${_scrobbleData.bytesBilled} B (\$${_scrobbleData.estimatedCostUsd.toStringAsFixed(4)})',
                style: text.labelSmall?.copyWith(
                  color: colors.onSurfaceVariant,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),

        // Sonic DNA Analytics Dashboard Card
        Container(
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
            border: Border.all(color: colors.primary.withValues(alpha: 0.3)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Icon(Icons.graphic_eq, color: colors.primary, size: 18),
                  const SizedBox(width: 8),
                  Text(
                    '15-YEAR SONIC DNA & BAROMETRIC SCROBBLE ANALYTICS (2012–2026)',
                    style: text.labelSmall?.copyWith(
                      color: colors.primary,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.8,
                    ),
                  ),
                  const Spacer(),
                  FilledButton.tonalIcon(
                    onPressed: _syncing ? null : _syncLastfmToFirestore,
                    icon: _syncing
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.cloud_sync_outlined, size: 16),
                    label: Text(
                      _syncing ? 'SYNCING…' : 'SYNC LAST.FM',
                      style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: BgSpace.md),
              Wrap(
                spacing: BgSpace.md,
                runSpacing: BgSpace.sm,
                children: <Widget>[
                  _DnaStatCard(
                    label: 'TOTAL SCROBBLES',
                    value: '${analytics.totalScrobbles} plays',
                    icon: Icons.headphones,
                  ),
                  _DnaStatCard(
                    label: 'UNIQUE CATALOG',
                    value: '${analytics.uniqueTracks} tracks',
                    icon: Icons.library_music_outlined,
                  ),
                  _DnaStatCard(
                    label: 'AVG TEMPO PROFILE',
                    value: '${analytics.avgBpm.toStringAsFixed(1)} BPM',
                    icon: Icons.speed,
                  ),
                  _DnaStatCard(
                    label: 'AVG SONIC ENERGY',
                    value: '${(analytics.avgEnergy * 100).toStringAsFixed(0)}%',
                    icon: Icons.bolt,
                  ),
                ],
              ),
              const SizedBox(height: BgSpace.md),
              Text(
                'DOMINANT MICRO-GENRE TAGS (TAP TO FILTER):',
                style: text.labelSmall?.copyWith(
                  color: colors.onSurfaceVariant,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: <Widget>[
                  if (_selectedTag != null)
                    ActionChip(
                      avatar: const Icon(Icons.clear, size: 14),
                      label: Text('Clear tag: #$_selectedTag'),
                      onPressed: () {
                        setState(() => _selectedTag = null);
                        _loadScrobbles();
                      },
                    ),
                  ...analytics.topGenres.map((JsonMap g) {
                    final String tag = g['tag']?.toString() ?? '';
                    final int count = (g['count'] as num?)?.toInt() ?? 0;
                    final bool active = _selectedTag == tag;
                    return FilterChip(
                      selected: active,
                      label: Text('#$tag ($count)'),
                      onSelected: (bool val) {
                        setState(() => _selectedTag = val ? tag : null);
                        _loadScrobbles();
                      },
                    );
                  }),
                ],
              ),
              const SizedBox(height: BgSpace.md),
              Text(
                'BAROMETRIC WEATHER THEME AFFINITY (TAP TO FILTER):',
                style: text.labelSmall?.copyWith(
                  color: colors.onSurfaceVariant,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: <Widget>[
                  if (_selectedTheme != null)
                    ActionChip(
                      avatar: const Icon(Icons.clear, size: 14),
                      label: Text('Clear theme: $_selectedTheme'),
                      onPressed: () {
                        setState(() => _selectedTheme = null);
                        _loadScrobbles();
                      },
                    ),
                  ...analytics.weatherAffinity.map((JsonMap w) {
                    final String tid = w['theme_id']?.toString() ?? '';
                    final String label = w['label']?.toString() ?? tid;
                    final double pct = (w['percentage'] as num?)?.toDouble() ?? 0.0;
                    final bool active = _selectedTheme == tid;
                    return FilterChip(
                      selected: active,
                      label: Text('$label • ${pct.toStringAsFixed(1)}%'),
                      onSelected: (bool val) {
                        setState(() => _selectedTheme = val ? tid : null);
                        _loadScrobbles();
                      },
                    );
                  }),
                ],
              ),
            ],
          ),
        ),

        const SizedBox(height: BgSpace.md),

        // Search & Filter Bar
        Row(
          children: <Widget>[
            Expanded(
              child: TextField(
                controller: _searchController,
                onChanged: (String val) {
                  _searchQuery = val;
                  _loadScrobbles();
                },
                decoration: InputDecoration(
                  hintText: 'Search 44,361 catalog tracks by artist, title, album, or tag…',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _searchQuery.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.clear),
                          onPressed: () {
                            _searchController.clear();
                            _searchQuery = '';
                            _loadScrobbles();
                          },
                        )
                      : null,
                  filled: true,
                  fillColor: colors.surfaceContainerHigh,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide.none,
                  ),
                ),
              ),
            ),
            const SizedBox(width: BgSpace.sm),
            OutlinedButton.icon(
              onPressed: () {
                final Set<String> allKeys =
                    _scrobbleData.scrobbles.take(5).map((ScrobbleEntry e) => e.trackKey).toSet();
                ref.read(selectedSeedScrobblesProvider.notifier).state = allKeys;
              },
              icon: const Icon(Icons.select_all, size: 16),
              label: const Text('Select Top 5'),
            ),
          ],
        ),

        const SizedBox(height: BgSpace.md),

        Text(
          'CHECK SCROBBLES BELOW TO SEED YOUR NEXT WEATHER-INSPIRED DAYLIST:',
          style: text.labelSmall?.copyWith(
            color: colors.primary,
            fontWeight: FontWeight.w800,
            letterSpacing: 0.7,
          ),
        ),
        const SizedBox(height: BgSpace.xs),

        if (_loadingScrobbles)
          const Padding(
            padding: EdgeInsets.all(BgSpace.xl),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (_scrobbleData.scrobbles.isEmpty)
          Container(
            padding: const EdgeInsets.all(BgSpace.xl),
            decoration: BoxDecoration(
              color: colors.surfaceContainer,
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Center(
              child: Text('No scrobbles match your current filter.'),
            ),
          )
        else
          ..._scrobbleData.scrobbles.map((ScrobbleEntry item) {
            final bool isSelected = selectedScrobbles.contains(item.trackKey);
            return Container(
              margin: const EdgeInsets.only(bottom: 8),
              decoration: BoxDecoration(
                color: isSelected
                    ? colors.primaryContainer.withValues(alpha: 0.38)
                    : colors.surfaceContainerHigh,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: isSelected
                      ? colors.primary
                      : colors.outlineVariant.withValues(alpha: 0.6),
                  width: isSelected ? 1.5 : 1.0,
                ),
              ),
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () {
                  final Set<String> next = Set<String>.from(selectedScrobbles);
                  if (isSelected) {
                    next.remove(item.trackKey);
                  } else {
                    next.add(item.trackKey);
                  }
                  ref.read(selectedSeedScrobblesProvider.notifier).state = next;
                },
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  child: Row(
                    children: <Widget>[
                      Checkbox(
                        value: isSelected,
                        onChanged: (bool? val) {
                          final Set<String> next = Set<String>.from(selectedScrobbles);
                          if (val == true) {
                            next.add(item.trackKey);
                          } else {
                            next.remove(item.trackKey);
                          }
                          ref.read(selectedSeedScrobblesProvider.notifier).state = next;
                        },
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Row(
                              children: <Widget>[
                                Expanded(
                                  child: Text(
                                    '${item.artist} — ${item.title}',
                                    style: text.titleSmall?.copyWith(
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: colors.primary.withValues(alpha: 0.14),
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: Text(
                                    item.weatherTheme.replaceAll('_', ' ').toUpperCase(),
                                    style: text.labelSmall?.copyWith(
                                      color: colors.primary,
                                      fontWeight: FontWeight.w700,
                                      fontSize: 9,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Row(
                              children: <Widget>[
                                if (item.album != null && item.album!.isNotEmpty) ...<Widget>[
                                  Text(
                                    item.album!,
                                    style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
                                  ),
                                  const SizedBox(width: 10),
                                ],
                                Text(
                                  '${item.bpmEstimate} BPM • ${(item.energyEstimate * 100).toStringAsFixed(0)}% Energy • ${item.playCount} plays',
                                  style: text.labelSmall?.copyWith(
                                    color: colors.secondary,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          }),
      ],
    );
  }

  // ===========================================================================
  // TAB 3: PLAYLIST & SONG COHORT ANALYSIS (CROSS-CHECK WITH VISUAL PIE & BAR CHARTS)
  // ===========================================================================
  Widget _buildPlaylistCohortAnalysisTab(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final PlaylistCohortResponse? cohort = _cohortResult;
    final Set<String> selectedScrobbles = ref.watch(selectedSeedScrobblesProvider);

    return ListView(
      padding: const EdgeInsets.fromLTRB(BgSpace.xl, BgSpace.sm, BgSpace.xl, 110),
      children: <Widget>[
        // Input & Presets Card
        Container(
          padding: const EdgeInsets.all(BgSpace.lg),
          decoration: BoxDecoration(
            color: colors.surfaceContainerHigh,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: colors.primary.withValues(alpha: 0.35)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  Icon(Icons.compare_arrows, color: colors.primary, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'PLAYLIST & SONG COHORT CROSS-CHECKER (BIGQUERY OLAP)',
                      style: text.labelSmall?.copyWith(
                        color: colors.primary,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.8,
                      ),
                    ),
                  ),
                  if (cohort != null)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: const Color(0xFF10B981).withValues(alpha: 0.16),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        '${cohort.cacheStatus} • ${cohort.executionMs.toStringAsFixed(1)} ms • \$0.00',
                        style: text.labelSmall?.copyWith(
                          color: const Color(0xFF10B981),
                          fontWeight: FontWeight.w800,
                          fontSize: 10,
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                'Paste any Spotify Playlist/Track link (open.spotify.com/...), Last.fm URL, or multi-line "Artist - Title" list to cross-check against your 15-year 160,717-scrobble cohort.',
                style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
              ),
              const SizedBox(height: BgSpace.md),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Expanded(
                    child: TextField(
                      controller: _cohortInputController,
                      maxLines: 2,
                      minLines: 1,
                      decoration: InputDecoration(
                        hintText: 'Paste Spotify/Last.fm URL, preset ID, or Artist - Track lines…',
                        prefixIcon: const Icon(Icons.link),
                        filled: true,
                        fillColor: colors.surface,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                          borderSide: BorderSide(color: colors.outlineVariant),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: BgSpace.sm),
                  FilledButton.icon(
                    onPressed: _loadingCohort
                        ? null
                        : () => _runCohortCheck(_cohortInputController.text),
                    icon: _loadingCohort
                        ? const SizedBox(
                            width: 15,
                            height: 15,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.analytics, size: 17),
                    label: const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        'CROSS-CHECK COHORT',
                        style: TextStyle(fontWeight: FontWeight.w800, fontSize: 12),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: BgSpace.sm),
              Wrap(
                spacing: 8,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: <Widget>[
                  Text(
                    'INSTANT PRESETS:',
                    style: text.labelSmall?.copyWith(
                      color: colors.onSurfaceVariant,
                      fontWeight: FontWeight.w700,
                      fontSize: 10,
                    ),
                  ),
                  _CohortPresetChip(
                    label: 'Chanson & Poetic Acoustic',
                    presetId: 'preset:chanson',
                    active: _cohortInputController.text == 'preset:chanson',
                    onTap: () {
                      _cohortInputController.text = 'preset:chanson';
                      _runCohortCheck('preset:chanson');
                    },
                  ),
                  _CohortPresetChip(
                    label: 'Bristol Trip-Hop & Night',
                    presetId: 'preset:triphop',
                    active: _cohortInputController.text == 'preset:triphop',
                    onTap: () {
                      _cohortInputController.text = 'preset:triphop';
                      _runCohortCheck('preset:triphop');
                    },
                  ),
                  _CohortPresetChip(
                    label: '70s Analog & Golden Hour',
                    presetId: 'preset:golden70s',
                    active: _cohortInputController.text == 'preset:golden70s',
                    onTap: () {
                      _cohortInputController.text = 'preset:golden70s';
                      _runCohortCheck('preset:golden70s');
                    },
                  ),
                  _CohortPresetChip(
                    label: 'Roots Reggae & Dub Rain',
                    presetId: 'preset:reggaedub',
                    active: _cohortInputController.text == 'preset:reggaedub',
                    onTap: () {
                      _cohortInputController.text = 'preset:reggaedub';
                      _runCohortCheck('preset:reggaedub');
                    },
                  ),
                ],
              ),
            ],
          ),
        ),

        const SizedBox(height: BgSpace.md),

        if (_loadingCohort)
          const Padding(
            padding: EdgeInsets.all(BgSpace.xl),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (cohort != null) ...<Widget>[
          // 4 KPI Summary Cards
          Wrap(
            spacing: BgSpace.md,
            runSpacing: BgSpace.sm,
            children: <Widget>[
              _DnaStatCard(
                label: 'COHORT OVERLAP AFFINITY',
                value: '${cohort.cohortOverlapPct.toStringAsFixed(1)}% (${cohort.exactMatchesCount}/${cohort.totalTracks} exact)',
                icon: Icons.verified_outlined,
              ),
              _DnaStatCard(
                label: 'HISTORICAL COHORT PLAYS',
                value: '${cohort.totalHistoricalPlays} track plays (${cohort.totalArtistCohortPlays} artist)',
                icon: Icons.history,
              ),
              _DnaStatCard(
                label: 'PEAK NOSTALGIA ERA',
                value: cohort.peakNostalgiaYear,
                icon: Icons.auto_graph,
              ),
              _DnaStatCard(
                label: 'DOMINANT BAROMETRIC THEME',
                value: cohort.dominantWeatherTheme.replaceAll('_', ' ').toUpperCase(),
                icon: Icons.wb_twilight,
              ),
            ],
          ),

          const SizedBox(height: BgSpace.md),

          // Visual Charts Section: Side-by-Side Pie/Donut Chart + 15-Year Timeline Bar Chart
          LayoutBuilder(
            builder: (BuildContext context, BoxConstraints constraints) {
              final bool isWide = constraints.maxWidth > 760;
              final Widget pieCard = _buildVisualPieChartCard(context, cohort);
              final Widget barCard = _buildVisualTimelineGraphCard(context, cohort);

              if (isWide) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Expanded(child: pieCard),
                    const SizedBox(width: BgSpace.md),
                    Expanded(child: barCard),
                  ],
                );
              }
              return Column(
                children: <Widget>[
                  pieCard,
                  const SizedBox(height: BgSpace.md),
                  barCard,
                ],
              );
            },
          ),

          const SizedBox(height: BgSpace.md),

          // Track-by-Track Cohort Match Matrix Header
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  'TRACK-BY-TRACK COHORT MATCH MATRIX (${cohort.playlistTitle.toUpperCase()}):',
                  style: text.labelSmall?.copyWith(
                    color: colors.primary,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.7,
                  ),
                ),
              ),
              OutlinedButton.icon(
                onPressed: () {
                  final Set<String> exactKeys = cohort.trackMatches
                      .where((PlaylistTrackMatch m) => m.status == 'IN_COHORT_EXACT')
                      .map((PlaylistTrackMatch m) => m.trackKey)
                      .toSet();
                  ref.read(selectedSeedScrobblesProvider.notifier).state = exactKeys;
                },
                icon: const Icon(Icons.check_circle_outline, size: 15),
                label: const Text('Select All Exact Matches', style: TextStyle(fontSize: 11)),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.xs),

          // Track-by-Track Cohort Match Rows
          ...cohort.trackMatches.map((PlaylistTrackMatch m) {
            final bool isSelected = selectedScrobbles.contains(m.trackKey);
            final Color badgeColor = m.status == 'IN_COHORT_EXACT'
                ? const Color(0xFF10B981)
                : (m.status == 'ARTIST_FAMILIAR_NEW_TRACK'
                    ? const Color(0xFFF59E0B)
                    : const Color(0xFF0EA5E9));
            final String badgeText = m.status == 'IN_COHORT_EXACT'
                ? 'EXACT COHORT MATCH • ${m.scrobbleCount} PLAYS (${m.firstPlayedYear ?? 2013}–${m.lastPlayedYear ?? 2026})'
                : (m.status == 'ARTIST_FAMILIAR_NEW_TRACK'
                    ? 'FAMILIAR ARTIST • ${m.artistTotalScrobbles} ARTIST PLAYS'
                    : 'NEW COHORT DISCOVERY');

            return Container(
              margin: const EdgeInsets.only(bottom: 8),
              decoration: BoxDecoration(
                color: isSelected
                    ? colors.primaryContainer.withValues(alpha: 0.35)
                    : colors.surfaceContainerHigh,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: isSelected
                      ? colors.primary
                      : badgeColor.withValues(alpha: 0.35),
                  width: isSelected ? 1.5 : 1.0,
                ),
              ),
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () {
                  final Set<String> next = Set<String>.from(selectedScrobbles);
                  if (isSelected) {
                    next.remove(m.trackKey);
                  } else {
                    next.add(m.trackKey);
                  }
                  ref.read(selectedSeedScrobblesProvider.notifier).state = next;
                },
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  child: Row(
                    children: <Widget>[
                      Checkbox(
                        value: isSelected,
                        onChanged: (bool? val) {
                          final Set<String> next = Set<String>.from(selectedScrobbles);
                          if (val == true) {
                            next.add(m.trackKey);
                          } else {
                            next.remove(m.trackKey);
                          }
                          ref.read(selectedSeedScrobblesProvider.notifier).state = next;
                        },
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Row(
                              children: <Widget>[
                                Expanded(
                                  child: Text(
                                    '${m.position}. ${m.artist} — ${m.title}',
                                    style: text.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                                  decoration: BoxDecoration(
                                    color: badgeColor.withValues(alpha: 0.15),
                                    borderRadius: BorderRadius.circular(8),
                                    border: Border.all(color: badgeColor.withValues(alpha: 0.45)),
                                  ),
                                  child: Text(
                                    badgeText,
                                    style: text.labelSmall?.copyWith(
                                      color: badgeColor,
                                      fontWeight: FontWeight.w800,
                                      fontSize: 9.5,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Row(
                              children: <Widget>[
                                Text(
                                  'Weather Theme: ${m.weatherTheme.replaceAll('_', ' ').toUpperCase()}',
                                  style: text.labelSmall?.copyWith(
                                    color: colors.primary,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Text(
                                  '${m.bpmEstimate} BPM • ${(m.energyEstimate * 100).toStringAsFixed(0)}% Energy',
                                  style: text.labelSmall?.copyWith(
                                    color: colors.onSurfaceVariant,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                if (m.peakYear != null) ...<Widget>[
                                  const SizedBox(width: 12),
                                  Text(
                                    'Peak Era: ${m.peakYear}',
                                    style: text.labelSmall?.copyWith(
                                      color: colors.secondary,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          }),
        ],
      ],
    );
  }

  Widget _buildVisualPieChartCard(BuildContext context, PlaylistCohortResponse cohort) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final List<CohortPieSlice> slices =
        _pieShowWeather ? cohort.weatherPieSlices : cohort.cohortPieSlices;

    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHigh,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(Icons.pie_chart, color: colors.primary, size: 18),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _pieShowWeather
                      ? 'WEATHER THEME COHORT DISTRIBUTION'
                      : '15-YEAR SCROBBLE COHORT OVERLAP PIE',
                  style: text.labelSmall?.copyWith(
                    color: colors.primary,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              SegmentedButton<bool>(
                segments: const <ButtonSegment<bool>>[
                  ButtonSegment<bool>(
                    value: false,
                    label: Text('Cohort Overlap', style: TextStyle(fontSize: 10)),
                  ),
                  ButtonSegment<bool>(
                    value: true,
                    label: Text('Weather DNA', style: TextStyle(fontSize: 10)),
                  ),
                ],
                selected: <bool>{_pieShowWeather},
                onSelectionChanged: (Set<bool> val) {
                  setState(() => _pieShowWeather = val.first);
                },
              ),
            ],
          ),
          const SizedBox(height: BgSpace.md),
          Row(
            children: <Widget>[
              SizedBox(
                width: 150,
                height: 150,
                child: CustomPaint(
                  painter: _CohortDonutChartPainter(
                    slices: slices,
                    centerLabel: '${cohort.cohortOverlapPct.toStringAsFixed(0)}%',
                    centerSublabel: 'Cohort Fit',
                    textColor: colors.onSurface,
                  ),
                ),
              ),
              const SizedBox(width: BgSpace.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: slices.map((CohortPieSlice s) {
                    final Color sliceColor = _parseHexColor(s.colorHex);
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(
                        children: <Widget>[
                          Container(
                            width: 12,
                            height: 12,
                            decoration: BoxDecoration(
                              color: sliceColor,
                              borderRadius: BorderRadius.circular(3),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              s.label,
                              style: text.labelSmall?.copyWith(fontWeight: FontWeight.w700),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          Text(
                            '${s.count} (${s.percentage.toStringAsFixed(1)}%)',
                            style: text.labelSmall?.copyWith(
                              color: colors.onSurfaceVariant,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ],
                      ),
                    );
                  }).toList(),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildVisualTimelineGraphCard(
      BuildContext context, PlaylistCohortResponse cohort) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final Map<String, int> dataMap =
        _graphShowCircadian ? cohort.hourlyCohortGraph : cohort.yearlyCohortGraph;

    return Container(
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surfaceContainerHigh,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(Icons.bar_chart, color: colors.primary, size: 18),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _graphShowCircadian
                      ? 'CIRCADIAN 24H COHORT RHYTHM (UTC)'
                      : '15-YEAR COHORT SCROBBLE VOLUME (2012–2026)',
                  style: text.labelSmall?.copyWith(
                    color: colors.primary,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              SegmentedButton<bool>(
                segments: const <ButtonSegment<bool>>[
                  ButtonSegment<bool>(
                    value: false,
                    label: Text('Yearly (15Y)', style: TextStyle(fontSize: 10)),
                  ),
                  ButtonSegment<bool>(
                    value: true,
                    label: Text('24h Circadian', style: TextStyle(fontSize: 10)),
                  ),
                ],
                selected: <bool>{_graphShowCircadian},
                onSelectionChanged: (Set<bool> val) {
                  setState(() => _graphShowCircadian = val.first);
                },
              ),
            ],
          ),
          const SizedBox(height: BgSpace.md),
          SizedBox(
            height: 150,
            width: double.infinity,
            child: CustomPaint(
              painter: _CohortBarGraphPainter(
                data: dataMap,
                barColor: colors.primary,
                accentColor: const Color(0xFF10B981),
                labelColor: colors.onSurfaceVariant,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

Color _parseHexColor(String hex) {
  final String clean = hex.replaceAll('#', '').trim();
  if (clean.length == 6) {
    return Color(int.parse('FF$clean', radix: 16));
  }
  return const Color(0xFF10B981);
}

class _CohortDonutChartPainter extends CustomPainter {
  _CohortDonutChartPainter({
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
    final Offset center = Offset(size.width / 2, size.height / 2);
    final double radius = math.min(size.width, size.height) / 2 - 10;
    final Rect rect = Rect.fromCircle(center: center, radius: radius);

    double startAngle = -math.pi / 2;
    final double total =
        slices.fold<double>(0.0, (double s, CohortPieSlice item) => s + item.count);

    for (final CohortPieSlice slice in slices) {
      final double sweep =
          total > 0 ? (slice.count / total) * 2 * math.pi : (2 * math.pi / slices.length);
      final Paint paint = Paint()
        ..color = _parseHexColor(slice.colorHex)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 22.0
        ..strokeCap = StrokeCap.butt;

      canvas.drawArc(rect, startAngle, sweep - 0.04, false, paint);
      startAngle += sweep;
    }

    // Draw Center KPI Text
    final TextPainter tpMain = TextPainter(
      text: TextSpan(
        text: centerLabel,
        style: TextStyle(
          color: textColor,
          fontSize: 18,
          fontWeight: FontWeight.w900,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tpMain.paint(
      canvas,
      Offset(center.dx - tpMain.width / 2, center.dy - tpMain.height / 2 - 6),
    );

    final TextPainter tpSub = TextPainter(
      text: TextSpan(
        text: centerSublabel,
        style: TextStyle(
          color: textColor.withValues(alpha: 0.7),
          fontSize: 10,
          fontWeight: FontWeight.w700,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tpSub.paint(
      canvas,
      Offset(center.dx - tpSub.width / 2, center.dy + 8),
    );
  }

  @override
  bool shouldRepaint(covariant _CohortDonutChartPainter oldDelegate) =>
      oldDelegate.slices != slices || oldDelegate.centerLabel != centerLabel;
}

class _CohortBarGraphPainter extends CustomPainter {
  _CohortBarGraphPainter({
    required this.data,
    required this.barColor,
    required this.accentColor,
    required this.labelColor,
  });

  final Map<String, int> data;
  final Color barColor;
  final Color accentColor;
  final Color labelColor;

  @override
  void paint(Canvas canvas, Size size) {
    if (data.isEmpty) return;

    final List<String> keys = data.keys.toList();
    final int maxVal = data.values.fold<int>(1, math.max);
    const double bottomPad = 22.0;
    const double topPad = 14.0;
    final double chartHeight = size.height - bottomPad - topPad;
    final double slotWidth = size.width / keys.length;
    final double barWidth = math.max(slotWidth * 0.62, 4.0);

    for (int i = 0; i < keys.length; i++) {
      final String k = keys[i];
      final int val = data[k] ?? 0;
      final double ratio = val / maxVal;
      final double barH = math.max(ratio * chartHeight, 3.0);
      final double x = i * slotWidth + (slotWidth - barWidth) / 2;
      final double y = topPad + chartHeight - barH;

      final Paint barPaint = Paint()
        ..color = ratio > 0.75 ? accentColor : barColor.withValues(alpha: 0.85)
        ..style = PaintingStyle.fill;

      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(x, y, barWidth, barH),
          const Radius.circular(4),
        ),
        barPaint,
      );

      // Draw x-axis labels periodically so they don't overlap
      final bool showLabel = keys.length <= 16 ? (i % 2 == 0 || i == keys.length - 1) : (i % 4 == 0);
      if (showLabel) {
        final String shortKey = k.length == 4 ? "'${k.substring(2)}" : '${k}h';
        final TextPainter tp = TextPainter(
          text: TextSpan(
            text: shortKey,
            style: TextStyle(
              color: labelColor,
              fontSize: 9.5,
              fontWeight: FontWeight.w700,
            ),
          ),
          textDirection: TextDirection.ltr,
        )..layout();
        tp.paint(canvas, Offset(x + barWidth / 2 - tp.width / 2, size.height - 16));
      }
    }
  }

  @override
  bool shouldRepaint(covariant _CohortBarGraphPainter oldDelegate) =>
      oldDelegate.data != data;
}

class _CohortPresetChip extends StatelessWidget {
  const _CohortPresetChip({
    required this.label,
    required this.presetId,
    required this.active,
    required this.onTap,
  });

  final String label;
  final String presetId;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return ActionChip(
      avatar: Icon(
        active ? Icons.check_circle : Icons.playlist_play,
        size: 15,
        color: active ? colors.primary : colors.onSurfaceVariant,
      ),
      backgroundColor: active ? colors.primaryContainer : colors.surface,
      label: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: active ? FontWeight.w800 : FontWeight.w600,
        ),
      ),
      onPressed: onTap,
    );
  }
}

class _DnaStatCard extends StatelessWidget {
  const _DnaStatCard({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(icon, size: 18, color: colors.primary),
          const SizedBox(width: 8),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                label,
                style: text.labelSmall?.copyWith(
                  color: colors.onSurfaceVariant,
                  fontSize: 9,
                  fontWeight: FontWeight.w700,
                ),
              ),
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
