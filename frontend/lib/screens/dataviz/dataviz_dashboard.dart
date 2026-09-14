// Data Viz — the standing dashboard.
//
// The `SUMMARY` KPI ribbon and the four fixed analytics cards, lifted verbatim
// out of the former 2127-line `dataviz_screen.dart` so the conversational
// surface above them is readable on its own.
//
// UX_IA_SPEC.md §3.4 items 4 and 5:
//   * the ribbon is rung 1 (collapsed) on mobile, rung 0 on desktop;
//   * cards are one column on M, two on D, at the unified 900 breakpoint
//     (this file used to hard-code 920);
//   * `isHighlighted` survives — when an answer references a standing card the
//     card is marked for 4 s. No flashing, no scale animation.
//
// This dashboard is also the empty state. §3.4 bans a hero illustration and a
// welcome card precisely because there is already something worth reading here
// before the first question.


import 'package:flutter/material.dart';

import '../../app_theme.dart';
import '../../widgets/bg_disclosure.dart';
import 'dataviz_models.dart';

class DataVizDashboard extends StatefulWidget {
  const DataVizDashboard({
    super.key,
    required this.dashboard,
    required this.isExpanded,
    this.highlightSection,
    this.pinned = const <Widget>[],
    this.isLoading = false,
  });

  final DataVizDashboardModel dashboard;
  final bool isExpanded;

  /// The first fetch is still in flight. §2 rule 3: loading is rung 0 and
  /// shaped, so each card shows a block skeleton the size of its chart rather
  /// than a spinner — and, crucially, rather than a plausible chart.
  final bool isLoading;

  /// Answer cards the user pinned. §3.4: "Pin to dashboard promotes the card
  /// below the ribbon permanently" — so they sit between the KPI ribbon and
  /// the standing cards, not in the conversation.
  final List<Widget> pinned;

  /// `pressure_vs_bpm` | `weather_affinity` | `hourly_solar` | `decade_dna`,
  /// or null. Cleared by the caller after 4 s.
  final String? highlightSection;

  @override
  State<DataVizDashboard> createState() => _DataVizDashboardState();
}

class _DataVizDashboardState extends State<DataVizDashboard> {
  int? _selectedPressureIndex;
  int _selectedSolarHour = 19; // Default to 19:00 Blue Hour Peak

  DataVizDashboardModel get _dashboard => widget.dashboard;

  @override
  Widget build(BuildContext context) {
    final String? highlighted = widget.highlightSection;
    final bool isWide = widget.isExpanded;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        // Rung 1 on compact/medium, rung 0 on expanded (§3.4 item 4, §4) —
        // this destination's one sanctioned default-open exception. The ribbon
        // is not built at all while collapsed.
        BgDisclosure(
          label: 'Summary',
          initiallyExpanded: widget.isExpanded,
          bodyPadding: const EdgeInsets.only(top: BgSpace.md),
          builder: (BuildContext context) =>
              _buildSummaryKpiRibbon(context, isWide: isWide),
        ),
        const SizedBox(height: BgSpace.xl),
        if (widget.pinned.isNotEmpty) ...<Widget>[
          ...widget.pinned,
          const SizedBox(height: BgSpace.sm),
        ],
        if (isWide) ...<Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Expanded(
                child: _buildPressureVsBpmCard(
                  context,
                  isHighlighted: highlighted == 'pressure_vs_bpm',
                ),
              ),
              const SizedBox(width: BgSpace.lg),
              Expanded(
                child: _buildWeatherAffinityCard(
                  context,
                  isHighlighted: highlighted == 'weather_affinity',
                ),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.lg),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Expanded(
                child: _buildHourlySolarHeatmapCard(
                  context,
                  isHighlighted: highlighted == 'hourly_solar',
                ),
              ),
              const SizedBox(width: BgSpace.lg),
              Expanded(
                child: _buildDecadeSonicDnaCard(
                  context,
                  isHighlighted: highlighted == 'decade_dna',
                ),
              ),
            ],
          ),
        ] else ...<Widget>[
          _buildPressureVsBpmCard(
            context,
            isHighlighted: highlighted == 'pressure_vs_bpm',
          ),
          const SizedBox(height: BgSpace.lg),
          _buildWeatherAffinityCard(
            context,
            isHighlighted: highlighted == 'weather_affinity',
          ),
          const SizedBox(height: BgSpace.lg),
          _buildHourlySolarHeatmapCard(
            context,
            isHighlighted: highlighted == 'hourly_solar',
          ),
          const SizedBox(height: BgSpace.lg),
          _buildDecadeSonicDnaCard(
            context,
            isHighlighted: highlighted == 'decade_dna',
          ),
        ],
      ],
    );
  }

  /// A whole number with thousands separators, or [kDvNoValue] when unknown.
  static String _grouped(int? value) {
    if (value == null) return kDvNoValue;
    final String digits = value.abs().toString();
    final StringBuffer out = StringBuffer(value < 0 ? '-' : '');
    for (int i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 == 0) out.write(',');
      out.write(digits[i]);
    }
    return out.toString();
  }

  /// The KPI ribbon.
  ///
  /// Every tile used to render unconditionally: the scrobble count and tempo
  /// through a non-null model field that defaulted to `160717` and `102.4`, and
  /// two sublabels — `24.0% Share (38,572 Plays)` and
  /// `78 BPM Storm → 132 BPM Zenith` — that were literals in this file stating
  /// findings no query produced. A tile now shows an em-dash when the figure
  /// behind it is unknown, and each sublabel says where its number came from
  /// instead of asserting a second one.
  Widget _buildSummaryKpiRibbon(BuildContext context, {required bool isWide}) {
    final SummaryStatsModel s = _dashboard.summaryStats;
    final WeatherAffinityModel? topAffinity =
        _dashboard.weatherAffinityBreakdown.isNotEmpty
            ? _dashboard.weatherAffinityBreakdown.first
            : null;

    final List<Widget> kpis = <Widget>[
      _buildKpiTile(
        icon: Icons.library_music_outlined,
        label: 'TOTAL SCROBBLES ANALYZED',
        value: _grouped(s.totalScrobblesAnalyzed),
        sublabel: s.totalScrobblesAnalyzed == null
            ? 'No scrobbles synced'
            : 'Your synced almanac',
        accent: BgPalette.sky600,
      ),
      _buildKpiTile(
        icon: Icons.speed,
        label: 'WEIGHTED AVG TEMPO',
        value: s.avgBpm == null ? kDvNoValue : '${s.avgBpm!.toStringAsFixed(1)} BPM',
        sublabel: s.avgBpm == null
            ? 'No tempo recorded'
            : 'Play-weighted across the catalog',
        accent: BgPalette.gold600,
      ),
      _buildKpiTile(
        icon: Icons.water_drop_outlined,
        label: 'DOMINANT WEATHER AFFINITY',
        value: topAffinity?.themeName.toUpperCase() ?? kDvNoValue,
        sublabel: topAffinity == null
            ? 'No weather breakdown'
            : '${topAffinity.percentage.toStringAsFixed(1)}% share '
                '(${_grouped(topAffinity.scrobbleCount)} plays)',
        accent: BgPalette.sky700,
      ),
      _buildKpiTile(
        icon: Icons.compass_calibration_outlined,
        label: 'PRESSURE SENSITIVITY INDEX',
        value: s.pressureSensitivityIndex == null
            ? kDvNoValue
            : '${(s.pressureSensitivityIndex! * 100).toInt()}% CORR',
        // Always the absent branch today: no pressure reading is recorded
        // against a play, so nothing correlates it with tempo. It used to
        // read "84% CORR · High Barometric Mood Shift".
        sublabel: s.pressureSensitivityIndex == null
            ? 'No pressure recorded per play'
            : 'Barometric shift vs tempo',
        accent: BgPalette.ok,
      ),
    ];

    if (isWide) {
      return Row(
        children: kpis
            .map((Widget w) => Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: w,
                  ),
                ))
            .toList(),
      );
    }
    return Column(
      children: kpis
          .map((Widget w) => Padding(
                padding: const EdgeInsets.only(bottom: BgSpace.sm),
                child: w,
              ))
          .toList(),
    );
  }

  Widget _buildKpiTile({
    required IconData icon,
    required String label,
    required String value,
    required String sublabel,
    required Color accent,
  }) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BgSpace.br,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Row(
        children: <Widget>[
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.12),
              borderRadius: BgSpace.brSm,
            ),
            child: Icon(icon, color: accent, size: 22),
          ),
          const SizedBox(width: BgSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  label,
                  style: const TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                    color: BgPalette.slate500,
                    letterSpacing: 0.6,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  value,
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    color: colors.onSurface,
                  ),
                ),
                Text(
                  sublabel,
                  style: const TextStyle(
                    fontSize: 11,
                    color: BgPalette.slate500,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ==========================================================================
  // Card 1: Barometric Pressure (hPa) vs Sonic BPM & Energy Chart Card
  // ==========================================================================

  Widget _buildPressureVsBpmCard(BuildContext context, {required bool isHighlighted}) {
    final List<PressureVsBpmModel> points = _dashboard.pressureVsBpm;

    // Empty is the normal state of this card: no barometric reading is
    // recorded against a play anywhere in the system, so an hPa axis has
    // nothing to plot. The backend used to fill it from a table of 18 invented
    // tuples, and when `points` was somehow still empty this method reached for
    // a nineteenth (992.4 hPa, 78 BPM, Massive Attack — Teardrop) so the
    // readout below would have something confident to say.
    if (points.isEmpty) {
      return _buildCardShell(
        context: context,
        isHighlighted: isHighlighted,
        title: 'BAROMETRIC PRESSURE (hPa) vs SONIC BPM',
        subtitle: 'Tempo against the pressure observed when you played it',
        icon: Icons.speed_outlined,
        child: widget.isLoading
            ? _buildChartSkeleton()
            : _buildChartEmptyState(
                icon: Icons.compass_calibration_outlined,
                headline: 'No pressure readings on your plays',
                reason: 'Your scrobbles record what you played and when, but '
                    'not the barometric pressure at the time — so there is '
                    'nothing to plot tempo against.',
              ),
      );
    }

    final PressureVsBpmModel selectedPoint =
        (_selectedPressureIndex != null && _selectedPressureIndex! < points.length)
            ? points[_selectedPressureIndex!]
            : points.first;

    return _buildCardShell(
      context: context,
      isHighlighted: isHighlighted,
      title: 'BAROMETRIC PRESSURE (hPa) vs SONIC BPM & ENERGY',
      subtitle: 'Tempo against the pressure observed when you played it',
      icon: Icons.speed_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // CustomPaint Barometric Scatter & Trend Curve wrapped in RepaintBoundary
          RepaintBoundary(
            child: SizedBox(
              height: 210,
              width: double.infinity,
              child: GestureDetector(
                onTapDown: (TapDownDetails details) {
                  if (points.isEmpty) return;
                  final double width = context.size?.width ?? 400;
                  final int idx = ((details.localPosition.dx / width) * points.length)
                      .clamp(0, points.length - 1)
                      .toInt();
                  setState(() => _selectedPressureIndex = idx);
                },
                child: CustomPaint(
                  painter: _PressureVsBpmPainter(
                    points: points,
                    selectedIndex: _selectedPressureIndex ?? 0,
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: BgSpace.sm),

          // Interactive Inspector Pill for Selected Pressure Point
          Container(
            padding: const EdgeInsets.all(BgSpace.md),
            decoration: BoxDecoration(
              color: BgPalette.slate900,
              borderRadius: BgSpace.brSm,
              border: Border.all(color: BgPalette.slate700),
            ),
            child: Row(
              children: <Widget>[
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: selectedPoint.pressureHpa < 1005
                        ? BgPalette.sky700
                        : BgPalette.gold600,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    '${selectedPoint.pressureHpa.toStringAsFixed(1)} hPa',
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w800,
                      fontSize: 13,
                    ),
                  ),
                ),
                const SizedBox(width: BgSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        '${selectedPoint.artist} — ${selectedPoint.trackTitle}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                        ),
                      ),
                      Text(
                        'Theme: ${selectedPoint.themeId} • Energy: ${(selectedPoint.energy * 100).toInt()}%',
                        style: const TextStyle(
                          color: BgPalette.slate400,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
                Text(
                  '${selectedPoint.bpm} BPM',
                  style: const TextStyle(
                    color: BgPalette.gold300,
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: BgSpace.sm),
          // Interactive Point Selector Chips
          SizedBox(
            height: 34,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: points.length,
              separatorBuilder: (_, __) => const SizedBox(width: 6),
              itemBuilder: (BuildContext context, int idx) {
                final PressureVsBpmModel pt = points[idx];
                final bool isSel = (_selectedPressureIndex ?? 0) == idx;
                return ChoiceChip(
                  selected: isSel,
                  label: Text(
                    '${pt.pressureHpa.toInt()} hPa (${pt.bpm} BPM)',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: isSel ? FontWeight.w700 : FontWeight.w500,
                    ),
                  ),
                  onSelected: (_) => setState(() => _selectedPressureIndex = idx),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  // ==========================================================================
  // Card 2: Atmospheric Weather Affinity Breakdown Card
  // ==========================================================================

  Widget _buildWeatherAffinityCard(BuildContext context, {required bool isHighlighted}) {
    final List<WeatherAffinityModel> items = _dashboard.weatherAffinityBreakdown;
    final int totalPlays =
        items.fold<int>(0, (int sum, WeatherAffinityModel i) => sum + i.scrobbleCount);

    if (items.isEmpty) {
      return _buildCardShell(
        context: context,
        isHighlighted: isHighlighted,
        title: 'ATMOSPHERIC WEATHER AFFINITY BREAKDOWN',
        subtitle: 'How your plays divide across weather regimes',
        icon: Icons.cloud_outlined,
        child: widget.isLoading
            ? _buildChartSkeleton()
            : _buildChartEmptyState(
                icon: Icons.cloud_outlined,
                headline: 'No weather breakdown yet',
                reason: 'Sync your listening history and this splits your '
                    'plays across the weather regimes they were logged under.',
              ),
      );
    }

    return _buildCardShell(
      context: context,
      isHighlighted: isHighlighted,
      title: 'ATMOSPHERIC WEATHER AFFINITY BREAKDOWN',
      // The count is now read off the rows below, not stated. It used to read
      // "Distribution of 160,717 scrobbles across the 6 BaroGroove
      // meteorological regimes" — a hardcoded total and a hardcoded row count,
      // neither of which had to match what the card was actually showing.
      subtitle: '${_grouped(totalPlays)} plays across ${items.length} '
          'weather ${items.length == 1 ? 'regime' : 'regimes'}',
      icon: Icons.cloud_outlined,
      child: Column(
        children: items.map((WeatherAffinityModel item) {
          return Padding(
            padding: const EdgeInsets.only(bottom: BgSpace.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: <Widget>[
                    Expanded(
                      child: Text(
                        item.themeName,
                        style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                        ),
                      ),
                    ),
                    // Flexible + ellipsis: at 390 px the artist name is the
                    // part that gives way, never the percentage.
                    Flexible(
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: BgPalette.slate100,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          'Top: ${item.topArtist ?? kDvNoValue}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: BgPalette.slate700,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '${item.percentage.toStringAsFixed(1)}% (${_grouped(item.scrobbleCount)})',
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 12,
                        color: BgPalette.sky700,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Row(
                  children: <Widget>[
                    Expanded(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: LinearProgressIndicator(
                          value: (item.percentage / 30.0).clamp(0.0, 1.0),
                          minHeight: 8,
                          backgroundColor: BgPalette.slate200,
                          // A null BPM is not a slow one: fall back to the
                          // neutral bar rather than reading the absence as
                          // "under 100".
                          color: (item.avgBpm ?? 0) >= 100
                              ? BgPalette.gold600
                              : BgPalette.sky600,
                        ),
                      ),
                    ),
                    const SizedBox(width: BgSpace.sm),
                    Text(
                      item.avgBpm == null ? kDvNoValue : '${item.avgBpm} BPM',
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: BgPalette.slate600,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  // ==========================================================================
  // Card 3: 24-Hour Solar Chronology Heatmap Card
  // ==========================================================================

  Widget _buildHourlySolarHeatmapCard(BuildContext context, {required bool isHighlighted}) {
    final List<HourlySolarModel> buckets = _dashboard.hourlySolarHeatmap;

    // `buckets.first` on an empty list threw. It could not happen while the
    // model was seeded with 24 invented rows; it can now, so it is handled.
    if (buckets.isEmpty) {
      return _buildCardShell(
        context: context,
        isHighlighted: isHighlighted,
        title: '24-HOUR CHRONOLOGY',
        subtitle: 'When you listen, by hour (UTC)',
        icon: Icons.wb_twilight_outlined,
        child: widget.isLoading
            ? _buildChartSkeleton(height: 150)
            : _buildChartEmptyState(
                icon: Icons.schedule,
                headline: 'No hourly histogram yet',
                reason: 'Sync your listening history and this shows which '
                    'hours of the day you play the most.',
                height: 150,
              ),
      );
    }

    final HourlySolarModel selectedBucket = buckets.firstWhere(
      (HourlySolarModel b) => b.hour == _selectedSolarHour,
      orElse: () => buckets.first,
    );

    return _buildCardShell(
      context: context,
      isHighlighted: isHighlighted,
      title: '24-HOUR CHRONOLOGY',
      // The histogram counts plays. It does not carry which tracks they were,
      // so there is no tempo curve and no mood to name — this used to promise
      // a "BPM shift from Dawn → Solar Zenith → Blue Hour → Midnight Thermal",
      // three of which are not theme ids that exist.
      subtitle: 'Plays by hour of day (UTC), against your busiest hour',
      icon: Icons.wb_twilight_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // 24 Interactive Hourly Bars
          SizedBox(
            height: 150,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: buckets.map((HourlySolarModel b) {
                final bool isSelected = b.hour == _selectedSolarHour;
                final Color barColor = isSelected
                    ? BgPalette.gold500
                    : (b.hour >= 18 && b.hour <= 21
                        ? BgPalette.sky600
                        : BgPalette.slate400);
                return Expanded(
                  child: GestureDetector(
                    onTap: () => setState(() => _selectedSolarHour = b.hour),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 1.5),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: <Widget>[
                          Expanded(
                            child: Align(
                              alignment: Alignment.bottomCenter,
                              child: FractionallySizedBox(
                                heightFactor: b.activityScore.clamp(0.12, 1.0),
                                child: Container(
                                  decoration: BoxDecoration(
                                    color: barColor,
                                    borderRadius: const BorderRadius.vertical(
                                      top: Radius.circular(3),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            b.hour.toString().padLeft(2, '0'),
                            style: TextStyle(
                              fontSize: 9,
                              fontWeight:
                                  isSelected ? FontWeight.w800 : FontWeight.w500,
                              color: isSelected
                                  ? BgPalette.gold600
                                  : BgPalette.slate500,
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

          const SizedBox(height: BgSpace.md),

          // Selected Hour Detail Box
          Container(
            padding: const EdgeInsets.all(BgSpace.md),
            decoration: BoxDecoration(
              color: BgPalette.slate900,
              borderRadius: BgSpace.brSm,
              border: Border.all(color: BgPalette.slate700),
            ),
            child: Row(
              children: <Widget>[
                const Icon(Icons.schedule, color: BgPalette.gold300, size: 22),
                const SizedBox(width: BgSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        selectedBucket.label,
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.w700,
                          fontSize: 13,
                        ),
                      ),
                      Text(
                        // Was `Dominant Mood: ${...}`, off a field that
                        // defaulted to 'Nocturnal Dub'. The histogram holds
                        // counts, so the count is what this says.
                        '${_grouped(selectedBucket.scrobbleCount)} plays',
                        style: const TextStyle(
                          color: BgPalette.slate300,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: <Widget>[
                    Text(
                      // Was `${selectedBucket.avgBpm} BPM`, off a field that
                      // defaulted to 96. Nothing records the tempo of the
                      // plays in an hour bucket.
                      selectedBucket.avgBpm == null
                          ? kDvNoValue
                          : '${selectedBucket.avgBpm} BPM',
                      style: const TextStyle(
                        color: BgPalette.gold300,
                        fontWeight: FontWeight.w800,
                        fontSize: 14,
                      ),
                    ),
                    Text(
                      'Activity: ${(selectedBucket.activityScore * 100).toInt()}%',
                      style: const TextStyle(
                        color: BgPalette.sky200,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ==========================================================================
  // Card 4: Decade Sonic DNA Matrix Card
  // ==========================================================================

  Widget _buildDecadeSonicDnaCard(BuildContext context, {required bool isHighlighted}) {
    final List<DecadeSonicDnaModel> decades = _dashboard.decadeSonicDna;

    // Empty is the normal state of this card: no release year is recorded for
    // any track, so the catalog cannot be split by decade. The title used to
    // name the range it had invented, "(1970s – 2020s)", and the subtitle
    // asserted three findings.
    if (decades.isEmpty) {
      return _buildCardShell(
        context: context,
        isHighlighted: isHighlighted,
        title: 'DECADE SONIC DNA MATRIX',
        subtitle: 'Your catalog by the era the music comes from',
        icon: Icons.album_outlined,
        child: widget.isLoading
            ? _buildChartSkeleton()
            : _buildChartEmptyState(
                icon: Icons.album_outlined,
                headline: 'No release years in your catalog',
                reason: 'Your scrobbles record when you played a track, not '
                    'when it came out, so there is no era to break down.',
              ),
      );
    }

    // Largest share, read off the data. Was `d.decade == '1990s'` — a literal
    // that only lined up because the rows below it were invented too.
    final double peakShare = decades
        .map((DecadeSonicDnaModel d) => d.percentage)
        .reduce((double a, double b) => a > b ? a : b);

    return _buildCardShell(
      context: context,
      isHighlighted: isHighlighted,
      title: 'DECADE SONIC DNA MATRIX',
      subtitle: 'Your catalog by the era the music comes from',
      icon: Icons.album_outlined,
      child: Column(
        children: decades.map((DecadeSonicDnaModel d) {
          final bool isPeak = d.percentage == peakShare;
          return Container(
            margin: const EdgeInsets.only(bottom: BgSpace.md),
            padding: const EdgeInsets.all(BgSpace.md),
            decoration: BoxDecoration(
              color: isPeak
                  ? BgPalette.gold50.withValues(alpha: 0.65)
                  : BgPalette.slate50,
              borderRadius: BgSpace.brSm,
              border: Border.all(
                color: isPeak ? BgPalette.gold500 : BgPalette.slate200,
                width: isPeak ? 1.5 : 1.0,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: <Widget>[
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        Text(
                          d.decade,
                          style: const TextStyle(
                            fontWeight: FontWeight.w800,
                            fontSize: 15,
                            color: BgPalette.slate900,
                          ),
                        ),
                        if (isPeak) ...<Widget>[
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 6,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: BgPalette.gold600,
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: const Text(
                              'PEAK ERA',
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 9,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                    // Gives way before the decade label does.
                    Flexible(
                      child: Padding(
                        padding: const EdgeInsets.only(left: BgSpace.sm),
                        child: Text(
                          '${d.percentage.toStringAsFixed(1)}% • ${d.trackCount} plays',
                          textAlign: TextAlign.right,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            fontSize: 12,
                            color: BgPalette.slate700,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  d.vibeSummary,
                  style: const TextStyle(
                    fontSize: 12,
                    color: BgPalette.slate600,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: d.signatureArtists.map((String artist) {
                    return Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 3,
                      ),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: BgPalette.slate300),
                      ),
                      child: Text(
                        artist,
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: BgPalette.slate800,
                        ),
                      ),
                    );
                  }).toList(),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  // ==========================================================================
  // Reusable Card Shell with Highlight Border Support
  // ==========================================================================

  /// A shaped loading block the size of the chart it stands in for.
  ///
  /// §2 rule 3: loading is rung 0 and shaped. No spinner, and — the point of
  /// this whole pass — no plausible chart standing in while the real one loads.
  Widget _buildChartSkeleton({double height = 210}) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    return SizedBox(
      height: height,
      width: double.infinity,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: colors.surfaceContainerHighest.withValues(alpha: 0.45),
          borderRadius: BgSpace.brSm,
        ),
      ),
    );
  }

  /// What a card shows when the figures behind it do not exist.
  ///
  /// §2 rule 4: an empty state says what is missing and gives one action, and
  /// never shows a placeholder number. [reason] names the gap in the user's own
  /// terms — not "no data", which tells them nothing about whether to wait,
  /// sync, or stop asking.
  Widget _buildChartEmptyState({
    required IconData icon,
    required String headline,
    required String reason,
    double height = 210,
  }) {
    final ThemeData theme = Theme.of(context);
    final ColorScheme colors = theme.colorScheme;
    return SizedBox(
      height: height,
      width: double.infinity,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: BgSpace.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Icon(icon, size: 22, color: colors.onSurfaceVariant),
              const SizedBox(height: BgSpace.sm),
              Text(
                headline,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium
                    ?.copyWith(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: BgSpace.xs),
              Text(
                reason,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: colors.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCardShell({
    required BuildContext context,
    required bool isHighlighted,
    required String title,
    required String subtitle,
    required IconData icon,
    required Widget child,
  }) {
    final ColorScheme colors = Theme.of(context).colorScheme;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      padding: const EdgeInsets.all(BgSpace.lg),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BgSpace.br,
        border: Border.all(
          color: isHighlighted ? BgPalette.gold500 : colors.outlineVariant,
          width: isHighlighted ? 2.2 : 1.0,
        ),
        boxShadow: isHighlighted
            ? <BoxShadow>[
                BoxShadow(
                  color: BgPalette.gold500.withValues(alpha: 0.22),
                  blurRadius: 18,
                  spreadRadius: 2,
                ),
              ]
            : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(icon, color: BgPalette.sky600, size: 20),
              const SizedBox(width: BgSpace.sm),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.6,
                  ),
                ),
              ),
              if (isHighlighted)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: BgPalette.gold600,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Icon(Icons.auto_awesome, size: 12, color: Colors.white),
                      SizedBox(width: 4),
                      Text(
                        'GEMINI LIVE FOCUS',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 9,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: const TextStyle(
              fontSize: 12,
              color: BgPalette.slate500,
            ),
          ),
          const SizedBox(height: BgSpace.lg),
          child,
        ],
      ),
    );
  }
}

// ============================================================================
// CustomPainter for Barometric Pressure vs BPM & Energy Scatter/Curve
// ============================================================================

class _PressureVsBpmPainter extends CustomPainter {
  _PressureVsBpmPainter({
    required this.points,
    required this.selectedIndex,
  });

  final List<PressureVsBpmModel> points;
  final int selectedIndex;

  @override
  void paint(Canvas canvas, Size size) {
    if (points.isEmpty) return;

    final Paint gridPaint = Paint()
      ..color = BgPalette.slate200
      ..strokeWidth = 1.0;

    // Draw horizontal reference grid lines
    for (int i = 0; i <= 4; i++) {
      final double y = size.height * (i / 4);
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    // Draw 1005 hPa storm threshold vertical divider
    final double thresholdX = size.width * ((1005.0 - 990.0) / (1032.0 - 990.0));
    final Paint thresholdPaint = Paint()
      ..color = BgPalette.sky500.withValues(alpha: 0.35)
      ..strokeWidth = 1.5;
    canvas.drawLine(
      Offset(thresholdX, 0),
      Offset(thresholdX, size.height),
      thresholdPaint,
    );

    final Path curvePath = Path();
    final List<Offset> coords = <Offset>[];

    for (int i = 0; i < points.length; i++) {
      final PressureVsBpmModel p = points[i];
      final double normX = ((p.pressureHpa - 990.0) / (1032.0 - 990.0)).clamp(0.04, 0.96);
      final double normY = 1.0 - ((p.bpm - 72.0) / (138.0 - 72.0)).clamp(0.08, 0.92);
      final Offset pt = Offset(normX * size.width, normY * size.height);
      coords.add(pt);
      if (i == 0) {
        curvePath.moveTo(pt.dx, pt.dy);
      } else {
        curvePath.lineTo(pt.dx, pt.dy);
      }
    }

    // Draw connecting trend line
    final Paint linePaint = Paint()
      ..color = BgPalette.sky600
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.5;
    canvas.drawPath(curvePath, linePaint);

    // Draw scatter points
    for (int i = 0; i < coords.length; i++) {
      final Offset pt = coords[i];
      final bool isSelected = i == selectedIndex;
      final PressureVsBpmModel dataPt = points[i];

      final Paint circlePaint = Paint()
        ..color = isSelected
            ? BgPalette.gold500
            : (dataPt.pressureHpa < 1005.0 ? BgPalette.sky700 : BgPalette.sky500);

      canvas.drawCircle(pt, isSelected ? 7.5 : 4.5, circlePaint);

      if (isSelected) {
        final Paint haloPaint = Paint()
          ..color = BgPalette.gold500.withValues(alpha: 0.3)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 4.0;
        canvas.drawCircle(pt, 11.0, haloPaint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _PressureVsBpmPainter oldDelegate) {
    return oldDelegate.selectedIndex != selectedIndex ||
        oldDelegate.points != points;
  }
}
