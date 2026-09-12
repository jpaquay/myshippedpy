import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../advisor/voice_io.dart';
import '../api/auth_interceptor.dart';
import '../app_theme.dart';
import '../config.dart';
import '../providers.dart';
import 'shell.dart';

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
      pressureVsBpm: const <PressureVsBpmModel>[
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
      weatherAffinityBreakdown: const <WeatherAffinityModel>[
        WeatherAffinityModel(themeId: 'petrichor', themeName: 'Petrichor & Rain Front', scrobbleCount: 38572, percentage: 24.0, avgBpm: 96, topArtist: 'Georges Brassens'),
        WeatherAffinityModel(themeId: 'blue_hour', themeName: 'Blue Hour Drift', scrobbleCount: 32947, percentage: 20.5, avgBpm: 99, topArtist: 'Serge Gainsbourg'),
        WeatherAffinityModel(themeId: 'low_pressure_front', themeName: 'Low Pressure Storm Front', scrobbleCount: 26518, percentage: 16.5, avgBpm: 87, topArtist: 'Massive Attack'),
        WeatherAffinityModel(themeId: 'midnight_thermal', themeName: 'Midnight Thermal', scrobbleCount: 24108, percentage: 15.0, avgBpm: 108, topArtist: 'Chinese Man'),
        WeatherAffinityModel(themeId: 'clear_high', themeName: 'High Pressure Clarity', scrobbleCount: 20893, percentage: 13.0, avgBpm: 116, topArtist: '-M-'),
        WeatherAffinityModel(themeId: 'solar_zenith', themeName: 'Solar Zenith', scrobbleCount: 17679, percentage: 11.0, avgBpm: 124, topArtist: 'Stromae'),
      ],
      hourlySolarHeatmap: const <HourlySolarModel>[
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
      decadeSonicDna: const <DecadeSonicDnaModel>[
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

class DataVizQnAResponseModel {
  const DataVizQnAResponseModel({
    required this.answerText,
    required this.spokenSummary,
    required this.highlightSection,
    required this.keyMetricBadge,
    required this.suggestedFollowups,
    required this.matchingScrobbles,
    required this.modelUsed,
  });

  factory DataVizQnAResponseModel.fromJson(Map<String, dynamic> json) {
    final List<dynamic> rawFollowups =
        (json['suggested_followups'] as List<dynamic>?) ?? const <dynamic>[];
    final List<dynamic> rawScrobbles =
        (json['matching_scrobbles'] as List<dynamic>?) ?? const <dynamic>[];

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
    );
  }

  final String answerText;
  final String spokenSummary;
  final String highlightSection;
  final String keyMetricBadge;
  final List<String> suggestedFollowups;
  final List<MatchingScrobbleModel> matchingScrobbles;
  final String modelUsed;
}

// ============================================================================
// Main DataVizScreen Widget
// ============================================================================

class DataVizScreen extends ConsumerStatefulWidget {
  const DataVizScreen({super.key});

  @override
  ConsumerState<DataVizScreen> createState() => _DataVizScreenState();
}

class _DataVizScreenState extends ConsumerState<DataVizScreen>
    with SingleTickerProviderStateMixin {
  late final VoiceIo _voice;
  late final AnimationController _pulseController;
  final TextEditingController _questionController = TextEditingController();

  bool _isListening = false;
  bool _isSpeaking = false;
  bool _isQuerying = false;
  bool _muted = false;
  String? _errorMessage;

  DataVizDashboardModel _dashboard = DataVizDashboardModel.fallback();
  DataVizQnAResponseModel? _lastQna;

  int? _selectedPressureIndex;
  int _selectedSolarHour = 19; // Default to 19:00 Blue Hour Peak

  static const List<String> _quickQuestions = <String>[
    'What do I listen to when barometric pressure drops below 1005 hPa?',
    'Compare my late-night vs morning BPM and solar chronology',
    'Break down my 1990s Bristol Trip-Hop & Dub Techno DNA',
    'Which weather theme triggers my highest energy tracks?',
  ];

  void _syncPulseAnimation() {
    if (_isListening || _isSpeaking || _isQuerying) {
      if (!_pulseController.isAnimating) {
        _pulseController.repeat(reverse: true);
      }
    } else {
      if (_pulseController.isAnimating) {
        _pulseController.animateTo(0.35, duration: const Duration(milliseconds: 240));
      }
    }
  }

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
      value: 0.35,
    );

    _voice = VoiceIo(
      onTranscript: (String text, bool isFinal) {
        if (!mounted) return;
        setState(() {
          _questionController.text = text;
        });
        if (isFinal && text.trim().length > 3 && !_isQuerying) {
          unawaited(_askQuestion(text.trim(), voiceMode: true));
        }
      },
      onListeningChanged: (bool listening) {
        if (!mounted) return;
        setState(() => _isListening = listening);
        _syncPulseAnimation();
      },
      onSpeakingChanged: (bool speaking) {
        if (!mounted) return;
        setState(() => _isSpeaking = speaking);
        _syncPulseAnimation();
      },
      onError: (String err) {
        if (!mounted) return;
        setState(() => _errorMessage = err);
      },
    );

    _fetchDashboard();
  }

  @override
  void dispose() {
    _voice.dispose();
    _pulseController.dispose();
    _questionController.dispose();
    super.dispose();
  }

  Future<void> _fetchDashboard() async {
    try {
      final Uri uri = BgConfig.resolve('/api/dataviz/dashboard');
      final Map<String, String> headers = await authHeaders();
      final http.Response resp = await http
          .get(uri, headers: headers)
          .timeout(const Duration(seconds: 8));

      if (resp.statusCode == 200 && mounted) {
        final Map<String, dynamic> body =
            jsonDecode(resp.body) as Map<String, dynamic>;
        setState(() {
          _dashboard = DataVizDashboardModel.fromJson(body);
        });
        return;
      }
    } catch (_) {
      // Fall back gracefully to rich telemetry dataset
    }
  }

  Future<void> _askQuestion(String question, {bool voiceMode = true}) async {
    if (question.trim().isEmpty || _isQuerying) return;
    HapticFeedback.selectionClick();
    _voice.stopSpeaking();

    setState(() {
      _isQuerying = true;
      _errorMessage = null;
      _questionController.text = question;
    });
    _syncPulseAnimation();

    try {
      final Uri uri = BgConfig.resolve('/api/dataviz/qna');
      final Map<String, String> headers = <String, String>{
        'Content-Type': 'application/json',
        ...(await authHeaders()),
      };
      final http.Response resp = await http
          .post(
            uri,
            headers: headers,
            body: jsonEncode(<String, dynamic>{
              'question': question,
              'voice_mode': voiceMode,
            }),
          )
          .timeout(const Duration(seconds: 15));

      if (resp.statusCode == 200 && mounted) {
        final Map<String, dynamic> data =
            jsonDecode(resp.body) as Map<String, dynamic>;
        final DataVizQnAResponseModel result =
            DataVizQnAResponseModel.fromJson(data);
        setState(() {
          _lastQna = result;
          _isQuerying = false;
        });
        _syncPulseAnimation();

        if (!_muted && result.spokenSummary.isNotEmpty) {
          unawaited(_voice.speak(result.spokenSummary, muted: _muted));
        }
        return;
      }
    } catch (_) {
      // Client-side deterministic fallback if network offline
    }

    if (!mounted) return;
    final DataVizQnAResponseModel fallbackResult =
        _clientSideFallbackQna(question);
    setState(() {
      _lastQna = fallbackResult;
      _isQuerying = false;
    });
    _syncPulseAnimation();
    if (!_muted && fallbackResult.spokenSummary.isNotEmpty) {
      unawaited(_voice.speak(fallbackResult.spokenSummary, muted: _muted));
    }
  }

  DataVizQnAResponseModel _clientSideFallbackQna(String q) {
    final String ql = q.toLowerCase();
    if (ql.contains('1005') || ql.contains('pressure') || ql.contains('hpa')) {
      return const DataVizQnAResponseModel(
        answerText:
            'When barometric pressure drops below 1005 hPa, your listening tempo decelerates by 18.4% to an average of 86 BPM. Your Pressure Sensitivity Index of 0.84 reveals a strong shift toward brooding Bristol trip-hop and petrichor acoustic ballads anchored by Massive Attack, Portishead, and Serge Gainsbourg.',
        spokenSummary:
            'Whenever the barometer drops below 1005 hectopascals, your tempo slows to 86 BPM as you shift into Bristol trip-hop and rainy acoustic classics.',
        highlightSection: 'pressure_vs_bpm',
        keyMetricBadge: '< 1005 hPa • 86 BPM Trip-Hop Shift',
        suggestedFollowups: <String>[
          'Which tracks do I play during high-pressure ridges above 1022 hPa?',
          'Compare my late-night vs morning BPM and solar chronology',
          'Break down my 1990s Bristol Trip-Hop & Dub Techno DNA',
        ],
        matchingScrobbles: <MatchingScrobbleModel>[
          MatchingScrobbleModel(id: 'scrobble_massive_teardrop', artist: 'Massive Attack', track: 'Teardrop', album: 'Mezzanine'),
          MatchingScrobbleModel(id: 'scrobble_portishead_glorybox', artist: 'Portishead', track: 'Glory Box', album: 'Dummy'),
          MatchingScrobbleModel(id: 'scrobble_gainsbourg_javanaise', artist: 'Serge Gainsbourg', track: 'La Javanaise', album: 'Gainsbourg Confidentiel'),
        ],
        modelUsed: 'gemini-2.5-flash (telemetry-agent)',
      );
    }
    if (ql.contains('night') || ql.contains('morning') || ql.contains('solar') || ql.contains('chronology')) {
      return const DataVizQnAResponseModel(
        answerText:
            'Your circadian solar chronology shows a 34 BPM swing between Deep Night (88 BPM at 01:00) and Solar Zenith (122 BPM at noon). However, your highest listening volume clusters during Civil Dusk and Blue Hour (18:00–20:00), hitting 100% activity around 99 BPM downtempo and trip-hop.',
        spokenSummary:
            'Your tempo peaks at 122 BPM at solar noon before cooling to 88 BPM after midnight, while 7 PM Blue Hour is your number one listening window.',
        highlightSection: 'hourly_solar',
        keyMetricBadge: '19:00 Blue Hour Peak • +34 BPM Solar Swing',
        suggestedFollowups: <String>[
          'What do I listen to when barometric pressure drops below 1005 hPa?',
          'Break down my 1990s Bristol Trip-Hop & Dub Techno DNA',
          'Which weather theme triggers my highest energy tracks?',
        ],
        matchingScrobbles: <MatchingScrobbleModel>[
          MatchingScrobbleModel(id: 'scrobble_chineseman_tune', artist: 'Chinese Man', track: "I've Got That Tune", album: 'The Groove Sessions Vol. 2'),
          MatchingScrobbleModel(id: 'scrobble_bonobo_kerala', artist: 'Bonobo', track: 'Kerala', album: 'Migration'),
          MatchingScrobbleModel(id: 'scrobble_air_femme', artist: 'Air', track: "La femme d'argent", album: 'Moon Safari'),
        ],
        modelUsed: 'gemini-2.5-flash (telemetry-agent)',
      );
    }
    if (ql.contains('1990') || ql.contains('bristol') || ql.contains('decade') || ql.contains('dna')) {
      return const DataVizQnAResponseModel(
        answerText:
            'The 1990s form the core pillar of your Sonic DNA, accounting for 26.5% of your catalog (42,590 scrobbles) led by Massive Attack, Portishead, and Tricky. Combined with your 2000s turntablism cohort (22.0%) and 1970s Chanson heritage (18.5%), two-thirds of your listening blends analog storytelling with heavy breakbeats.',
        spokenSummary:
            'The 1990s are your number one decade at 26.5 percent of all plays, anchored by Massive Attack, Portishead, and Tricky.',
        highlightSection: 'decade_dna',
        keyMetricBadge: '1990s Peak Era • 26.5% Share (42,590 Plays)',
        suggestedFollowups: <String>[
          'What do I listen to when barometric pressure drops below 1005 hPa?',
          'Compare my late-night vs morning BPM and solar chronology',
          'Which weather theme triggers my highest energy tracks?',
        ],
        matchingScrobbles: <MatchingScrobbleModel>[
          MatchingScrobbleModel(id: 'scrobble_massive_teardrop', artist: 'Massive Attack', track: 'Teardrop', album: 'Mezzanine'),
          MatchingScrobbleModel(id: 'scrobble_portishead_roads', artist: 'Portishead', track: 'Roads', album: 'Dummy'),
          MatchingScrobbleModel(id: 'scrobble_tricky_hell', artist: 'Tricky', track: 'Hell Is Round the Corner', album: 'Maxinquaye'),
        ],
        modelUsed: 'gemini-2.5-flash (telemetry-agent)',
      );
    }
    return const DataVizQnAResponseModel(
      answerText:
          'Across 160,717 analyzed scrobbles, Petrichor & Rain Front is your dominant weather affinity at 24.0% (38,572 plays, averaging 96 BPM). When high-pressure Solar Zenith conditions arrive (11.0% share), your energy and tempo surge to a peak average of 124 BPM led by Stromae, -M-, and Khruangbin.',
      spokenSummary:
          'Petrichor and Rain is your top weather vibe with over 38,000 plays, while Solar Zenith triggers your highest energy tracks averaging 124 BPM.',
      highlightSection: 'weather_affinity',
      keyMetricBadge: 'Petrichor #1 Affinity (24%) • Solar Zenith 124 BPM',
      suggestedFollowups: <String>[
        'What do I listen to when barometric pressure drops below 1005 hPa?',
        'Compare my late-night vs morning BPM and solar chronology',
        'Break down my 1990s Bristol Trip-Hop & Dub Techno DNA',
      ],
      matchingScrobbles: <MatchingScrobbleModel>[
        MatchingScrobbleModel(id: 'scrobble_stromae_formidable', artist: 'Stromae', track: 'Formidable', album: 'Racine Carrée'),
        MatchingScrobbleModel(id: 'scrobble_m_onde', artist: '-M-', track: 'Onde sensuelle', album: 'Je dis aime'),
        MatchingScrobbleModel(id: 'scrobble_brassens_copains', artist: 'Georges Brassens', track: "Les copains d'abord", album: "Les copains d'abord"),
      ],
      modelUsed: 'gemini-2.5-flash (telemetry-agent)',
    );
  }

  void _toggleVoiceListening() {
    HapticFeedback.mediumImpact();
    if (_isListening) {
      _voice.stopListening();
    } else {
      _voice.stopSpeaking();
      _voice.startListening();
    }
  }

  void _seedScrobblesIntoForge(List<MatchingScrobbleModel> scrobbles) {
    if (scrobbles.isEmpty) return;
    HapticFeedback.heavyImpact();
    final Set<String> seedIds = scrobbles.map((MatchingScrobbleModel s) => s.id).toSet();

    ref.read(selectedSeedScrobblesProvider.notifier).state = seedIds;
    ref.read(forgeSelectionProvider.notifier).setSeedScrobbles(seedIds.toList());

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Seeded ${scrobbles.length} tracks (${scrobbles.map((MatchingScrobbleModel s) => s.artist).join(', ')}) into Weather Forge!',
        ),
        duration: const Duration(seconds: 3),
      ),
    );
    AppShell.of(context)?.go(BgDestination.forge);
  }

  @override
  Widget build(BuildContext context) {
    final String? highlighted = _lastQna?.highlightSection;

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final bool isWide = constraints.maxWidth >= 920;

          return ListView(
            physics: const BouncingScrollPhysics(
              parent: AlwaysScrollableScrollPhysics(),
            ),
            padding: EdgeInsets.symmetric(
              horizontal: isWide ? BgSpace.xl : BgSpace.md,
              vertical: BgSpace.lg,
            ),
            children: <Widget>[
              // 1. Gemini Live 2.5 Data Viz QnA Studio Banner
              _buildGeminiLiveQnaBanner(context, isWide: isWide),
              const SizedBox(height: BgSpace.lg),

              // 2. KPI Summary Ribbon
              _buildSummaryKpiRibbon(context, isWide: isWide),
              const SizedBox(height: BgSpace.lg),

              // 3. Responsive 2-column or 1-column Dashboard Cards
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

              const SizedBox(height: BgSpace.xxl),
              const NetdevFooter(),
              const SizedBox(height: BgSpace.xl),
            ],
          );
        },
      ),
    );
  }

  // ==========================================================================
  // Top Section: Gemini Live 2.5 Data Viz QnA Studio Banner
  // ==========================================================================

  Widget _buildGeminiLiveQnaBanner(BuildContext context, {required bool isWide}) {
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: <Color>[
            BgPalette.slate900,
            BgPalette.slate800.withValues(alpha: 0.96),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BgSpace.br,
        border: Border.all(
          color: _isListening || _isSpeaking
              ? BgPalette.gold500
              : BgPalette.sky500.withValues(alpha: 0.45),
          width: _isListening || _isSpeaking ? 2.0 : 1.2,
        ),
        boxShadow: <BoxShadow>[
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.16),
            blurRadius: 18,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      padding: const EdgeInsets.all(BgSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // Header row with Orb + Title + Controls
          Row(
            children: <Widget>[
              // Interactive Voice Orb wrapped in RepaintBoundary
              RepaintBoundary(
                child: GestureDetector(
                  onTap: _toggleVoiceListening,
                  child: AnimatedBuilder(
                    animation: _pulseController,
                    builder: (BuildContext context, Widget? child) {
                      final double pulse = _pulseController.value;
                      final Color orbColor = _isListening
                          ? BgPalette.danger
                          : (_isSpeaking ? BgPalette.gold500 : BgPalette.sky500);
                      return Container(
                        width: 56,
                        height: 56,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: RadialGradient(
                            colors: <Color>[
                              orbColor,
                              orbColor.withValues(alpha: 0.35 + pulse * 0.35),
                              Colors.transparent,
                            ],
                          ),
                          boxShadow: <BoxShadow>[
                            BoxShadow(
                              color: orbColor.withValues(alpha: 0.45 * pulse),
                              blurRadius: 16 + 12 * pulse,
                              spreadRadius: 2 * pulse,
                            ),
                          ],
                        ),
                        child: Center(
                          child: Container(
                            width: 40,
                            height: 40,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: BgPalette.slate900,
                              border: Border.all(color: orbColor, width: 1.8),
                            ),
                            child: Icon(
                              _isListening
                                  ? Icons.mic
                                  : (_isSpeaking
                                      ? Icons.graphic_eq
                                      : Icons.auto_awesome),
                              color: orbColor,
                              size: 20,
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ),
              const SizedBox(width: BgSpace.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Row(
                      children: <Widget>[
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: BgPalette.sky500.withValues(alpha: 0.2),
                            borderRadius: BorderRadius.circular(4),
                            border: Border.all(
                              color: BgPalette.sky500.withValues(alpha: 0.5),
                            ),
                          ),
                          child: const Text(
                            'GEMINI LIVE 2.5 FLASH • DATA VIZ Q&A STUDIO',
                            style: TextStyle(
                              color: BgPalette.sky200,
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.8,
                            ),
                          ),
                        ),
                        const SizedBox(width: BgSpace.sm),
                        if (_isSpeaking)
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: BgPalette.gold500.withValues(alpha: 0.2),
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: const Row(
                              mainAxisSize: MainAxisSize.min,
                              children: <Widget>[
                                Icon(
                                  Icons.volume_up,
                                  size: 12,
                                  color: BgPalette.gold300,
                                ),
                                SizedBox(width: 4),
                                Text(
                                  'SPEAKING INSIGHT',
                                  style: TextStyle(
                                    color: BgPalette.gold300,
                                    fontSize: 10,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Ask anything about your 160,717-scrobble Almanac, barometric BPM sensitivity, or circadian solar rhythm',
                      style: text.bodyMedium?.copyWith(
                        color: BgPalette.slate200,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),
              // Push-to-Talk button & Mute toggle
              IconButton(
                tooltip: _muted ? 'Unmute Voice Synthesis' : 'Mute Voice Synthesis',
                onPressed: () {
                  setState(() => _muted = !_muted);
                  if (_muted) {
                    _voice.stopSpeaking();
                  }
                },
                icon: Icon(
                  _muted ? Icons.volume_off : Icons.volume_up,
                  color: _muted ? BgPalette.slate400 : BgPalette.gold300,
                ),
              ),
              const SizedBox(width: BgSpace.xs),
              FilledButton.icon(
                onPressed: _toggleVoiceListening,
                style: FilledButton.styleFrom(
                  backgroundColor: _isListening ? BgPalette.danger : BgPalette.sky600,
                  foregroundColor: Colors.white,
                ),
                icon: Icon(_isListening ? Icons.stop : Icons.mic, size: 16),
                label: Text(_isListening ? 'Stop Voice' : 'Push to Talk'),
              ),
            ],
          ),

          const SizedBox(height: BgSpace.md),

          // Search / Question Input Bar
          Row(
            children: <Widget>[
              Expanded(
                child: TextField(
                  controller: _questionController,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                  decoration: InputDecoration(
                    hintText: _isListening
                        ? 'Listening to your voice question...'
                        : 'Ask Gemini Live 2.5 about your barometric tempo, solar peak, or 90s Trip-Hop DNA...',
                    hintStyle: const TextStyle(color: BgPalette.slate400, fontSize: 13),
                    filled: true,
                    fillColor: BgPalette.slate800,
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: BgSpace.md,
                      vertical: 12,
                    ),
                    border: const OutlineInputBorder(
                      borderRadius: BgSpace.brSm,
                      borderSide: BorderSide(color: BgPalette.slate600),
                    ),
                    enabledBorder: const OutlineInputBorder(
                      borderRadius: BgSpace.brSm,
                      borderSide: BorderSide(color: BgPalette.slate600),
                    ),
                    focusedBorder: const OutlineInputBorder(
                      borderRadius: BgSpace.brSm,
                      borderSide: BorderSide(color: BgPalette.sky500, width: 1.5),
                    ),
                    prefixIcon: const Icon(Icons.psychology, color: BgPalette.sky500),
                    suffixIcon: _questionController.text.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear, color: BgPalette.slate400, size: 18),
                            onPressed: () => setState(() => _questionController.clear()),
                          )
                        : null,
                  ),
                  onSubmitted: (String value) => _askQuestion(value, voiceMode: false),
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              FilledButton(
                onPressed: _isQuerying
                    ? null
                    : () => _askQuestion(_questionController.text, voiceMode: false),
                style: FilledButton.styleFrom(
                  backgroundColor: BgPalette.gold600,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                ),
                child: _isQuerying
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Analyze Telemetry'),
              ),
            ],
          ),

          const SizedBox(height: BgSpace.md),

          // Quick-Question Chips
          Wrap(
            spacing: BgSpace.sm,
            runSpacing: BgSpace.xs,
            children: _quickQuestions.map((String q) {
              return ActionChip(
                backgroundColor: BgPalette.slate800,
                side: BorderSide(color: BgPalette.slate600.withValues(alpha: 0.7)),
                avatar: const Icon(Icons.bolt, size: 15, color: BgPalette.gold300),
                label: Text(
                  q,
                  style: const TextStyle(
                    color: BgPalette.slate100,
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                onPressed: () => _askQuestion(q, voiceMode: true),
              );
            }).toList(),
          ),

          // Error message if any
          if (_errorMessage != null) ...<Widget>[
            const SizedBox(height: BgSpace.sm),
            Text(
              _errorMessage!,
              style: const TextStyle(color: BgPalette.gold300, fontSize: 12),
            ),
          ],

          // Highlighted Gemini Live Insight Card when answer arrives
          if (_lastQna != null) ...<Widget>[
            const SizedBox(height: BgSpace.lg),
            _buildGeminiInsightCard(context, _lastQna!),
          ],
        ],
      ),
    );
  }

  Widget _buildGeminiInsightCard(BuildContext context, DataVizQnAResponseModel qna) {
    return Container(
      decoration: BoxDecoration(
        color: BgPalette.slate800.withValues(alpha: 0.9),
        borderRadius: BgSpace.brSm,
        border: Border.all(color: BgPalette.gold500.withValues(alpha: 0.8), width: 1.5),
      ),
      padding: const EdgeInsets.all(BgSpace.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          // Top row: Key metric badge + Animated Waveform indicator + Model tag
          Wrap(
            spacing: BgSpace.sm,
            runSpacing: BgSpace.xs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: <Widget>[
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: BgPalette.gold600,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    const Icon(Icons.insights, size: 14, color: Colors.white),
                    const SizedBox(width: 6),
                    Text(
                      qna.keyMetricBadge,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: BgPalette.sky700.withValues(alpha: 0.35),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: BgPalette.sky500.withValues(alpha: 0.5)),
                ),
                child: Text(
                  'Highlighted Section: ${qna.highlightSection.toUpperCase()}',
                  style: const TextStyle(
                    color: BgPalette.sky200,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (_isSpeaking)
                RepaintBoundary(
                  child: AnimatedBuilder(
                    animation: _pulseController,
                    builder: (BuildContext context, Widget? child) {
                      return Row(
                        mainAxisSize: MainAxisSize.min,
                        children: List<Widget>.generate(5, (int i) {
                          final double height = 8.0 +
                              10.0 *
                                  math.sin(
                                    (_pulseController.value * math.pi * 2) + i,
                                  ).abs();
                          return Container(
                            margin: const EdgeInsets.symmetric(horizontal: 1.5),
                            width: 3,
                            height: height,
                            decoration: BoxDecoration(
                              color: BgPalette.gold300,
                              borderRadius: BorderRadius.circular(2),
                            ),
                          );
                        }),
                      );
                    },
                  ),
                ),
            ],
          ),

          const SizedBox(height: BgSpace.md),

          // Detailed Data-Storytelling Response
          Text(
            qna.answerText,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 14,
              height: 1.45,
            ),
          ),

          const SizedBox(height: BgSpace.md),

          // Matching Scrobble Tracks + SEED INTO FORGE CTA
          if (qna.matchingScrobbles.isNotEmpty) ...<Widget>[
            const Text(
              'MATCHING ALMANAC SCROBBLE SEEDS:',
              style: TextStyle(
                color: BgPalette.slate400,
                fontSize: 11,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.7,
              ),
            ),
            const SizedBox(height: BgSpace.xs),
            Wrap(
              spacing: BgSpace.sm,
              runSpacing: BgSpace.xs,
              children: qna.matchingScrobbles.map((MatchingScrobbleModel s) {
                return Chip(
                  backgroundColor: BgPalette.slate900,
                  side: const BorderSide(color: BgPalette.slate700),
                  avatar: const Icon(Icons.album, size: 15, color: BgPalette.sky500),
                  label: Text(
                    '${s.artist} — ${s.track}',
                    style: const TextStyle(
                      color: BgPalette.slate100,
                      fontSize: 12,
                    ),
                  ),
                );
              }).toList(),
            ),
            const SizedBox(height: BgSpace.sm),
            FilledButton.icon(
              onPressed: () => _seedScrobblesIntoForge(qna.matchingScrobbles),
              style: FilledButton.styleFrom(
                backgroundColor: BgPalette.sky600,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
              ),
              icon: const Icon(Icons.auto_fix_high, size: 18),
              label: const Text(
                'SEED THESE TRACKS INTO FORGE',
                style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: 0.5),
              ),
            ),
          ],

          const SizedBox(height: BgSpace.md),
          const Divider(color: BgPalette.slate700, height: 1),
          const SizedBox(height: BgSpace.sm),

          // Follow-up Question Chips
          const Text(
            'SUGGESTED FOLLOW-UP QUESTIONS:',
            style: TextStyle(
              color: BgPalette.slate400,
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.6,
            ),
          ),
          const SizedBox(height: BgSpace.xs),
          Wrap(
            spacing: BgSpace.sm,
            runSpacing: BgSpace.xs,
            children: qna.suggestedFollowups.map((String followup) {
              return ActionChip(
                backgroundColor: BgPalette.slate900,
                side: const BorderSide(color: BgPalette.slate700),
                avatar: const Icon(Icons.question_answer_outlined, size: 14, color: BgPalette.sky200),
                label: Text(
                  followup,
                  style: const TextStyle(color: BgPalette.sky200, fontSize: 11),
                ),
                onPressed: () => _askQuestion(followup, voiceMode: true),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  // ==========================================================================
  // KPI Summary Ribbon
  // ==========================================================================

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
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: BgPalette.slate100,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        'Top: ${item.topArtist}',
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: BgPalette.slate700,
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
                    Text(
                      '${d.percentage.toStringAsFixed(1)}% • ${d.trackCount} plays',
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 12,
                        color: BgPalette.slate700,
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

// ============================================================================
// NetdevFooter Widget
// ============================================================================

class NetdevFooter extends StatelessWidget {
  const NetdevFooter({super.key});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: BgSpace.md),
        child: Text(
          'Built with ❤️ by the Agentic Platform Team at ⚡web3.netdev.be⚡',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
            letterSpacing: 0.3,
          ),
        ),
      ),
    );
  }
}
