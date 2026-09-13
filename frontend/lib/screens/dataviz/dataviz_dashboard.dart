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
  });

  final DataVizDashboardModel dashboard;
  final bool isExpanded;

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

  Widget _buildSummaryKpiRibbon(BuildContext context, {required bool isWide}) {
    final SummaryStatsModel s = _dashboard.summaryStats;
    final List<Widget> kpis = <Widget>[
      _buildKpiTile(
        icon: Icons.library_music_outlined,
        label: 'TOTAL SCROBBLES ANALYZED',
        value: '${s.totalScrobblesAnalyzed ~/ 1000},${(s.totalScrobblesAnalyzed % 1000).toString().padLeft(3, '0')}',
        sublabel: '15-Year BigQuery OLAP Cohort',
        accent: BgPalette.sky600,
      ),
      _buildKpiTile(
        icon: Icons.speed,
        label: 'WEIGHTED AVG TEMPO',
        value: '${s.avgBpm.toStringAsFixed(1)} BPM',
        sublabel: '78 BPM Storm → 132 BPM Zenith',
        accent: BgPalette.gold600,
      ),
      _buildKpiTile(
        icon: Icons.water_drop_outlined,
        label: 'DOMINANT WEATHER AFFINITY',
        value: s.dominantWeatherTheme.toUpperCase(),
        sublabel: '24.0% Share (38,572 Plays)',
        accent: BgPalette.sky700,
      ),
      _buildKpiTile(
        icon: Icons.compass_calibration_outlined,
        label: 'PRESSURE SENSITIVITY INDEX',
        value: '${(s.pressureSensitivityIndex * 100).toInt()}% CORR',
        sublabel: 'High Barometric Mood Shift',
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
    final PressureVsBpmModel selectedPoint =
        (_selectedPressureIndex != null && _selectedPressureIndex! < points.length)
            ? points[_selectedPressureIndex!]
            : (points.isNotEmpty ? points.first : const PressureVsBpmModel(
                pressureHpa: 992.4,
                bpm: 78,
                energy: 0.34,
                trackTitle: 'Teardrop',
                artist: 'Massive Attack',
                themeId: 'low_pressure_front',
              ));

    return _buildCardShell(
      context: context,
      isHighlighted: isHighlighted,
      title: 'BAROMETRIC PRESSURE (hPa) vs SONIC BPM & ENERGY',
      subtitle: 'Lower barometric pressure (< 1005 hPa) correlates with sub-bass Bristol trip-hop & ambient tempos',
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

    return _buildCardShell(
      context: context,
      isHighlighted: isHighlighted,
      title: 'ATMOSPHERIC WEATHER AFFINITY BREAKDOWN',
      subtitle: 'Distribution of 160,717 scrobbles across the 6 BaroGroove meteorological regimes',
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
                          'Top: ${item.topArtist}',
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
                      '${item.percentage.toStringAsFixed(1)}% (${item.scrobbleCount})',
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
                          color: item.avgBpm < 100 ? BgPalette.sky600 : BgPalette.gold600,
                        ),
                      ),
                    ),
                    const SizedBox(width: BgSpace.sm),
                    Text(
                      '${item.avgBpm} BPM',
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
    final HourlySolarModel selectedBucket =
        buckets.firstWhere((HourlySolarModel b) => b.hour == _selectedSolarHour, orElse: () => buckets.first);

    return _buildCardShell(
      context: context,
      isHighlighted: isHighlighted,
      title: '24-HOUR SOLAR CHRONOLOGY HEATMAP',
      subtitle: 'Circadian listening volume & BPM shift from Dawn → Solar Zenith → Blue Hour → Midnight Thermal',
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
                        'Dominant Mood: ${selectedBucket.dominantMood}',
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
                      '${selectedBucket.avgBpm} BPM',
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

    return _buildCardShell(
      context: context,
      isHighlighted: isHighlighted,
      title: 'DECADE SONIC DNA MATRIX (1970s – 2020s)',
      subtitle: 'Generational breakdown across 1990s Bristol Trip-Hop, 2000s Turntablism & 1970s Chanson Française',
      icon: Icons.album_outlined,
      child: Column(
        children: decades.map((DecadeSonicDnaModel d) {
          final bool isPeak = d.decade == '1990s';
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
