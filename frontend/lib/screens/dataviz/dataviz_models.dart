// Data Viz — JSON models for the standing dashboard and the conversational
// BigQuery Data QnA agent.
//
// Split out of the former 2127-line `dataviz_screen.dart` (UX_IA_SPEC.md §3.4).
// Pure data: no widgets, no theming, no I/O.

// ============================================================================
// Self-contained Data Viz Telemetry & QnA JSON Models
// ============================================================================

/// What a Data Viz figure shows when the number behind it is not known.
///
/// `UX_IA_SPEC.md` §2 rule 4: empty states are honest and never show a
/// placeholder number. Same em-dash the Almanac KPI strip uses, so a reader can
/// tell a missing figure from a real one at a glance anywhere in the app.
const String kDvNoValue = '—';

class SummaryStatsModel {
  const SummaryStatsModel({
    this.totalScrobblesAnalyzed,
    this.avgBpm,
    this.dominantWeatherTheme,
    this.dominantGenre,
    this.pressureSensitivityIndex,
  });

  /// Absent fields stay absent.
  ///
  /// These used to default to `160717` scrobbles, `102.4` BPM, `'petrichor'`,
  /// `'chanson-francaise & trip-hop'` and a `0.84` "pressure sensitivity
  /// index" — so a response that omitted a field, or a backend that had not
  /// measured it, produced a KPI ribbon of confident numbers nobody counted.
  factory SummaryStatsModel.fromJson(Map<String, dynamic> json) {
    return SummaryStatsModel(
      totalScrobblesAnalyzed: (json['total_scrobbles_analyzed'] as num?)?.toInt(),
      avgBpm: (json['avg_bpm'] as num?)?.toDouble(),
      dominantWeatherTheme: (json['dominant_weather_theme'] as String?),
      dominantGenre: (json['dominant_genre'] as String?),
      pressureSensitivityIndex: (json['pressure_sensitivity_index'] as num?)?.toDouble(),
    );
  }

  static const SummaryStatsModel empty = SummaryStatsModel();

  final int? totalScrobblesAnalyzed;
  final double? avgBpm;
  final String? dominantWeatherTheme;
  final String? dominantGenre;
  final double? pressureSensitivityIndex;
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

  /// Structural zeroes only.
  ///
  /// A row the backend sent is a row it measured, so a missing field here is a
  /// malformed payload, not an unknown value — and `0` reads as broken rather
  /// than as a reading. The previous defaults (`1013.0` hPa, `100` BPM,
  /// `'Teardrop'` by `'Massive Attack'`) each read as a real observation.
  factory PressureVsBpmModel.fromJson(Map<String, dynamic> json) {
    return PressureVsBpmModel(
      pressureHpa: (json['pressure_hpa'] as num?)?.toDouble() ?? 0.0,
      bpm: (json['bpm'] as num?)?.toInt() ?? 0,
      energy: (json['energy'] as num?)?.toDouble() ?? 0.0,
      trackTitle: (json['track_title'] as String?) ?? '',
      artist: (json['artist'] as String?) ?? '',
      themeId: (json['theme_id'] as String?) ?? '',
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
    this.avgBpm,
    this.topArtist,
  });

  /// `avg_bpm` and `top_artist` are nullable on the wire: the backend joins
  /// them in from the track catalog and leaves them null for a theme it holds
  /// no tracks for. They are rendered as [kDvNoValue], not as a guess.
  factory WeatherAffinityModel.fromJson(Map<String, dynamic> json) {
    return WeatherAffinityModel(
      themeId: (json['theme_id'] as String?) ?? '',
      themeName: (json['theme_name'] as String?) ?? '',
      scrobbleCount: (json['scrobble_count'] as num?)?.toInt() ?? 0,
      percentage: (json['percentage'] as num?)?.toDouble() ?? 0.0,
      avgBpm: (json['avg_bpm'] as num?)?.toInt(),
      topArtist: (json['top_artist'] as String?),
    );
  }

  final String themeId;
  final String themeName;
  final int scrobbleCount;
  final double percentage;
  final int? avgBpm;
  final String? topArtist;
}

class HourlySolarModel {
  const HourlySolarModel({
    required this.hour,
    required this.label,
    required this.activityScore,
    required this.scrobbleCount,
    this.avgBpm,
    this.dominantMood,
  });

  /// `avg_bpm` and `dominant_mood` are always null: the corpus histogram counts
  /// plays per hour and does not carry which tracks they were, so there is no
  /// tempo to average and no mood to name. They used to default to `96` BPM and
  /// `'Nocturnal Dub'`.
  factory HourlySolarModel.fromJson(Map<String, dynamic> json) {
    return HourlySolarModel(
      hour: (json['hour'] as num?)?.toInt() ?? 0,
      label: (json['label'] as String?) ?? '',
      activityScore: (json['activity_score'] as num?)?.toDouble() ?? 0.0,
      scrobbleCount: (json['scrobble_count'] as num?)?.toInt() ?? 0,
      avgBpm: (json['avg_bpm'] as num?)?.toInt(),
      dominantMood: (json['dominant_mood'] as String?),
    );
  }

  final int hour;
  final String label;
  final double activityScore;
  final int scrobbleCount;
  final int? avgBpm;
  final String? dominantMood;
}

class DecadeSonicDnaModel {
  const DecadeSonicDnaModel({
    required this.decade,
    required this.percentage,
    required this.trackCount,
    required this.signatureArtists,
    required this.vibeSummary,
  });

  /// Structural zeroes, for the reason given on [PressureVsBpmModel.fromJson].
  /// These used to default to the `'1990s'` decade at `20.0%` and `30000`
  /// tracks.
  factory DecadeSonicDnaModel.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawArtists = (json['signature_artists'] as List<dynamic>?) ?? const <dynamic>[];
    return DecadeSonicDnaModel(
      decade: (json['decade'] as String?) ?? '',
      percentage: (json['percentage'] as num?)?.toDouble() ?? 0.0,
      trackCount: (json['track_count'] as num?)?.toInt() ?? 0,
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

  bool get hasAnyData =>
      pressureVsBpm.isNotEmpty ||
      weatherAffinityBreakdown.isNotEmpty ||
      hourlySolarHeatmap.isNotEmpty ||
      decadeSonicDna.isNotEmpty ||
      summaryStats.totalScrobblesAnalyzed != null;

  /// Nothing measured yet. The screen's state before the first response lands,
  /// and the state it returns to when a load fails.
  ///
  /// This replaces `fallback()`, which was ~90 lines of invented analytics —
  /// 160,717 scrobbles, 102.4 BPM, an 18-point pressure scatter, a six-row
  /// weather breakdown ("High Pressure Clarity — 20,893 scrobbles"), 24 hourly
  /// rows and six decades. It was not dead code: it was this field's
  /// initialiser, so it is what every user saw before any real data arrived and
  /// what they kept seeing if the fetch failed. It also carried four theme ids
  /// that no longer exist, one of them retired with no successor.
  static const DataVizDashboardModel empty = DataVizDashboardModel(
    summaryStats: SummaryStatsModel.empty,
    pressureVsBpm: <PressureVsBpmModel>[],
    weatherAffinityBreakdown: <WeatherAffinityModel>[],
    hourlySolarHeatmap: <HourlySolarModel>[],
    decadeSonicDna: <DecadeSonicDnaModel>[],
  );
}

class MatchingScrobbleModel {
  const MatchingScrobbleModel({
    required this.id,
    required this.artist,
    required this.track,
    required this.album,
  });

  /// A track the agent cited. Missing fields stay empty rather than becoming
  /// `Massive Attack — Teardrop (Mezzanine)`, which is a real record and read
  /// as one: the agent would appear to have cited a track it never returned.
  factory MatchingScrobbleModel.fromJson(Map<String, dynamic> json) {
    return MatchingScrobbleModel(
      id: (json['id'] as String?) ?? '',
      artist: (json['artist'] as String?) ?? '',
      track: (json['track'] as String?) ?? (json['title'] as String?) ?? '',
      album: (json['album'] as String?) ?? '',
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
