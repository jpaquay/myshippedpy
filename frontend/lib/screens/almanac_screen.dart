/// The Sonic Almanac & Scrobble Explorer.
///
/// Backed by Firestore collections (`forges` and `scrobbles`), offering:
/// 1. Forged Sets History: view every Weather-Inspired Daylist forged, with
///    barometric telemetry and one-click reload into the Player Deck.
/// 2. Scrobble Explorer & Sonic DNA Analytics: search, filter, and analyse
///    your scrobbles by micro-genre, BPM, and weather affinity, and select
///    scrobbles to seed new atmospheric Daylists in the Forge.
library;

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
  bool _syncing = false;
  bool _forgingFromScrobbles = false;
  String? _error;

  List<AlmanacEntry> _history = const <AlmanacEntry>[];
  Retrospective _retro = Retrospective.empty;
  ScrobbleSearchResponse _scrobbleData = ScrobbleSearchResponse.empty;

  String _searchQuery = '';
  String? _selectedTag;
  String? _selectedTheme;
  final TextEditingController _searchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadHistory();
      _loadScrobbles();
    });
  }

  @override
  void dispose() {
    _tabController.dispose();
    _searchController.dispose();
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
          content: Text('Synced Last.fm scrobbles to Firestore `scrobbles` collection.'),
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
          degraded: pl.rationale?.degraded ?? const <String>[],
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
                    '${selectedScrobbles.length} scrobble(s) selected',
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
                          : 'FORGE DAYLIST WITH SCROBBLES',
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
                      Row(
                        children: <Widget>[
                          Text('Sonic Almanac', style: text.displaySmall),
                          const SizedBox(width: BgSpace.sm),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: colors.primary.withValues(alpha: 0.15),
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(color: colors.primary.withValues(alpha: 0.35)),
                            ),
                            child: Text(
                              'FIRESTORE PERSISTED',
                              style: text.labelSmall?.copyWith(
                                color: colors.primary,
                                fontWeight: FontWeight.w700,
                                fontSize: 10,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Explore your Firestore-persisted Daylist forge history and analyse your Last.fm scrobbles to seed new weather-inspired sets.',
                        style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: 'Refresh Almanac & Scrobbles',
                  onPressed: () {
                    _loadHistory();
                    _loadScrobbles();
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
              ],
            ),
          ),
        ],
      ),
    );
  }

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
                    'Head to the Forge screen or select scrobbles in the Scrobble Explorer tab to synthesize your first weather-inspired Daylist.',
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
                  border: Border.all(color: colors.primary.withValues(alpha: 0.25)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Row(
                      children: <Widget>[
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: colors.primary.withValues(alpha: 0.16),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            (entry.themeId.isEmpty ? 'PETRICHOR' : entry.themeId)
                                .replaceAll('_', ' ')
                                .toUpperCase(),
                            style: text.labelSmall?.copyWith(
                              color: colors.primary,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        if (entry.locationLabel != null && entry.locationLabel!.isNotEmpty) ...<Widget>[
                          Icon(Icons.place_outlined, size: 14, color: colors.secondary),
                          const SizedBox(width: 4),
                          Text(
                            entry.locationLabel!,
                            style: text.labelSmall?.copyWith(
                              color: colors.secondary,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(width: 8),
                        ],
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: colors.surfaceContainerHighest,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            trendBadge,
                            style: text.labelSmall?.copyWith(fontSize: 10),
                          ),
                        ),
                        const Spacer(),
                        Text(
                          '${entry.trackCount} tracks',
                          style: text.labelSmall?.copyWith(color: colors.onSurfaceVariant),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      entry.title,
                      style: text.titleMedium?.copyWith(fontWeight: FontWeight.w800),
                    ),
                    if (entry.headline != null && entry.headline!.isNotEmpty) ...<Widget>[
                      const SizedBox(height: 4),
                      Text(
                        entry.headline!,
                        style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
                      ),
                    ],
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
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: <Widget>[
                        FilledButton.tonalIcon(
                          onPressed: () => _reloadForgedPlaylist(entry),
                          icon: const Icon(Icons.play_circle_outline, size: 17),
                          label: const Text(
                            'OPEN & PLAY THIS DAYLIST',
                            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 12),
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

  Widget _buildScrobbleExplorerTab(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final ScrobbleAnalytics analytics = _scrobbleData.analytics;
    final Set<String> selectedScrobbles = ref.watch(selectedSeedScrobblesProvider);

    return ListView(
      padding: const EdgeInsets.fromLTRB(BgSpace.xl, BgSpace.sm, BgSpace.xl, 110),
      children: <Widget>[
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
                    'SONIC DNA & BAROMETRIC SCROBBLE ANALYTICS',
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
                      _syncing ? 'SYNCING LAST.FM…' : 'SYNC LAST.FM TO FIRESTORE',
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
                    label: 'INDEXED CATALOG',
                    value: '${analytics.uniqueTracks} tracks',
                    icon: Icons.library_music_outlined,
                  ),
                  _DnaStatCard(
                    label: 'AVG TEMPO PROFILE',
                    value: '${analytics.avgBpm.toStringAsFixed(0)} BPM',
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
                      label: Text('$label • ${pct.toStringAsFixed(0)}%'),
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
                  hintText: 'Search scrobbles by artist, track title, album, or tag…',
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
                            const SizedBox(height: 6),
                            Wrap(
                              spacing: 4,
                              runSpacing: 4,
                              children: item.tags.map((String t) {
                                return Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: colors.surface,
                                    borderRadius: BorderRadius.circular(6),
                                    border: Border.all(color: colors.outlineVariant),
                                  ),
                                  child: Text(
                                    '#$t',
                                    style: text.labelSmall?.copyWith(fontSize: 10),
                                  ),
                                );
                              }).toList(),
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
