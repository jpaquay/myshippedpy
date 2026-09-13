// Data Viz — JSON models for the standing dashboard and the conversational
// BigQuery Data QnA agent.
//
// Split out of the former 2127-line `dataviz_screen.dart` (UX_IA_SPEC.md §3.4).
// Pure data: no widgets, no theming, no I/O.

// ============================================================================
// Self-contained Data Viz Telemetry & QnA JSON Models
// ============================================================================

class SummaryStatsModel {
  const SummaryStatsModel({
    required this.totalScrobblesAnalyzed,
    required this.avgBpm,
    required this.dominantWeatherTheme,
    required this.dominantGenre,
    required this.pressureSensitivityIndex,
  });

  factory SummaryStatsModel.fromJson(Map<String, dynamic> json) {
    return SummaryStatsModel(
      totalScrobblesAnalyzed: (json['total_scrobbles_analyzed'] as num?)?.toInt() ?? 160717,
      avgBpm: (json['avg_bpm'] as num?)?.toDouble() ?? 102.4,
      dominantWeatherTheme: (json['dominant_weather_theme'] as String?) ?? 'petrichor',
      dominantGenre: (json['dominant_genre'] as String?) ?? 'chanson-francaise & trip-hop',
      pressureSensitivityIndex:
          (json['pressure_sensitivity_index'] as num?)?.toDouble() ?? 0.84,
    );
  }

  final int totalScrobblesAnalyzed;
  final double avgBpm;
  final String dominantWeatherTheme;
  final String dominantGenre;
  final double pressureSensitivityIndex;
}

class PressureVsBpmModel {
  const PressureVsBpmModel({
    required this.pressureHpa,
    required this.bpm,
    required this.energy,
    required this.trackTitle,
    required this.artist,
    required this.themeId,
  });

  factory PressureVsBpmModel.fromJson(Map<String, dynamic> json) {
    return PressureVsBpmModel(
      pressureHpa: (json['pressure_hpa'] as num?)?.toDouble() ?? 1013.0,
      bpm: (json['bpm'] as num?)?.toInt() ?? 100,
      energy: (json['energy'] as num?)?.toDouble() ?? 0.5,
      trackTitle: (json['track_title'] as String?) ?? 'Teardrop',
      artist: (json['artist'] as String?) ?? 'Massive Attack',
      themeId: (json['theme_id'] as String?) ?? 'petrichor',
    );
  }

  final double pressureHpa;
  final int bpm;
  final double energy;
  final String trackTitle;
  final String artist;
  final String themeId;
}

class WeatherAffinityModel {
  const WeatherAffinityModel({
    required this.themeId,
    required this.themeName,
    required this.scrobbleCount,
    required this.percentage,
    required this.avgBpm,
    required this.topArtist,
  });

  factory WeatherAffinityModel.fromJson(Map<String, dynamic> json) {
    return WeatherAffinityModel(
      themeId: (json['theme_id'] as String?) ?? 'petrichor',
      themeName: (json['theme_name'] as String?) ?? 'Petrichor & Rain Front',
      scrobbleCount: (json['scrobble_count'] as num?)?.toInt() ?? 38572,
      percentage: (json['percentage'] as num?)?.toDouble() ?? 24.0,
      avgBpm: (json['avg_bpm'] as num?)?.toInt() ?? 96,
      topArtist: (json['top_artist'] as String?) ?? 'Georges Brassens',
    );
  }

  final String themeId;
  final String themeName;
  final int scrobbleCount;
  final double percentage;
  final int avgBpm;
  final String topArtist;
}

class HourlySolarModel {
  const HourlySolarModel({
    required this.hour,
    required this.label,
    required this.activityScore,
    required this.avgBpm,
    required this.dominantMood,
  });

  factory HourlySolarModel.fromJson(Map<String, dynamic> json) {
    return HourlySolarModel(
      hour: (json['hour'] as num?)?.toInt() ?? 0,
      label: (json['label'] as String?) ?? '00:00',
      activityScore: (json['activity_score'] as num?)?.toDouble() ?? 0.5,
      avgBpm: (json['avg_bpm'] as num?)?.toInt() ?? 96,
      dominantMood: (json['dominant_mood'] as String?) ?? 'Nocturnal Dub',
    );
  }

  final int hour;
  final String label;
  final double activityScore;
  final int avgBpm;
  final String dominantMood;
}

class DecadeSonicDnaModel {
  const DecadeSonicDnaModel({
    required this.decade,
    required this.percentage,
    required this.trackCount,
    required this.signatureArtists,
    required this.vibeSummary,
  });

  factory DecadeSonicDnaModel.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawArtists = (json['signature_artists'] as List<dynamic>?) ?? const <dynamic>[];
    return DecadeSonicDnaModel(
      decade: (json['decade'] as String?) ?? '1990s',
      percentage: (json['percentage'] as num?)?.toDouble() ?? 20.0,
      trackCount: (json['track_count'] as num?)?.toInt() ?? 30000,
      signatureArtists: rawArtists.map((dynamic e) => e.toString()).toList(),
      vibeSummary: (json['vibe_summary'] as String?) ?? '',
    );
  }

  final String decade;
  final double percentage;
  final int trackCount;
  final List<String> signatureArtists;
  final String vibeSummary;
}

class DataVizDashboardModel {
  const DataVizDashboardModel({
    required this.summaryStats,
    required this.pressureVsBpm,
    required this.weatherAffinityBreakdown,
    required this.hourlySolarHeatmap,
    required this.decadeSonicDna,
  });

  factory DataVizDashboardModel.fromJson(Map<String, dynamic> json) {
    final Map<String, dynamic> rawSummary =
        (json['summary_stats'] as Map<String, dynamic>?) ?? const <String, dynamic>{};
    final List<dynamic> rawPressure =
        (json['pressure_vs_bpm'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawAffinity =
        (json['weather_affinity_breakdown'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawHourly =
        (json['hourly_solar_heatmap'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawDecade =
        (json['decade_sonic_dna'] as List<dynamic>?) ?? const <dynamic>[];

    return DataVizDashboardModel(
      summaryStats: SummaryStatsModel.fromJson(rawSummary),
      pressureVsBpm: rawPressure
          .map((dynamic e) => PressureVsBpmModel.fromJson(e as Map<String, dynamic>))
          .toList(),
      weatherAffinityBreakdown: rawAffinity
          .map((dynamic e) => WeatherAffinityModel.fromJson(e as Map<String, dynamic>))
          .toList(),
      hourlySolarHeatmap: rawHourly
          .map((dynamic e) => HourlySolarModel.fromJson(e as Map<String, dynamic>))
          .toList(),
      decadeSonicDna: rawDecade
          .map((dynamic e) => DecadeSonicDnaModel.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }

  final SummaryStatsModel summaryStats;
  final List<PressureVsBpmModel> pressureVsBpm;
  final List<WeatherAffinityModel> weatherAffinityBreakdown;
  final List<HourlySolarModel> hourlySolarHeatmap;
  final List<DecadeSonicDnaModel> decadeSonicDna;

  static DataVizDashboardModel fallback() {
    return const DataVizDashboardModel(
      summaryStats: SummaryStatsModel(
        totalScrobblesAnalyzed: 160717,
        avgBpm: 102.4,
        dominantWeatherTheme: 'petrichor',
        dominantGenre: 'chanson-francaise & trip-hop',
        pressureSensitivityIndex: 0.84,
      ),
      pressureVsBpm: <PressureVsBpmModel>[
        PressureVsBpmModel(pressureHpa: 992.4, bpm: 78, energy: 0.34, trackTitle: 'Teardrop', artist: 'Massive Attack', themeId: 'low_pressure_front'),
        PressureVsBpmModel(pressureHpa: 994.8, bpm: 82, energy: 0.38, trackTitle: 'Roads', artist: 'Portishead', themeId: 'low_pressure_front'),
        PressureVsBpmModel(pressureHpa: 997.1, bpm: 85, energy: 0.41, trackTitle: 'Archangel', artist: 'Burial', themeId: 'low_pressure_front'),
        PressureVsBpmModel(pressureHpa: 999.5, bpm: 88, energy: 0.44, trackTitle: 'Glory Box', artist: 'Portishead', themeId: 'petrichor'),
        PressureVsBpmModel(pressureHpa: 1001.8, bpm: 91, energy: 0.47, trackTitle: 'Angel', artist: 'Massive Attack', themeId: 'petrichor'),
        PressureVsBpmModel(pressureHpa: 1003.6, bpm: 94, energy: 0.50, trackTitle: 'La Javanaise', artist: 'Serge Gainsbourg', themeId: 'petrichor'),
        PressureVsBpmModel(pressureHpa: 1005.9, bpm: 96, energy: 0.52, trackTitle: 'Que Sera', artist: 'Wax Tailor', themeId: 'blue_hour'),
        PressureVsBpmModel(pressureHpa: 1008.2, bpm: 99, energy: 0.55, trackTitle: 'La femme d\'argent', artist: 'Air', themeId: 'blue_hour'),
        PressureVsBpmModel(pressureHpa: 1010.5, bpm: 102, energy: 0.57, trackTitle: 'Les copains d\'abord', artist: 'Georges Brassens', themeId: 'blue_hour'),
        PressureVsBpmModel(pressureHpa: 1012.8, bpm: 105, energy: 0.60, trackTitle: 'I\'ve Got That Tune', artist: 'Chinese Man', themeId: 'midnight_thermal'),
        PressureVsBpmModel(pressureHpa: 1014.9, bpm: 108, energy: 0.63, trackTitle: 'Kerala', artist: 'Bonobo', themeId: 'midnight_thermal'),
        PressureVsBpmModel(pressureHpa: 1017.1, bpm: 111, energy: 0.66, trackTitle: 'L\'hymne de nos campagnes', artist: 'Tryo', themeId: 'midnight_thermal'),
        PressureVsBpmModel(pressureHpa: 1019.4, bpm: 114, energy: 0.70, trackTitle: 'Texas Sun', artist: 'Khruangbin', themeId: 'clear_high'),
        PressureVsBpmModel(pressureHpa: 1021.6, bpm: 118, energy: 0.73, trackTitle: 'Onde sensuelle', artist: '-M-', themeId: 'clear_high'),
        PressureVsBpmModel(pressureHpa: 1023.8, bpm: 121, energy: 0.76, trackTitle: 'Papaoutai', artist: 'Stromae', themeId: 'clear_high'),
        PressureVsBpmModel(pressureHpa: 1025.9, bpm: 124, energy: 0.80, trackTitle: 'Formidable', artist: 'Stromae', themeId: 'solar_zenith'),
        PressureVsBpmModel(pressureHpa: 1027.7, bpm: 128, energy: 0.84, trackTitle: 'Hallogallo', artist: 'Neu!', themeId: 'solar_zenith'),
        PressureVsBpmModel(pressureHpa: 1029.5, bpm: 132, energy: 0.88, trackTitle: 'Liquid Sunshine', artist: 'Biga*Ranx', themeId: 'solar_zenith'),
      ],
      weatherAffinityBreakdown: <WeatherAffinityModel>[
        WeatherAffinityModel(themeId: 'petrichor', themeName: 'Petrichor & Rain Front', scrobbleCount: 38572, percentage: 24.0, avgBpm: 96, topArtist: 'Georges Brassens'),
        WeatherAffinityModel(themeId: 'blue_hour', themeName: 'Blue Hour Drift', scrobbleCount: 32947, percentage: 20.5, avgBpm: 99, topArtist: 'Serge Gainsbourg'),
        WeatherAffinityModel(themeId: 'low_pressure_front', themeName: 'Low Pressure Storm Front', scrobbleCount: 26518, percentage: 16.5, avgBpm: 87, topArtist: 'Massive Attack'),
        WeatherAffinityModel(themeId: 'midnight_thermal', themeName: 'Midnight Thermal', scrobbleCount: 24108, percentage: 15.0, avgBpm: 108, topArtist: 'Chinese Man'),
        WeatherAffinityModel(themeId: 'clear_high', themeName: 'High Pressure Clarity', scrobbleCount: 20893, percentage: 13.0, avgBpm: 116, topArtist: '-M-'),
        WeatherAffinityModel(themeId: 'solar_zenith', themeName: 'Solar Zenith', scrobbleCount: 17679, percentage: 11.0, avgBpm: 124, topArtist: 'Stromae'),
      ],
      hourlySolarHeatmap: <HourlySolarModel>[
        HourlySolarModel(hour: 0, label: '00:00 • Midnight Thermal', activityScore: 0.62, avgBpm: 92, dominantMood: 'Nocturnal Dub & Deep Trip-Hop'),
        HourlySolarModel(hour: 1, label: '01:00 • Deep Night', activityScore: 0.48, avgBpm: 88, dominantMood: 'Sub-Bass & Ambient Drone'),
        HourlySolarModel(hour: 2, label: '02:00 • Astral Stillness', activityScore: 0.31, avgBpm: 84, dominantMood: 'Late-Night Vinyl & Lo-Fi Drift'),
        HourlySolarModel(hour: 3, label: '03:00 • Pre-Dawn Isobar', activityScore: 0.19, avgBpm: 82, dominantMood: 'Minimal Dub Chords'),
        HourlySolarModel(hour: 4, label: '04:00 • First Twilight', activityScore: 0.14, avgBpm: 85, dominantMood: 'Quiet Acoustic Reflections'),
        HourlySolarModel(hour: 5, label: '05:00 • Civil Dawn', activityScore: 0.22, avgBpm: 89, dominantMood: 'Dew-Point Acoustic Folk'),
        HourlySolarModel(hour: 6, label: '06:00 • Sunrise Horizon', activityScore: 0.38, avgBpm: 94, dominantMood: 'Warm Rhodes & Morning Coffee'),
        HourlySolarModel(hour: 7, label: '07:00 • Morning Ascent', activityScore: 0.54, avgBpm: 101, dominantMood: 'Chanson Française & Poetic Guitar'),
        HourlySolarModel(hour: 8, label: '08:00 • Commute Ridge', activityScore: 0.68, avgBpm: 106, dominantMood: 'Upbeat Indie & Motorik Pulse'),
        HourlySolarModel(hour: 9, label: '09:00 • Forenoon Clarity', activityScore: 0.75, avgBpm: 110, dominantMood: 'Crisp Rhythm & Analog Grooves'),
        HourlySolarModel(hour: 10, label: '10:00 • High Sun Climb', activityScore: 0.82, avgBpm: 114, dominantMood: 'Funk, Soul & Brass Hooks'),
        HourlySolarModel(hour: 11, label: '11:00 • Pre-Zenith', activityScore: 0.86, avgBpm: 117, dominantMood: 'High-Energy Grooves & Reggae'),
        HourlySolarModel(hour: 12, label: '12:00 • Solar Zenith', activityScore: 0.91, avgBpm: 122, dominantMood: 'Peak Solar Energy & Tropicalia'),
        HourlySolarModel(hour: 13, label: '13:00 • Post-Zenith Warmth', activityScore: 0.84, avgBpm: 119, dominantMood: 'Sun-Drenched Grooves & Bossa'),
        HourlySolarModel(hour: 14, label: '14:00 • Afternoon Thermal', activityScore: 0.79, avgBpm: 115, dominantMood: 'Steady Groove & Classic Rock'),
        HourlySolarModel(hour: 15, label: '15:00 • Trade Wind Breeze', activityScore: 0.76, avgBpm: 112, dominantMood: 'Roots Reggae & Dub Basslines'),
        HourlySolarModel(hour: 16, label: '16:00 • Golden Approach', activityScore: 0.83, avgBpm: 109, dominantMood: 'Warm Analog Synths & Soul'),
        HourlySolarModel(hour: 17, label: '17:00 • Golden Hour Ridge', activityScore: 0.94, avgBpm: 106, dominantMood: 'Sunset Grooves & Poetic Chanson'),
        HourlySolarModel(hour: 18, label: '18:00 • Civil Dusk', activityScore: 0.98, avgBpm: 103, dominantMood: 'Twilight Transitions & Downtempo'),
        HourlySolarModel(hour: 19, label: '19:00 • Blue Hour Drift', activityScore: 1.00, avgBpm: 99, dominantMood: 'Peak Listening • Bristol Trip-Hop'),
        HourlySolarModel(hour: 20, label: '20:00 • Nautical Twilight', activityScore: 0.92, avgBpm: 97, dominantMood: 'Atmospheric Beats & Spoken Word'),
        HourlySolarModel(hour: 21, label: '21:00 • Urban Heat Island', activityScore: 0.85, avgBpm: 96, dominantMood: 'Deep Grooves & Midnight Jazz'),
        HourlySolarModel(hour: 22, label: '22:00 • Late Evening Club', activityScore: 0.78, avgBpm: 95, dominantMood: 'Hypnotic Beats & Dub Techno'),
        HourlySolarModel(hour: 23, label: '23:00 • Pre-Midnight Drift', activityScore: 0.71, avgBpm: 93, dominantMood: 'Nocturnal Trip-Hop & Vinyl Crackle'),
      ],
      decadeSonicDna: <DecadeSonicDnaModel>[
        DecadeSonicDnaModel(
          decade: '1970s',
          percentage: 18.5,
          trackCount: 29732,
          signatureArtists: <String>['Georges Brassens', 'Serge Gainsbourg', 'Jacques Brel', 'Simon & Garfunkel'],
          vibeSummary: 'Analog warmth, poetic Chanson Française storytelling, and timeless acoustic fingerpicking.',
        ),
        DecadeSonicDnaModel(
          decade: '1980s',
          percentage: 11.0,
          trackCount: 17679,
          signatureArtists: <String>['Paolo Conte', 'Claude Nougaro', 'The Cure', 'Talking Heads'],
          vibeSummary: 'Post-punk basslines, theatrical cabaret jazz swing, and early analog synth textures.',
        ),
        DecadeSonicDnaModel(
          decade: '1990s',
          percentage: 26.5,
          trackCount: 42590,
          signatureArtists: <String>['Massive Attack', 'Portishead', 'Tricky', 'MC Solaar'],
          vibeSummary: 'The Bristol Trip-Hop golden era: brooding sub-bass, vinyl crackle, and low-pressure melancholia.',
        ),
        DecadeSonicDnaModel(
          decade: '2000s',
          percentage: 22.0,
          trackCount: 35358,
          signatureArtists: <String>['Chinese Man', 'Tryo', 'Wax Tailor', '-M-'],
          vibeSummary: 'Turntablism, sample-heavy cinematic hip-hop, festive acoustic reggae, and French touch.',
        ),
        DecadeSonicDnaModel(
          decade: '2010s',
          percentage: 14.0,
          trackCount: 22500,
          signatureArtists: <String>['Stromae', 'Bonobo', 'Dub Incorporation', 'L\'Entourloop'],
          vibeSummary: 'Electronic orchestration, global bass fusion, and high-definition club production.',
        ),
        DecadeSonicDnaModel(
          decade: '2020s',
          percentage: 8.0,
          trackCount: 12858,
          signatureArtists: <String>['Khruangbin', 'Pomme', 'Biga*Ranx', 'Fred again..'],
          vibeSummary: 'Psychedelic Thai-surf funk, intimate neo-chanson, and vapor-dub atmospheric soundscapes.',
        ),
      ],
    );
  }
}

class MatchingScrobbleModel {
  const MatchingScrobbleModel({
    required this.id,
    required this.artist,
    required this.track,
    required this.album,
  });

  factory MatchingScrobbleModel.fromJson(Map<String, dynamic> json) {
    return MatchingScrobbleModel(
      id: (json['id'] as String?) ?? 'scrobble_id',
      artist: (json['artist'] as String?) ?? 'Massive Attack',
      track: (json['track'] as String?) ?? (json['title'] as String?) ?? 'Teardrop',
      album: (json['album'] as String?) ?? 'Mezzanine',
    );
  }

  final String id;
  final String artist;
  final String track;
  final String album;
}

// ============================================================================
// Answer-card chart geometry
//
// `POST /api/dataviz/qna` carries the chart the BigQuery Data QnA agent
// synthesised for the answer (`backend/app/dataviz/engine.py`, field
// `chart_spec`). Four geometries only, exactly the set in
// docs/BIGQUERY_DATA_QNA_AGENT.md: bar, horizontal_bar, donut, line.
// ============================================================================

enum QnaChartGeometry { bar, horizontalBar, donut, line }

QnaChartGeometry _geometryFromWire(String raw) {
  switch (raw) {
    case 'horizontal_bar':
      return QnaChartGeometry.horizontalBar;
    case 'donut':
    case 'pie':
      return QnaChartGeometry.donut;
    case 'line':
      return QnaChartGeometry.line;
    default:
      return QnaChartGeometry.bar;
  }
}

class QnaChartPointModel {
  const QnaChartPointModel({
    required this.label,
    required this.value,
    required this.colorHex,
    required this.percentage,
    required this.extraLabel,
  });

  factory QnaChartPointModel.fromJson(Map<String, dynamic> json) {
    return QnaChartPointModel(
      label: (json['label'] as String?) ?? '',
      value: (json['value'] as num?)?.toDouble() ?? 0.0,
      colorHex: (json['color_hex'] as String?) ?? '',
      percentage: (json['percentage'] as num?)?.toDouble() ?? 0.0,
      extraLabel: (json['extra_label'] as String?) ?? '',
    );
  }

  final String label;
  final double value;
  final String colorHex;
  final double percentage;
  final String extraLabel;
}

class QnaChartSpecModel {
  const QnaChartSpecModel({
    required this.geometry,
    required this.title,
    required this.subtitle,
    required this.xLabel,
    required this.yLabel,
    required this.series,
  });

  factory QnaChartSpecModel.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawSeries =
        (json['series'] as List<dynamic>?) ?? const <dynamic>[];
    return QnaChartSpecModel(
      geometry: _geometryFromWire((json['chart_type'] as String?) ?? 'bar'),
      title: (json['title'] as String?) ?? '',
      subtitle: (json['subtitle'] as String?) ?? '',
      xLabel: (json['x_label'] as String?) ?? '',
      yLabel: (json['y_label'] as String?) ?? '',
      series: rawSeries
          .whereType<Map<String, dynamic>>()
          .map(QnaChartPointModel.fromJson)
          .toList(),
    );
  }

  final QnaChartGeometry geometry;
  final String title;
  final String subtitle;
  final String xLabel;
  final String yLabel;
  final List<QnaChartPointModel> series;

  /// A spec with no points is not a chart. The answer card renders its
  /// no-rows state instead of an empty axis.
  bool get hasData => series.isNotEmpty;
}

class DataVizQnAResponseModel {
  const DataVizQnAResponseModel({
    required this.answerText,
    required this.spokenSummary,
    required this.highlightSection,
    required this.keyMetricBadge,
    required this.suggestedFollowups,
    required this.matchingScrobbles,
    required this.modelUsed,
    this.generatedSql = '',
    this.chartSpec,
    this.rowCount = 0,
    this.dataEngine = '',
  });

  factory DataVizQnAResponseModel.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawFollowups =
        (json['suggested_followups'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawScrobbles =
        (json['matching_scrobbles'] as List<dynamic>?) ?? const <dynamic>[];
    final Map<String, dynamic>? rawChart =
        json['chart_spec'] as Map<String, dynamic>?;

    return DataVizQnAResponseModel(
      answerText: (json['answer_text'] as String?) ?? '',
      spokenSummary: (json['spoken_summary'] as String?) ?? '',
      highlightSection: (json['highlight_section'] as String?) ?? 'pressure_vs_bpm',
      keyMetricBadge: (json['key_metric_badge'] as String?) ?? 'Sonic Insight',
      suggestedFollowups: rawFollowups.map((dynamic e) => e.toString()).toList(),
      matchingScrobbles: rawScrobbles
          .map((dynamic e) => MatchingScrobbleModel.fromJson(e as Map<String, dynamic>))
          .toList(),
      modelUsed: (json['model_used'] as String?) ?? 'gemini-2.5-flash',
      generatedSql: (json['generated_sql'] as String?) ?? '',
      chartSpec: rawChart == null ? null : QnaChartSpecModel.fromJson(rawChart),
      rowCount: (json['row_count'] as num?)?.toInt() ?? 0,
      dataEngine: (json['data_engine'] as String?) ?? '',
    );
  }

  final String answerText;
  final String spokenSummary;
  final String highlightSection;
  final String keyMetricBadge;
  final List<String> suggestedFollowups;
  final List<MatchingScrobbleModel> matchingScrobbles;
  final String modelUsed;

  /// The SQL the agent ran. Drives the rung-1 `SOURCE QUERY` disclosure — the
  /// trust affordance UX_IA_SPEC.md §3.4 makes mandatory. Empty when the agent
  /// produced no query, in which case the disclosure is not rendered at all.
  final String generatedSql;

  /// The chart to draw beside the answer sentence. Null when the agent
  /// returned no plottable series.
  final QnaChartSpecModel? chartSpec;

  /// Rows the query returned. `0` together with a non-empty [generatedSql] is
  /// a genuine "nothing matched that", which the card renders differently
  /// from an error.
  final int rowCount;

  /// `bigquery_data_qna_v1beta` (live or disk-cached) or
  /// `local_olap_synthesizer` (offline). Shown verbatim in `SOURCE QUERY` so
  /// the user is never misled about where a number came from.
  final String dataEngine;
}
