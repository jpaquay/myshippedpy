/// Domain models mirroring the Python contracts.
///
/// These exist for the SHELL — health, pairing status, the theme and genre
/// lists the pickers need, the demo forge. They are deliberately NOT used to
/// render domain content: that comes through A2UI as an untyped data model,
/// because the server owns the presentation. If you find yourself adding a
/// model here so a screen can lay out a playlist by hand, you are building
/// the UI twice.
///
/// Every `fromJson` is total. Backend drift produces a partially-populated
/// object with sensible defaults, not an exception on a background isolate.
library;

import '../a2ui/messages.dart' show JsonMap, asDoubleOrNull, asJsonList,
    asJsonMap, asStringList, asStringOrNull, asBoolOrNull;

// ===========================================================================
// Health
// ===========================================================================

/// `GET /api/health`
class HealthStatus {
  const HealthStatus({
    required this.status,
    required this.capabilities,
    required this.degraded,
    this.telemetry,
  });

  final String status;

  /// Feature flags the backend reports, e.g. `{"spotify": true}`.
  final Map<String, bool> capabilities;

  /// Things currently not working. Surfaced verbatim in the UI.
  final List<String> degraded;

  /// Live AI telemetry summary counters reported by `/api/health`.
  final TelemetrySummaryModel? telemetry;

  bool get ok => status == 'ok' || status == 'healthy';

  bool capability(String name) => capabilities[name] ?? false;

  static const HealthStatus unknown = HealthStatus(
    status: 'unknown',
    capabilities: <String, bool>{},
    degraded: <String>['backend unreachable'],
  );

  factory HealthStatus.fromJson(JsonMap json) {
    final JsonMap caps = asJsonMap(json['capabilities']) ?? const <String, Object?>{};
    final JsonMap? rawTelemetry = asJsonMap(json['telemetry']);
    final String status = asStringOrNull(json['status']) ??
        (asBoolOrNull(json['ok']) == true ? 'ok' : 'unknown');
    return HealthStatus(
      status: status,
      capabilities: <String, bool>{
        for (final MapEntry<String, Object?> e in caps.entries)
          e.key: asBoolOrNull(e.value) ?? false,
      },
      degraded: asStringList(json['degraded']),
      telemetry: rawTelemetry != null ? TelemetrySummaryModel.fromJson(rawTelemetry) : null,
    );
  }
}

// ===========================================================================
// Sky
// ===========================================================================

/// The nine-dimensional reading. Signed dims are [-1, 1]; the rest [0, 1].
class SkyVector {
  const SkyVector({
    required this.pressureTrend6h,
    required this.pressureNormDeviation,
    required this.tempNormDeviation,
    required this.sunElevation,
    required this.goldenHourProximity,
    required this.gustVariance,
    required this.cloudDepth,
    required this.precipIntensity,
    required this.daylightDelta,
    required this.observedAt,
    required this.stale,
    required this.notes,
  });

  final double pressureTrend6h;
  final double pressureNormDeviation;
  final double tempNormDeviation;
  final double sunElevation;
  final double goldenHourProximity;
  final double gustVariance;
  final double cloudDepth;
  final double precipIntensity;
  final double daylightDelta;
  final String? observedAt;
  final bool stale;
  final List<String> notes;

  factory SkyVector.fromJson(JsonMap json) {
    double d(String key) => asDoubleOrNull(json[key]) ?? 0;
    return SkyVector(
      pressureTrend6h: d('pressure_trend_6h'),
      pressureNormDeviation: d('pressure_norm_deviation'),
      tempNormDeviation: d('temp_norm_deviation'),
      sunElevation: d('sun_elevation'),
      goldenHourProximity: d('golden_hour_proximity'),
      gustVariance: d('gust_variance'),
      cloudDepth: d('cloud_depth'),
      precipIntensity: d('precip_intensity'),
      daylightDelta: d('daylight_delta'),
      observedAt: asStringOrNull(json['observed_at']),
      stale: asBoolOrNull(json['stale']) ?? false,
      notes: asStringList(json['notes']),
    );
  }

  JsonMap toJson() => <String, Object?>{
        'pressure_trend_6h': pressureTrend6h,
        'pressure_norm_deviation': pressureNormDeviation,
        'temp_norm_deviation': tempNormDeviation,
        'sun_elevation': sunElevation,
        'golden_hour_proximity': goldenHourProximity,
        'gust_variance': gustVariance,
        'cloud_depth': cloudDepth,
        'precip_intensity': precipIntensity,
        'daylight_delta': daylightDelta,
        'observed_at': observedAt,
        'stale': stale,
        'notes': notes,
      };
}

/// The seven-dimensional musical target the sky is mapped onto.
class SonicVector {
  const SonicVector({
    required this.valence,
    required this.energy,
    required this.tempo,
    required this.acousticness,
    required this.density,
    required this.grit,
    required this.spatiality,
  });

  final double valence;
  final double energy;
  final double tempo;
  final double acousticness;
  final double density;
  final double grit;
  final double spatiality;

  factory SonicVector.fromJson(JsonMap json) {
    double d(String key) => asDoubleOrNull(json[key]) ?? 0;
    return SonicVector(
      valence: d('valence'),
      energy: d('energy'),
      tempo: d('tempo'),
      acousticness: d('acousticness'),
      density: d('density'),
      grit: d('grit'),
      spatiality: d('spatiality'),
    );
  }

  Map<String, double> get asMap => <String, double>{
        'valence': valence,
        'energy': energy,
        'tempo': tempo,
        'acousticness': acousticness,
        'density': density,
        'grit': grit,
        'spatiality': spatiality,
      };
}

/// A named scenario from `GET /api/sky/scenarios` — canned skies for demos
/// and for testing the forge without waiting for real weather.
class SkyScenario {
  const SkyScenario({required this.id, required this.name, this.description});

  final String id;
  final String name;
  final String? description;

  factory SkyScenario.fromJson(JsonMap json) => SkyScenario(
        id: asStringOrNull(json['id']) ?? '',
        name: asStringOrNull(json['name']) ??
            asStringOrNull(json['id']) ??
            'Scenario',
        description: asStringOrNull(json['description']),
      );
}

/// Curated World Street-Art Geo-Cache landmark from `GET /api/sky/geocaches`.
class StreetArtGeoCache {
  const StreetArtGeoCache({
    required this.id,
    required this.name,
    required this.city,
    required this.country,
    required this.label,
    required this.lat,
    required this.lon,
    required this.tzOffsetHours,
    required this.localTime,
    required this.dayPeriod,
    required this.artistHighlight,
    required this.description,
    required this.vibeTags,
  });

  final String id;
  final String name;
  final String city;
  final String country;
  final String label;
  final double lat;
  final double lon;
  final double tzOffsetHours;
  final String localTime;
  final String dayPeriod;
  final String artistHighlight;
  final String description;
  final List<String> vibeTags;

  factory StreetArtGeoCache.fromJson(JsonMap json) => StreetArtGeoCache(
        id: asStringOrNull(json['id']) ?? '',
        name: asStringOrNull(json['name']) ?? 'Street Art Landmark',
        city: asStringOrNull(json['city']) ?? '',
        country: asStringOrNull(json['country']) ?? '',
        label: asStringOrNull(json['label']) ??
            asStringOrNull(json['name']) ??
            '',
        lat: asDoubleOrNull(json['lat']) ?? 50.8503,
        lon: asDoubleOrNull(json['lon']) ?? 4.3517,
        tzOffsetHours: asDoubleOrNull(json['tz_offset_hours']) ?? 1.0,
        localTime: asStringOrNull(json['local_time']) ?? '14:00 (UTC+1)',
        dayPeriod: asStringOrNull(json['day_period']) ?? 'afternoon',
        artistHighlight: asStringOrNull(json['artist_highlight']) ?? '',
        description: asStringOrNull(json['description']) ?? '',
        vibeTags: asStringList(json['vibe_tags']),
      );
}

// ===========================================================================
// Themes and genres
// ===========================================================================

/// One of the eight sky themes.
class SkyTheme {
  const SkyTheme({
    required this.id,
    required this.name,
    required this.tagline,
    required this.description,
    required this.bias,
    required this.biasWeight,
    required this.seedTags,
    required this.avoidTags,
    required this.palette,
    required this.voice,
    required this.affinity,
  });

  final String id;
  final String name;
  final String tagline;
  final String description;
  final String bias;
  final double biasWeight;
  final List<String> seedTags;
  final List<String> avoidTags;

  /// Hex strings keyed by role. Used as a tint, never as a repaint.
  final Map<String, String> palette;

  final String voice;
  final Map<String, double> affinity;

  /// The canonical eight, for ordering a picker before the network answers.
  static const List<String> canonicalIds = <String>[
    'petrichor',
    'golden_hour',
    'nordic_fog',
    'storm_front',
    'heatwave_cruise',
    'blue_hour',
    'first_frost',
    'sirocco',
  ];

  factory SkyTheme.fromJson(JsonMap json) {
    final JsonMap rawPalette =
        asJsonMap(json['palette']) ?? const <String, Object?>{};
    final JsonMap rawAffinity =
        asJsonMap(json['affinity']) ?? const <String, Object?>{};
    return SkyTheme(
      id: asStringOrNull(json['id']) ?? '',
      name: asStringOrNull(json['name']) ?? asStringOrNull(json['id']) ?? '',
      tagline: asStringOrNull(json['tagline']) ?? '',
      description: asStringOrNull(json['description']) ?? '',
      bias: asStringOrNull(json['bias']) ?? '',
      biasWeight: asDoubleOrNull(json['bias_weight']) ?? 0,
      seedTags: asStringList(json['seed_tags']),
      avoidTags: asStringList(json['avoid_tags']),
      palette: <String, String>{
        for (final MapEntry<String, Object?> e in rawPalette.entries)
          if (asStringOrNull(e.value) case final String hex) e.key: hex,
      },
      voice: asStringOrNull(json['voice']) ?? '',
      affinity: <String, double>{
        for (final MapEntry<String, Object?> e in rawAffinity.entries)
          if (asDoubleOrNull(e.value) case final double v) e.key: v,
      },
    );
  }

  /// The accent hex, if the palette declares one under any of the usual keys.
  String? get accentHex {
    for (final String key in const <String>['accent', 'primary', 'base']) {
      final String? hex = palette[key];
      if (hex != null) return hex;
    }
    return palette.values.firstOrNull;
  }
}

/// A genre expressed as an interval, not a label.
class GenreCorridorModel {
  const GenreCorridorModel({
    required this.id,
    required this.name,
    required this.tags,
    required this.anchor,
    required this.width,
    required this.description,
  });

  final String id;
  final String name;
  final List<String> tags;

  /// Centre of the corridor on the abstract genre axis, [0, 1].
  final double anchor;

  /// How far the forge may wander from the anchor, [0, 1].
  final double width;

  final String description;

  factory GenreCorridorModel.fromJson(JsonMap json) => GenreCorridorModel(
        id: asStringOrNull(json['id']) ?? '',
        name: asStringOrNull(json['name']) ?? asStringOrNull(json['id']) ?? '',
        tags: asStringList(json['tags']),
        anchor: asDoubleOrNull(json['anchor']) ?? 0.5,
        width: asDoubleOrNull(json['width']) ?? 0.2,
        description: asStringOrNull(json['description']) ?? '',
      );
}

// ===========================================================================
// Forge
// ===========================================================================

/// Body for `POST /api/forge`.
class ForgeRequest {
  const ForgeRequest({
    this.lat,
    this.lon,
    this.themeId,
    this.genreId,
    this.scenario,
    this.trackCount,
    this.geocacheId,
    this.seedScrobbles = const <String>[],
    this.customTempC,
    this.customLightPct,
    this.customColorKelvin,
    this.customPressureHpa,
    this.customTrendHpa,
    this.customTargetBpm,
  });

  final double? lat;
  final double? lon;
  final String? themeId;
  final String? genreId;

  /// Named scenario instead of live weather. Mutually exclusive with lat/lon
  /// in practice, though the backend decides.
  final String? scenario;

  final int? trackCount;
  final String? geocacheId;
  final List<String> seedScrobbles;
  final double? customTempC;
  final double? customLightPct;
  final double? customColorKelvin;
  final double? customPressureHpa;
  final double? customTrendHpa;
  final double? customTargetBpm;

  JsonMap toJson() => <String, Object?>{
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
        if (themeId != null) 'theme_id': themeId,
        if (genreId != null) 'genre_id': genreId,
        if (scenario != null) 'scenario': scenario,
        if (trackCount != null) 'track_count': trackCount,
        if (geocacheId != null) 'geocache_id': geocacheId,
        if (seedScrobbles.isNotEmpty) 'seed_scrobbles': seedScrobbles,
        if (customTempC != null) 'custom_temp_c': customTempC,
        if (customLightPct != null) 'custom_light_pct': customLightPct,
        if (customColorKelvin != null) 'custom_color_kelvin': customColorKelvin,
        if (customPressureHpa != null) 'custom_pressure_hpa': customPressureHpa,
        if (customTrendHpa != null) 'custom_trend_hpa': customTrendHpa,
        if (customTargetBpm != null) 'custom_target_bpm': customTargetBpm,
      };

  ForgeRequest copyWith({
    double? lat,
    double? lon,
    String? themeId,
    String? genreId,
    String? scenario,
    int? trackCount,
    String? geocacheId,
    List<String>? seedScrobbles,
    double? customTempC,
    double? customLightPct,
    double? customColorKelvin,
    double? customPressureHpa,
    double? customTrendHpa,
    double? customTargetBpm,
  }) =>
      ForgeRequest(
        lat: lat ?? this.lat,
        lon: lon ?? this.lon,
        themeId: themeId ?? this.themeId,
        genreId: genreId ?? this.genreId,
        scenario: scenario ?? this.scenario,
        trackCount: trackCount ?? this.trackCount,
        geocacheId: geocacheId ?? this.geocacheId,
        seedScrobbles: seedScrobbles ?? this.seedScrobbles,
        customTempC: customTempC ?? this.customTempC,
        customLightPct: customLightPct ?? this.customLightPct,
        customColorKelvin: customColorKelvin ?? this.customColorKelvin,
        customPressureHpa: customPressureHpa ?? this.customPressureHpa,
        customTrendHpa: customTrendHpa ?? this.customTrendHpa,
        customTargetBpm: customTargetBpm ?? this.customTargetBpm,
      );
}

class Track {
  const Track({
    required this.title,
    required this.artist,
    required this.album,
    required this.durationMs,
    required this.tags,
    this.spotifyUri,
    this.lastfmUrl,
  });

  final String title;
  final String artist;
  final String album;
  final int durationMs;
  final List<String> tags;
  final String? spotifyUri;
  final String? lastfmUrl;

  factory Track.fromJson(JsonMap json) => Track(
        title: asStringOrNull(json['title']) ?? 'Untitled',
        artist: asStringOrNull(json['artist']) ?? 'Unknown artist',
        album: asStringOrNull(json['album']) ?? '',
        durationMs: (asDoubleOrNull(json['duration_ms']) ?? 0).round(),
        tags: asStringList(json['tags']),
        spotifyUri: asStringOrNull(json['spotify_uri']),
        lastfmUrl: asStringOrNull(json['lastfm_url']),
      );
}

class ScoredTrack {
  const ScoredTrack({
    required this.track,
    required this.score,
    required this.sonicDistance,
    required this.tasteAffinity,
    required this.corridorFit,
    required this.novelty,
    required this.role,
    required this.position,
    required this.why,
  });

  final Track track;
  final double score;
  final double sonicDistance;
  final double tasteAffinity;
  final double corridorFit;
  final double novelty;

  /// "opener" | "build" | "peak" | "descent" | "closer" | "body"
  final String role;

  final int position;
  final String why;

  factory ScoredTrack.fromJson(JsonMap json) => ScoredTrack(
        track: Track.fromJson(
          asJsonMap(json['track']) ?? const <String, Object?>{},
        ),
        score: asDoubleOrNull(json['score']) ?? 0,
        sonicDistance: asDoubleOrNull(json['sonic_distance']) ?? 0,
        tasteAffinity: asDoubleOrNull(json['taste_affinity']) ?? 0,
        corridorFit: asDoubleOrNull(json['corridor_fit']) ?? 0,
        novelty: asDoubleOrNull(json['novelty']) ?? 0,
        role: asStringOrNull(json['role']) ?? 'body',
        position: (asDoubleOrNull(json['position']) ?? 0).round(),
        why: asStringOrNull(json['why']) ?? '',
      );
}

class Rationale {
  const Rationale({
    required this.headline,
    required this.body,
    required this.skyReading,
    required this.sonicMoves,
    required this.tasteNote,
    required this.confidence,
    required this.degraded,
  });

  final String headline;
  final String body;
  final List<String> skyReading;
  final List<String> sonicMoves;
  final String tasteNote;
  final double confidence;
  final List<String> degraded;

  factory Rationale.fromJson(JsonMap json) => Rationale(
        headline: asStringOrNull(json['headline']) ?? '',
        body: asStringOrNull(json['body']) ?? '',
        skyReading: asStringList(json['sky_reading']),
        sonicMoves: asStringList(json['sonic_moves']),
        tasteNote: asStringOrNull(json['taste_note']) ?? '',
        confidence: asDoubleOrNull(json['confidence']) ?? 0,
        degraded: asStringList(json['degraded']),
      );
}

/// Where the playlist ended up: a real Spotify playlist, or an M3U file.
class PlaylistSink {
  const PlaylistSink({
    required this.kind,
    required this.ok,
    this.externalUrl,
    this.payload,
    this.message,
  });

  /// e.g. "spotify" | "m3u" | "none"
  final String kind;

  final bool ok;
  final String? externalUrl;

  /// For the M3U sink, the file body. We hand this to the user rather than
  /// pretending the export failed.
  final String? payload;

  final String? message;

  factory PlaylistSink.fromJson(JsonMap json) => PlaylistSink(
        kind: asStringOrNull(json['kind']) ?? 'none',
        ok: asBoolOrNull(json['ok']) ?? false,
        externalUrl: asStringOrNull(json['external_url']),
        payload: asStringOrNull(json['payload']),
        message: asStringOrNull(json['message']),
      );
}

class Playlist {
  const Playlist({
    required this.id,
    required this.title,
    required this.subtitle,
    required this.tracks,
    required this.sky,
    required this.sonicTarget,
    required this.themeId,
    required this.genreId,
    required this.rationale,
    required this.createdAt,
    required this.sink,
  });

  final String id;
  final String title;
  final String subtitle;
  final List<ScoredTrack> tracks;
  final SkyVector sky;
  final SonicVector sonicTarget;
  final String themeId;
  final String genreId;
  final Rationale rationale;
  final String createdAt;
  final PlaylistSink sink;

  factory Playlist.fromJson(JsonMap json) => Playlist(
        id: asStringOrNull(json['id']) ?? '',
        title: asStringOrNull(json['title']) ?? 'Untitled set',
        subtitle: asStringOrNull(json['subtitle']) ?? '',
        tracks: <ScoredTrack>[
          for (final Object? t in asJsonList(json['tracks']) ?? const <Object?>[])
            if (asJsonMap(t) case final JsonMap m) ScoredTrack.fromJson(m),
        ],
        sky: SkyVector.fromJson(
            asJsonMap(json['sky']) ?? const <String, Object?>{}),
        sonicTarget: SonicVector.fromJson(
            asJsonMap(json['sonic_target']) ?? const <String, Object?>{}),
        themeId: asStringOrNull(json['theme_id']) ?? '',
        genreId: asStringOrNull(json['genre_id']) ?? '',
        rationale: Rationale.fromJson(
            asJsonMap(json['rationale']) ?? const <String, Object?>{}),
        createdAt: asStringOrNull(json['created_at']) ?? '',
        sink: PlaylistSink.fromJson(
            asJsonMap(json['sink']) ?? const <String, Object?>{}),
      );
}

/// `POST /api/forge` -> ForgeResult. The playlist plus whatever went wrong
/// on the way.
typedef ForgeResponse = ForgeResult;

class ForgeResult {
  const ForgeResult({required this.playlist, required this.degraded});

  final Playlist playlist;
  final List<String> degraded;

  factory ForgeResult.fromJson(JsonMap json) {
    // The backend may return the playlist inline or wrapped.
    final JsonMap playlistJson = asJsonMap(json['playlist']) ?? json;
    return ForgeResult(
      playlist: Playlist.fromJson(playlistJson),
      degraded: asStringList(json['degraded']).isNotEmpty
          ? asStringList(json['degraded'])
          : asStringList(asJsonMap(playlistJson['rationale'])?['degraded']),
    );
  }
}

// ===========================================================================
// Pairing
// ===========================================================================

/// Which music providers this account has connected.
///
/// The degradation story is explicit and the UI states it plainly:
///   * no Spotify -> the sink falls back to an M3U file you download.
///   * no Last.fm -> no taste signal, so the forge runs theme-only.
class PairingStatus {
  const PairingStatus({
    required this.spotify,
    required this.lastfm,
    this.spotifyAccount,
    this.lastfmAccount,
  });

  final bool spotify;
  final bool lastfm;
  final String? spotifyAccount;
  final String? lastfmAccount;

  static const PairingStatus none =
      PairingStatus(spotify: false, lastfm: false);

  bool get fullyPaired => spotify && lastfm;

  /// Human-readable consequences of what is missing. Shown verbatim.
  List<String> get consequences => <String>[
        if (!spotify)
          'Spotify is not connected, so a forged set is delivered as an M3U '
              'file rather than a playlist in your account.',
        if (!lastfm)
          'Last.fm is not connected, so there is no taste signal. The forge '
              'runs theme-only and the rationale will say so.',
      ];

  factory PairingStatus.fromJson(JsonMap json) {
    // Accept both `{"spotify": true}` and
    // `{"providers": {"spotify": {"connected": true, "account": "…"}}}`.
    final JsonMap providers = asJsonMap(json['providers']) ?? json;

    bool connected(String key) {
      final Object? v = providers[key];
      final bool? direct = asBoolOrNull(v);
      if (direct != null) return direct;
      final JsonMap? m = asJsonMap(v);
      if (m == null) return false;
      return asBoolOrNull(m['connected']) ?? asBoolOrNull(m['paired']) ?? false;
    }

    String? account(String key) {
      final JsonMap? m = asJsonMap(providers[key]);
      if (m == null) return null;
      return asStringOrNull(m['account']) ??
          asStringOrNull(m['display_name']) ??
          asStringOrNull(m['username']);
    }

    return PairingStatus(
      spotify: connected('spotify'),
      lastfm: connected('lastfm'),
      spotifyAccount: account('spotify'),
      lastfmAccount: account('lastfm'),
    );
  }
}

/// `POST /api/pair/{provider}/start` — the URL to send the user to, plus the
/// correlator we quote back when polling.
class PairingStart {
  const PairingStart({required this.authorizeUrl, this.state, this.token});

  final String authorizeUrl;

  /// Spotify: the OAuth `state`.
  final String? state;

  /// Last.fm: the request token.
  final String? token;

  factory PairingStart.fromJson(JsonMap json) => PairingStart(
        authorizeUrl: asStringOrNull(json['authorize_url']) ?? '',
        state: asStringOrNull(json['state']),
        token: asStringOrNull(json['token']),
      );

  bool get isValid => authorizeUrl.isNotEmpty;
}

// ===========================================================================
// Almanac
// ===========================================================================

/// One past forge, as listed by `GET /api/almanac/history`.
class AlmanacEntry {
  const AlmanacEntry({
    required this.id,
    required this.title,
    required this.themeId,
    required this.createdAt,
    required this.trackCount,
    this.headline,
    this.pressureTrend6h,
    this.locationLabel,
    this.tracksPreview = const <String>[],
  });

  final String id;
  final String title;
  final String themeId;
  final String createdAt;
  final int trackCount;
  final String? headline;
  final double? pressureTrend6h;
  final String? locationLabel;
  final List<String> tracksPreview;

  String get themeName => themeId.isNotEmpty ? themeId : 'Unknown Theme';

  factory AlmanacEntry.fromJson(JsonMap json) => AlmanacEntry(
        id: asStringOrNull(json['id']) ?? '',
        title: asStringOrNull(json['title']) ?? 'Untitled set',
        themeId: asStringOrNull(json['theme_id']) ?? '',
        createdAt: asStringOrNull(json['created_at']) ?? '',
        trackCount: (asDoubleOrNull(json['track_count']) ??
                (asJsonList(json['tracks'])?.length ?? 0))
            .round(),
        headline: asStringOrNull(
              asJsonMap(json['rationale'])?['headline'],
            ) ??
            asStringOrNull(json['subtitle']),
        pressureTrend6h: asDoubleOrNull(
              asJsonMap(json['sky'])?['pressure_trend_6h'],
            ) ??
            asDoubleOrNull(json['pressure_trend_6h']),
        locationLabel: asStringOrNull(json['location_label']),
        tracksPreview: asStringList(json['tracks_preview']),
      );
}

/// A single scrobbled track indexed in the Firestore Almanac (`GET /api/almanac/scrobbles`).
class ScrobbleEntry {
  const ScrobbleEntry({
    required this.id,
    required this.title,
    required this.artist,
    required this.tags,
    required this.weatherTheme,
    required this.bpmEstimate,
    required this.energyEstimate,
    required this.playCount,
    required this.lastPlayedAt,
    this.album,
  });

  final String id;
  final String title;
  final String artist;
  final String? album;
  final List<String> tags;
  final String weatherTheme;
  final int bpmEstimate;
  final double energyEstimate;
  final int playCount;
  final String lastPlayedAt;

  String get trackKey => '$artist - $title';

  factory ScrobbleEntry.fromJson(JsonMap json) => ScrobbleEntry(
        id: asStringOrNull(json['id']) ?? '',
        title: asStringOrNull(json['title']) ?? 'Untitled',
        artist: asStringOrNull(json['artist']) ?? 'Unknown Artist',
        album: asStringOrNull(json['album']),
        tags: asStringList(json['tags']),
        weatherTheme: asStringOrNull(json['weather_theme']) ?? 'petrichor',
        bpmEstimate: (asDoubleOrNull(json['bpm_estimate']) ?? 112).round(),
        energyEstimate: asDoubleOrNull(json['energy_estimate']) ?? 0.6,
        playCount: (asDoubleOrNull(json['play_count']) ?? 1).round(),
        lastPlayedAt: asStringOrNull(json['last_played_at']) ?? '',
      );
}

class ScrobbleAnalytics {
  const ScrobbleAnalytics({
    required this.totalScrobbles,
    required this.uniqueTracks,
    required this.avgBpm,
    required this.avgEnergy,
    required this.topArtists,
    required this.topGenres,
    required this.weatherAffinity,
    this.yearlyCounts = const <String, int>{},
  });

  final int totalScrobbles;
  final int uniqueTracks;
  final double avgBpm;
  final double avgEnergy;
  final List<JsonMap> topArtists;
  final List<JsonMap> topGenres;
  final List<JsonMap> weatherAffinity;
  final Map<String, int> yearlyCounts;

  static const ScrobbleAnalytics empty = ScrobbleAnalytics(
    totalScrobbles: 0,
    uniqueTracks: 0,
    avgBpm: 112.0,
    avgEnergy: 0.60,
    topArtists: <JsonMap>[],
    topGenres: <JsonMap>[],
    weatherAffinity: <JsonMap>[],
    yearlyCounts: <String, int>{},
  );

  factory ScrobbleAnalytics.fromJson(JsonMap json) {
    final JsonMap? rawYr = asJsonMap(json['yearly_counts']);
    final Map<String, int> yrMap = <String, int>{};
    if (rawYr != null) {
      for (final MapEntry<String, Object?> entry in rawYr.entries) {
        yrMap[entry.key] = (asDoubleOrNull(entry.value) ?? 0).round();
      }
    }
    return ScrobbleAnalytics(
      totalScrobbles: (asDoubleOrNull(json['total_scrobbles']) ?? 0).round(),
      uniqueTracks: (asDoubleOrNull(json['unique_tracks']) ?? 0).round(),
      avgBpm: asDoubleOrNull(json['avg_bpm']) ?? 112.0,
      avgEnergy: asDoubleOrNull(json['avg_energy']) ?? 0.60,
      topArtists: <JsonMap>[
        for (final Object? item in asJsonList(json['top_artists']) ?? const <Object?>[])
          if (asJsonMap(item) case final JsonMap m) m,
      ],
      topGenres: <JsonMap>[
        for (final Object? item in asJsonList(json['top_genres']) ?? const <Object?>[])
          if (asJsonMap(item) case final JsonMap m) m,
      ],
      weatherAffinity: <JsonMap>[
        for (final Object? item in asJsonList(json['weather_affinity']) ?? const <Object?>[])
          if (asJsonMap(item) case final JsonMap m) m,
      ],
      yearlyCounts: yrMap,
    );
  }
}

class ScrobbleSearchResponse {
  const ScrobbleSearchResponse({
    required this.count,
    required this.scrobbles,
    required this.analytics,
    required this.syncedFromFirestore,
    this.queryEngine = 'BigQuery OLAP + Firestore Dual-Store Cache',
    this.cacheStatus = 'MEMORY_HIT',
    this.bytesBilled = 0,
    this.estimatedCostUsd = 0.0,
    this.executionMs = 0.0,
  });

  final int count;
  final List<ScrobbleEntry> scrobbles;
  final ScrobbleAnalytics analytics;
  final bool syncedFromFirestore;
  final String queryEngine;
  final String cacheStatus;
  final int bytesBilled;
  final double estimatedCostUsd;
  final double executionMs;

  static const ScrobbleSearchResponse empty = ScrobbleSearchResponse(
    count: 0,
    scrobbles: <ScrobbleEntry>[],
    analytics: ScrobbleAnalytics.empty,
    syncedFromFirestore: false,
  );

  factory ScrobbleSearchResponse.fromJson(JsonMap json) => ScrobbleSearchResponse(
        count: (asDoubleOrNull(json['count']) ?? 0).round(),
        scrobbles: <ScrobbleEntry>[
          for (final Object? item in asJsonList(json['scrobbles']) ?? const <Object?>[])
            if (asJsonMap(item) case final JsonMap m) ScrobbleEntry.fromJson(m),
        ],
        analytics: ScrobbleAnalytics.fromJson(
          asJsonMap(json['analytics']) ?? const <String, Object?>{},
        ),
        syncedFromFirestore: json['synced_from_firestore'] == true,
        queryEngine: asStringOrNull(json['query_engine']) ?? 'BigQuery OLAP + Firestore',
        cacheStatus: asStringOrNull(json['cache_status']) ?? 'MEMORY_HIT',
        bytesBilled: (asDoubleOrNull(json['bytes_billed']) ?? 0).round(),
        estimatedCostUsd: asDoubleOrNull(json['estimated_cost_usd']) ?? 0.0,
        executionMs: asDoubleOrNull(json['execution_ms']) ?? 0.0,
      );
}

class CohortPieSlice {
  const CohortPieSlice({
    required this.category,
    required this.label,
    required this.count,
    required this.percentage,
    required this.colorHex,
  });

  final String category;
  final String label;
  final int count;
  final double percentage;
  final String colorHex;

  factory CohortPieSlice.fromJson(JsonMap json) => CohortPieSlice(
        category: asStringOrNull(json['category']) ?? '',
        label: asStringOrNull(json['label']) ?? '',
        count: (asDoubleOrNull(json['count']) ?? 0).round(),
        percentage: asDoubleOrNull(json['percentage']) ?? 0.0,
        colorHex: asStringOrNull(json['color_hex']) ?? '#10B981',
      );
}

class PlaylistTrackMatch {
  const PlaylistTrackMatch({
    required this.position,
    required this.artist,
    required this.title,
    this.album,
    required this.status,
    required this.scrobbleCount,
    required this.artistTotalScrobbles,
    this.firstPlayedYear,
    this.lastPlayedYear,
    this.peakYear,
    required this.weatherTheme,
    required this.bpmEstimate,
    required this.energyEstimate,
    required this.trackKey,
  });

  final int position;
  final String artist;
  final String title;
  final String? album;
  final String status; // IN_COHORT_EXACT | ARTIST_FAMILIAR_NEW_TRACK | NEW_DISCOVERY
  final int scrobbleCount;
  final int artistTotalScrobbles;
  final int? firstPlayedYear;
  final int? lastPlayedYear;
  final int? peakYear;
  final String weatherTheme;
  final int bpmEstimate;
  final double energyEstimate;
  final String trackKey;

  factory PlaylistTrackMatch.fromJson(JsonMap json) => PlaylistTrackMatch(
        position: (asDoubleOrNull(json['position']) ?? 0).round(),
        artist: asStringOrNull(json['artist']) ?? '',
        title: asStringOrNull(json['title']) ?? '',
        album: asStringOrNull(json['album']),
        status: asStringOrNull(json['status']) ?? 'NEW_DISCOVERY',
        scrobbleCount: (asDoubleOrNull(json['scrobble_count']) ?? 0).round(),
        artistTotalScrobbles:
            (asDoubleOrNull(json['artist_total_scrobbles']) ?? 0).round(),
        firstPlayedYear: asDoubleOrNull(json['first_played_year'])?.round(),
        lastPlayedYear: asDoubleOrNull(json['last_played_year'])?.round(),
        peakYear: asDoubleOrNull(json['peak_year'])?.round(),
        weatherTheme: asStringOrNull(json['weather_theme']) ?? 'warm_front_haze',
        bpmEstimate: (asDoubleOrNull(json['bpm_estimate']) ?? 102).round(),
        energyEstimate: asDoubleOrNull(json['energy_estimate']) ?? 0.54,
        trackKey: asStringOrNull(json['track_key']) ?? '',
      );
}

class PlaylistCohortResponse {
  const PlaylistCohortResponse({
    required this.playlistTitle,
    required this.sourceType,
    required this.totalTracks,
    required this.exactMatchesCount,
    required this.familiarArtistCount,
    required this.newDiscoveryCount,
    required this.cohortOverlapPct,
    required this.totalHistoricalPlays,
    required this.totalArtistCohortPlays,
    required this.peakNostalgiaYear,
    required this.dominantWeatherTheme,
    required this.avgBpm,
    required this.avgEnergy,
    required this.cohortPieSlices,
    required this.weatherPieSlices,
    required this.yearlyCohortGraph,
    required this.hourlyCohortGraph,
    required this.trackMatches,
    this.queryEngine = 'BigQuery OLAP Cohort Engine',
    this.cacheStatus = 'MEMORY_HIT',
    this.bytesBilled = 0,
    this.estimatedCostUsd = 0.0,
    this.executionMs = 0.0,
  });

  final String playlistTitle;
  final String sourceType;
  final int totalTracks;
  final int exactMatchesCount;
  final int familiarArtistCount;
  final int newDiscoveryCount;
  final double cohortOverlapPct;
  final int totalHistoricalPlays;
  final int totalArtistCohortPlays;
  final String peakNostalgiaYear;
  final String dominantWeatherTheme;
  final double avgBpm;
  final double avgEnergy;
  final List<CohortPieSlice> cohortPieSlices;
  final List<CohortPieSlice> weatherPieSlices;
  final Map<String, int> yearlyCohortGraph;
  final Map<String, int> hourlyCohortGraph;
  final List<PlaylistTrackMatch> trackMatches;
  final String queryEngine;
  final String cacheStatus;
  final int bytesBilled;
  final double estimatedCostUsd;
  final double executionMs;

  factory PlaylistCohortResponse.fromJson(JsonMap json) {
    final JsonMap? rawYr = asJsonMap(json['yearly_cohort_graph']);
    final Map<String, int> yrMap = <String, int>{};
    if (rawYr != null) {
      for (final MapEntry<String, Object?> entry in rawYr.entries) {
        yrMap[entry.key] = (asDoubleOrNull(entry.value) ?? 0).round();
      }
    }
    final JsonMap? rawHr = asJsonMap(json['hourly_cohort_graph']);
    final Map<String, int> hrMap = <String, int>{};
    if (rawHr != null) {
      for (final MapEntry<String, Object?> entry in rawHr.entries) {
        hrMap[entry.key] = (asDoubleOrNull(entry.value) ?? 0).round();
      }
    }
    return PlaylistCohortResponse(
      playlistTitle: asStringOrNull(json['playlist_title']) ?? 'Cohort Analysis',
      sourceType: asStringOrNull(json['source_type']) ?? 'Playlist Link',
      totalTracks: (asDoubleOrNull(json['total_tracks']) ?? 0).round(),
      exactMatchesCount: (asDoubleOrNull(json['exact_matches_count']) ?? 0).round(),
      familiarArtistCount: (asDoubleOrNull(json['familiar_artist_count']) ?? 0).round(),
      newDiscoveryCount: (asDoubleOrNull(json['new_discovery_count']) ?? 0).round(),
      cohortOverlapPct: asDoubleOrNull(json['cohort_overlap_pct']) ?? 0.0,
      totalHistoricalPlays: (asDoubleOrNull(json['total_historical_plays']) ?? 0).round(),
      totalArtistCohortPlays: (asDoubleOrNull(json['total_artist_cohort_plays']) ?? 0).round(),
      peakNostalgiaYear: asStringOrNull(json['peak_nostalgia_year']) ?? '2015',
      dominantWeatherTheme: asStringOrNull(json['dominant_weather_theme']) ?? 'warm_front_haze',
      avgBpm: asDoubleOrNull(json['avg_bpm']) ?? 102.0,
      avgEnergy: asDoubleOrNull(json['avg_energy']) ?? 0.54,
      cohortPieSlices: <CohortPieSlice>[
        for (final Object? item in asJsonList(json['cohort_pie_slices']) ?? const <Object?>[])
          if (asJsonMap(item) case final JsonMap m) CohortPieSlice.fromJson(m),
      ],
      weatherPieSlices: <CohortPieSlice>[
        for (final Object? item in asJsonList(json['weather_pie_slices']) ?? const <Object?>[])
          if (asJsonMap(item) case final JsonMap m) CohortPieSlice.fromJson(m),
      ],
      yearlyCohortGraph: yrMap,
      hourlyCohortGraph: hrMap,
      trackMatches: <PlaylistTrackMatch>[
        for (final Object? item in asJsonList(json['track_matches']) ?? const <Object?>[])
          if (asJsonMap(item) case final JsonMap m) PlaylistTrackMatch.fromJson(m),
      ],
      queryEngine: asStringOrNull(json['query_engine']) ?? 'BigQuery OLAP Cohort Engine',
      cacheStatus: asStringOrNull(json['cache_status']) ?? 'MEMORY_HIT',
      bytesBilled: (asDoubleOrNull(json['bytes_billed']) ?? 0).round(),
      estimatedCostUsd: asDoubleOrNull(json['estimated_cost_usd']) ?? 0.0,
      executionMs: asDoubleOrNull(json['execution_ms']) ?? 0.0,
    );
  }
}

/// `GET /api/almanac/retrospective` — the "your rain sound" lines.
class Retrospective {
  const Retrospective({required this.items});

  final List<RetrospectiveItem> items;

  static const Retrospective empty =
      Retrospective(items: <RetrospectiveItem>[]);

  factory Retrospective.fromJson(Object? json) {
    final List<Object?> raw = asJsonList(json) ??
        asJsonList(asJsonMap(json)?['items']) ??
        const <Object?>[];
    return Retrospective(
      items: <RetrospectiveItem>[
        for (final Object? i in raw)
          if (asJsonMap(i) case final JsonMap m) RetrospectiveItem.fromJson(m),
      ],
    );
  }
}

class RetrospectiveItem {
  const RetrospectiveItem({
    required this.key,
    required this.label,
    required this.detail,
  });

  /// e.g. "rain_sound", "first_frost_record"
  final String key;

  final String label;
  final String detail;

  factory RetrospectiveItem.fromJson(JsonMap json) => RetrospectiveItem(
        key: asStringOrNull(json['key']) ?? '',
        label: asStringOrNull(json['label']) ??
            asStringOrNull(json['title']) ??
            '',
        detail: asStringOrNull(json['detail']) ??
            asStringOrNull(json['body']) ??
            asStringOrNull(json['value']) ??
            '',
      );
}

/// Body for `POST /api/almanac/feedback`.
class FeedbackSignal {
  const FeedbackSignal({
    required this.playlistId,
    required this.trackKey,
    required this.signal,
  });

  final String playlistId;
  final String trackKey;

  /// "loved" | "skipped"
  final String signal;

  JsonMap toJson() => <String, Object?>{
        'playlist_id': playlistId,
        'track_key': trackKey,
        'signal': signal,
      };
}

extension _FirstOrNull<E> on Iterable<E> {
  E? get firstOrNull {
    final Iterator<E> it = iterator;
    return it.moveNext() ? it.current : null;
  }
}

// ============================================================================
// Gemini Live Forge Advisor & Executor
// ============================================================================

class AdvisorActionBadge {
  const AdvisorActionBadge({
    required this.tool,
    required this.label,
    required this.detail,
  });

  final String tool;
  final String label;
  final String detail;

  factory AdvisorActionBadge.fromJson(JsonMap json) => AdvisorActionBadge(
        tool: asStringOrNull(json['tool']) ?? '',
        label: asStringOrNull(json['label']) ?? '',
        detail: asStringOrNull(json['detail']) ?? '',
      );
}

class AdvisorSuggestionItem {
  const AdvisorSuggestionItem({
    required this.id,
    required this.title,
    required this.prompt,
    required this.geocacheId,
    required this.badge,
  });

  final String id;
  final String title;
  final String prompt;
  final String geocacheId;
  final String badge;

  factory AdvisorSuggestionItem.fromJson(JsonMap json) => AdvisorSuggestionItem(
        id: asStringOrNull(json['id']) ?? '',
        title: asStringOrNull(json['title']) ?? '',
        prompt: asStringOrNull(json['prompt']) ?? '',
        geocacheId: asStringOrNull(json['geocache_id']) ?? '',
        badge: asStringOrNull(json['badge']) ?? '',
      );
}

class AdvisorLiveRequest {
  const AdvisorLiveRequest({
    this.prompt,
    this.audioBase64,
    this.audioMimeType = 'audio/webm',
    this.currentGeocacheId,
    this.currentThemeId,
    this.currentGenreId,
    this.autoForge = true,
    this.sessionId,
    this.conversationId,
  });

  final String? prompt;
  final String? audioBase64;
  final String audioMimeType;
  final String? currentGeocacheId;
  final String? currentThemeId;
  final String? currentGenreId;
  final bool autoForge;
  final String? sessionId;
  final String? conversationId;

  JsonMap toJson() => <String, Object?>{
        if (prompt != null) 'prompt': prompt,
        if (audioBase64 != null) 'audio_base64': audioBase64,
        'audio_mime_type': audioMimeType,
        if (currentGeocacheId != null) 'current_geocache_id': currentGeocacheId,
        if (currentThemeId != null) 'current_theme_id': currentThemeId,
        if (currentGenreId != null) 'current_genre_id': currentGenreId,
        'auto_forge': autoForge,
        if (sessionId != null) 'session_id': sessionId,
        if (conversationId != null) 'conversation_id': conversationId,
      };
}

class AdvisorLiveResponse {
  const AdvisorLiveResponse({
    required this.replyText,
    required this.spokenSummary,
    required this.transcript,
    required this.actionsExecuted,
    required this.selectedGeocache,
    required this.selectedThemeId,
    required this.selectedGenreId,
    required this.seededScrobbles,
    required this.forgeResult,
    required this.modelUsed,
    this.trajectoryId,
    this.sessionId,
    this.conversationId,
    this.latencyMs,
  });

  final String replyText;
  final String spokenSummary;
  final String transcript;
  final List<AdvisorActionBadge> actionsExecuted;
  final StreetArtGeoCache? selectedGeocache;
  final String? selectedThemeId;
  final String? selectedGenreId;
  final List<ScrobbleEntry> seededScrobbles;
  final ForgeResult? forgeResult;
  final String modelUsed;
  final String? trajectoryId;
  final String? sessionId;
  final String? conversationId;
  final double? latencyMs;

  factory AdvisorLiveResponse.fromJson(JsonMap json) => AdvisorLiveResponse(
        replyText: asStringOrNull(json['reply_text']) ?? '',
        spokenSummary: asStringOrNull(json['spoken_summary']) ?? '',
        transcript: asStringOrNull(json['transcript']) ?? '',
        actionsExecuted: <AdvisorActionBadge>[
          for (final Object? item in asJsonList(json['actions_executed']) ?? const <Object?>[])
            if (asJsonMap(item) case final JsonMap m) AdvisorActionBadge.fromJson(m),
        ],
        selectedGeocache: asJsonMap(json['selected_geocache']) != null
            ? StreetArtGeoCache.fromJson(asJsonMap(json['selected_geocache'])!)
            : null,
        selectedThemeId: asStringOrNull(json['selected_theme_id']),
        selectedGenreId: asStringOrNull(json['selected_genre_id']),
        seededScrobbles: <ScrobbleEntry>[
          for (final Object? item in asJsonList(json['seeded_scrobbles']) ?? const <Object?>[])
            if (asJsonMap(item) case final JsonMap m) ScrobbleEntry.fromJson(m),
        ],
        forgeResult: asJsonMap(json['forge_result']) != null
            ? ForgeResult.fromJson(asJsonMap(json['forge_result'])!)
            : null,
        modelUsed: asStringOrNull(json['model_used']) ?? 'gemini-2.5-flash',
        trajectoryId: asStringOrNull(json['trajectory_id']),
        sessionId: asStringOrNull(json['session_id']),
        conversationId: asStringOrNull(json['conversation_id']),
        latencyMs: asDoubleOrNull(json['latency_ms']),
      );
}

// ===========================================================================
// BigQuery Conversational Data QnA Agent & On-Demand Graphing Models
// ===========================================================================

class QnAChartPoint {
  const QnAChartPoint({
    required this.label,
    required this.value,
    required this.colorHex,
    required this.percentage,
    required this.extraLabel,
  });

  final String label;
  final double value;
  final String colorHex;
  final double percentage;
  final String extraLabel;

  factory QnAChartPoint.fromJson(JsonMap json) => QnAChartPoint(
        label: asStringOrNull(json['label']) ?? '',
        value: asDoubleOrNull(json['value']) ?? 0.0,
        colorHex: asStringOrNull(json['color_hex']) ?? '#FFB74D',
        percentage: asDoubleOrNull(json['percentage']) ?? 0.0,
        extraLabel: asStringOrNull(json['extra_label']) ?? '',
      );
}

class QnAChartSpec {
  const QnAChartSpec({
    required this.chartType,
    required this.title,
    required this.subtitle,
    required this.xLabel,
    required this.yLabel,
    required this.series,
  });

  final String chartType;
  final String title;
  final String subtitle;
  final String xLabel;
  final String yLabel;
  final List<QnAChartPoint> series;

  QnAChartSpec copyWith({
    String? chartType,
    String? title,
    String? subtitle,
    List<QnAChartPoint>? series,
  }) =>
      QnAChartSpec(
        chartType: chartType ?? this.chartType,
        title: title ?? this.title,
        subtitle: subtitle ?? this.subtitle,
        xLabel: xLabel,
        yLabel: yLabel,
        series: series ?? this.series,
      );

  factory QnAChartSpec.fromJson(JsonMap json) => QnAChartSpec(
        chartType: asStringOrNull(json['chart_type']) ?? 'horizontal_bar',
        title: asStringOrNull(json['title']) ?? 'Almanac Data Visualization',
        subtitle: asStringOrNull(json['subtitle']) ?? 'BigQuery OLAP',
        xLabel: asStringOrNull(json['x_label']) ?? 'Category',
        yLabel: asStringOrNull(json['y_label']) ?? 'Scrobbles',
        series: <QnAChartPoint>[
          for (final Object? item in asJsonList(json['series']) ?? const <Object?>[])
            if (asJsonMap(item) case final JsonMap m) QnAChartPoint.fromJson(m),
        ],
      );
}

class DataQnAStarterPrompt {
  const DataQnAStarterPrompt({
    required this.id,
    required this.icon,
    required this.title,
    required this.prompt,
    required this.preferredChartType,
  });

  final String id;
  final String icon;
  final String title;
  final String prompt;
  final String preferredChartType;

  factory DataQnAStarterPrompt.fromJson(JsonMap json) => DataQnAStarterPrompt(
        id: asStringOrNull(json['id']) ?? '',
        icon: asStringOrNull(json['icon']) ?? 'auto_graph',
        title: asStringOrNull(json['title']) ?? '',
        prompt: asStringOrNull(json['prompt']) ?? '',
        preferredChartType: asStringOrNull(json['preferred_chart_type']) ?? 'auto',
      );
}

class DataQnAStatusResponse {
  const DataQnAStatusResponse({
    required this.agentActive,
    required this.serviceName,
    required this.projectId,
    required this.datasetId,
    required this.tables,
    required this.cacheEnabled,
    required this.starterPrompts,
  });

  final bool agentActive;
  final String serviceName;
  final String projectId;
  final String datasetId;
  final List<String> tables;
  final bool cacheEnabled;
  final List<DataQnAStarterPrompt> starterPrompts;

  factory DataQnAStatusResponse.fromJson(JsonMap json) => DataQnAStatusResponse(
        agentActive: json['agent_active'] != false,
        serviceName: asStringOrNull(json['service_name']) ??
            'BigQuery Conversational Data QnA Agent (geminidataanalytics.googleapis.com/v1beta)',
        projectId: asStringOrNull(json['project_id']) ?? 'netdev-firebase',
        datasetId: asStringOrNull(json['dataset_id']) ?? 'barogroove_analytics',
        tables: asStringList(json['tables']),
        cacheEnabled: json['cache_enabled'] != false,
        starterPrompts: <DataQnAStarterPrompt>[
          for (final Object? item in asJsonList(json['starter_prompts']) ?? const <Object?>[])
            if (asJsonMap(item) case final JsonMap m) DataQnAStarterPrompt.fromJson(m),
        ],
      );
}

class DataQnAResponse {
  const DataQnAResponse({
    required this.question,
    required this.answerMarkdown,
    required this.thoughts,
    required this.sqlQuery,
    required this.rows,
    required this.chartSpec,
    required this.suggestions,
    required this.engine,
    required this.cacheStatus,
    required this.executionMs,
    required this.bytesBilled,
    required this.estimatedCostUsd,
  });

  final String question;
  final String answerMarkdown;
  final List<String> thoughts;
  final String sqlQuery;
  final List<JsonMap> rows;
  final QnAChartSpec chartSpec;
  final List<String> suggestions;
  final String engine;
  final String cacheStatus;
  final double executionMs;
  final int bytesBilled;
  final double estimatedCostUsd;

  DataQnAResponse copyWith({
    QnAChartSpec? chartSpec,
  }) =>
      DataQnAResponse(
        question: question,
        answerMarkdown: answerMarkdown,
        thoughts: thoughts,
        sqlQuery: sqlQuery,
        rows: rows,
        chartSpec: chartSpec ?? this.chartSpec,
        suggestions: suggestions,
        engine: engine,
        cacheStatus: cacheStatus,
        executionMs: executionMs,
        bytesBilled: bytesBilled,
        estimatedCostUsd: estimatedCostUsd,
      );

  factory DataQnAResponse.fromJson(JsonMap json) => DataQnAResponse(
        question: asStringOrNull(json['question']) ?? '',
        answerMarkdown: asStringOrNull(json['answer_markdown']) ?? '',
        thoughts: asStringList(json['thoughts']),
        sqlQuery: asStringOrNull(json['sql_query']) ?? '',
        rows: <JsonMap>[
          for (final Object? item in asJsonList(json['rows']) ?? const <Object?>[])
            if (asJsonMap(item) case final JsonMap m) m,
        ],
        chartSpec: QnAChartSpec.fromJson(asJsonMap(json['chart_spec']) ?? const <String, Object?>{}),
        suggestions: asStringList(json['suggestions']),
        engine: asStringOrNull(json['engine']) ?? 'bigquery_data_qna_v1beta',
        cacheStatus: asStringOrNull(json['cache_status']) ?? 'MEMORY_HIT',
        executionMs: asDoubleOrNull(json['execution_ms']) ?? 0.4,
        bytesBilled: (asDoubleOrNull(json['bytes_billed']) ?? 0).round(),
        estimatedCostUsd: asDoubleOrNull(json['estimated_cost_usd']) ?? 0.0,
      );
}

// ===========================================================================
// DataViz QnA Models (`/api/dataviz/qna`)
// ===========================================================================

class DataVizQnARequest {
  const DataVizQnARequest({
    required this.question,
    this.voiceMode = true,
    this.sessionId,
    this.conversationId,
  });

  final String question;
  final bool voiceMode;
  final String? sessionId;
  final String? conversationId;

  JsonMap toJson() => <String, Object?>{
        'question': question,
        'voice_mode': voiceMode,
        if (sessionId != null) 'session_id': sessionId,
        if (conversationId != null) 'conversation_id': conversationId,
      };
}

class DataVizMatchingScrobble {
  const DataVizMatchingScrobble({
    required this.id,
    required this.artist,
    required this.track,
    required this.album,
  });

  final String id;
  final String artist;
  final String track;
  final String album;

  factory DataVizMatchingScrobble.fromJson(Map<String, dynamic> json) =>
      DataVizMatchingScrobble(
        id: asStringOrNull(json['id']) ?? 'scrobble_id',
        artist: asStringOrNull(json['artist']) ?? 'Massive Attack',
        track: asStringOrNull(json['track']) ??
            asStringOrNull(json['title']) ??
            'Teardrop',
        album: asStringOrNull(json['album']) ?? 'Mezzanine',
      );
}

class DataVizQnAResponse {
  const DataVizQnAResponse({
    required this.answerText,
    required this.spokenSummary,
    required this.highlightSection,
    required this.keyMetricBadge,
    required this.suggestedFollowups,
    required this.matchingScrobbles,
    required this.modelUsed,
    this.trajectoryId,
    this.sessionId,
    this.conversationId,
    this.latencyMs,
  });

  final String answerText;
  final String spokenSummary;
  final String highlightSection;
  final String keyMetricBadge;
  final List<String> suggestedFollowups;
  final List<DataVizMatchingScrobble> matchingScrobbles;
  final String modelUsed;
  final String? trajectoryId;
  final String? sessionId;
  final String? conversationId;
  final double? latencyMs;

  factory DataVizQnAResponse.fromJson(Map<String, dynamic> json) {
    final List<Object?> rawScrobbles =
        asJsonList(json['matching_scrobbles']) ?? const <Object?>[];
    return DataVizQnAResponse(
      answerText: asStringOrNull(json['answer_text']) ?? '',
      spokenSummary: asStringOrNull(json['spoken_summary']) ?? '',
      highlightSection:
          asStringOrNull(json['highlight_section']) ?? 'pressure_vs_bpm',
      keyMetricBadge:
          asStringOrNull(json['key_metric_badge']) ?? 'Sonic Insight',
      suggestedFollowups: asStringList(json['suggested_followups']),
      matchingScrobbles: <DataVizMatchingScrobble>[
        for (final Object? item in rawScrobbles)
          if (asJsonMap(item) case final JsonMap m)
            DataVizMatchingScrobble.fromJson(m),
      ],
      modelUsed: asStringOrNull(json['model_used']) ?? 'gemini-2.5-flash',
      trajectoryId: asStringOrNull(json['trajectory_id']),
      sessionId: asStringOrNull(json['session_id']),
      conversationId: asStringOrNull(json['conversation_id']),
      latencyMs: asDoubleOrNull(json['latency_ms']),
    );
  }
}

// ===========================================================================
// AI Observability & Telemetry Models (`/api/telemetry/*`)
// ===========================================================================

class TokenUsageModel {
  const TokenUsageModel({
    required this.promptTokens,
    required this.candidateTokens,
    required this.totalTokens,
    this.isEstimated = false,
  });

  final int promptTokens;
  final int candidateTokens;
  final int totalTokens;
  final bool isEstimated;

  static const TokenUsageModel empty = TokenUsageModel(
    promptTokens: 0,
    candidateTokens: 0,
    totalTokens: 0,
    isEstimated: false,
  );

  factory TokenUsageModel.fromJson(Map<String, dynamic> json) {
    final int prompt = (asDoubleOrNull(json['prompt_tokens']) ?? 0).round();
    final int candidate = (asDoubleOrNull(json['candidate_tokens']) ??
            asDoubleOrNull(json['candidates_tokens']) ??
            0)
        .round();
    final int total =
        (asDoubleOrNull(json['total_tokens']) ?? (prompt + candidate)).round();
    return TokenUsageModel(
      promptTokens: prompt,
      candidateTokens: candidate,
      totalTokens: total,
      isEstimated: asBoolOrNull(json['is_estimated']) ?? false,
    );
  }

  JsonMap toJson() => <String, Object?>{
        'prompt_tokens': promptTokens,
        'candidate_tokens': candidateTokens,
        'total_tokens': totalTokens,
        'is_estimated': isEstimated,
      };
}

class ToolStepModel {
  const ToolStepModel({
    required this.stepId,
    required this.toolName,
    required this.label,
    required this.detail,
    this.status = 'ok',
    this.latencyMs = 0.0,
    this.inputArgs = const <String, dynamic>{},
    this.outputSummary = '',
  });

  final String stepId;
  final String toolName;
  final String label;
  final String detail;
  final String status;
  final double latencyMs;
  final Map<String, dynamic> inputArgs;
  final String outputSummary;

  String get name => toolName;

  factory ToolStepModel.fromJson(Map<String, dynamic> json) {
    final String tool = asStringOrNull(json['tool_name']) ??
        asStringOrNull(json['tool']) ??
        asStringOrNull(json['name']) ??
        'tool';
    return ToolStepModel(
      stepId: asStringOrNull(json['step_id']) ?? tool,
      toolName: tool,
      label: asStringOrNull(json['label']) ?? tool,
      detail: asStringOrNull(json['detail']) ?? '',
      status: asStringOrNull(json['status']) ?? 'ok',
      latencyMs: asDoubleOrNull(json['latency_ms']) ?? 0.0,
      inputArgs: asJsonMap(json['input_args']) ??
          asJsonMap(json['args']) ??
          const <String, dynamic>{},
      outputSummary: asStringOrNull(json['output_summary']) ??
          asStringOrNull(json['result_summary']) ??
          '',
    );
  }

  JsonMap toJson() => <String, Object?>{
        'step_id': stepId,
        'tool_name': toolName,
        'label': label,
        'detail': detail,
        'status': status,
        'latency_ms': latencyMs,
        'input_args': inputArgs,
        'output_summary': outputSummary,
      };
}

class TrajectoryRecordModel {
  const TrajectoryRecordModel({
    required this.trajectoryId,
    required this.sessionId,
    required this.conversationId,
    required this.userId,
    required this.surface,
    required this.endpoint,
    required this.createdAt,
    required this.latencyMs,
    required this.traceId,
    required this.spanId,
    required this.gcpTrace,
    required this.requestedModel,
    required this.executionPath,
    required this.httpStatus,
    this.errorState,
    required this.tokenUsage,
    required this.systemInstruction,
    required this.userPrompt,
    required this.multimodalMetadata,
    required this.rawModelResponse,
    required this.parsedPlan,
    required this.toolSteps,
    required this.extractedMemoryIds,
  });

  final String trajectoryId;
  final String sessionId;
  final String conversationId;
  final String userId;
  final String surface;
  final String endpoint;
  final String createdAt;
  final double latencyMs;
  final String traceId;
  final String spanId;
  final String gcpTrace;
  final String requestedModel;
  final String executionPath;
  final int httpStatus;
  final String? errorState;
  final TokenUsageModel tokenUsage;
  final String systemInstruction;
  final String userPrompt;
  final Map<String, dynamic> multimodalMetadata;
  final String rawModelResponse;
  final Map<String, dynamic> parsedPlan;
  final List<ToolStepModel> toolSteps;
  final List<String> extractedMemoryIds;

  String get gcpTracePath => gcpTrace;
  TokenUsageModel get tokens => tokenUsage;

  factory TrajectoryRecordModel.fromJson(Map<String, dynamic> json) {
    final List<Object?> rawTools = asJsonList(json['tool_steps']) ??
        asJsonList(json['actions_executed']) ??
        const <Object?>[];
    return TrajectoryRecordModel(
      trajectoryId: asStringOrNull(json['trajectory_id']) ?? '',
      sessionId: asStringOrNull(json['session_id']) ?? '',
      conversationId: asStringOrNull(json['conversation_id']) ?? '',
      userId: asStringOrNull(json['user_id']) ?? 'demo',
      surface: asStringOrNull(json['surface']) ?? 'advisor',
      endpoint: asStringOrNull(json['endpoint']) ??
          asStringOrNull(json['operation']) ??
          '',
      createdAt: asStringOrNull(json['created_at']) ??
          asStringOrNull(json['timestamp_utc']) ??
          '',
      latencyMs: asDoubleOrNull(json['latency_ms']) ?? 0.0,
      traceId: asStringOrNull(json['trace_id']) ?? '',
      spanId: asStringOrNull(json['span_id']) ?? '',
      gcpTrace: asStringOrNull(json['gcp_trace']) ??
          asStringOrNull(json['gcp_trace_path']) ??
          asStringOrNull(json['logging.googleapis.com/trace']) ??
          '',
      requestedModel: asStringOrNull(json['requested_model']) ??
          asStringOrNull(json['model']) ??
          'gemini-2.5-flash',
      executionPath: asStringOrNull(json['execution_path']) ??
          asStringOrNull(json['model_path']) ??
          'vertex-ai',
      httpStatus: (asDoubleOrNull(json['http_status']) ?? 200).round(),
      errorState: asStringOrNull(json['error_state']),
      tokenUsage: TokenUsageModel.fromJson(
        asJsonMap(json['token_usage']) ??
            asJsonMap(json['tokens']) ??
            const <String, dynamic>{},
      ),
      systemInstruction: asStringOrNull(json['system_instruction']) ?? '',
      userPrompt: asStringOrNull(json['user_prompt']) ??
          asStringOrNull(json['prompt']) ??
          '',
      multimodalMetadata:
          asJsonMap(json['multimodal_metadata']) ?? const <String, dynamic>{},
      rawModelResponse: asStringOrNull(json['raw_model_response']) ??
          asStringOrNull(json['output']) ??
          '',
      parsedPlan: asJsonMap(json['parsed_plan']) ?? const <String, dynamic>{},
      toolSteps: <ToolStepModel>[
        for (final Object? item in rawTools)
          if (asJsonMap(item) case final JsonMap m) ToolStepModel.fromJson(m),
      ],
      extractedMemoryIds: asStringList(json['extracted_memory_ids']),
    );
  }
}

class SessionRecordModel {
  const SessionRecordModel({
    required this.sessionId,
    required this.userId,
    required this.clientSurface,
    required this.startedAt,
    required this.lastActiveAt,
    required this.turnCount,
    this.activeGeocacheId,
    this.activeThemeId,
    this.activeGenreId,
    required this.conversationIds,
    required this.trajectoryIds,
  });

  final String sessionId;
  final String userId;
  final String clientSurface;
  final String startedAt;
  final String lastActiveAt;
  final int turnCount;
  final String? activeGeocacheId;
  final String? activeThemeId;
  final String? activeGenreId;
  final List<String> conversationIds;
  final List<String> trajectoryIds;

  factory SessionRecordModel.fromJson(Map<String, dynamic> json) =>
      SessionRecordModel(
        sessionId: asStringOrNull(json['session_id']) ?? '',
        userId: asStringOrNull(json['user_id']) ?? 'demo',
        clientSurface: asStringOrNull(json['client_surface']) ??
            asStringOrNull(json['surface']) ??
            'web-flutter',
        startedAt: asStringOrNull(json['started_at']) ?? '',
        lastActiveAt: asStringOrNull(json['last_active_at']) ?? '',
        turnCount: (asDoubleOrNull(json['turn_count']) ?? 0).round(),
        activeGeocacheId: asStringOrNull(json['active_geocache_id']),
        activeThemeId: asStringOrNull(json['active_theme_id']),
        activeGenreId: asStringOrNull(json['active_genre_id']),
        conversationIds: asStringList(json['conversation_ids']),
        trajectoryIds: asStringList(json['trajectory_ids']),
      );
}

class ConversationTurnModel {
  const ConversationTurnModel({
    required this.turnId,
    required this.turnIndex,
    required this.role,
    required this.timestamp,
    required this.content,
    this.audioTranscript,
    this.spokenSummary,
    required this.actionsExecuted,
    this.trajectoryId,
  });

  final String turnId;
  final int turnIndex;
  final String role;
  final String timestamp;
  final String content;
  final String? audioTranscript;
  final String? spokenSummary;
  final List<String> actionsExecuted;
  final String? trajectoryId;

  factory ConversationTurnModel.fromJson(Map<String, dynamic> json) {
    final List<Object?>? rawActions = asJsonList(json['actions_executed']);
    final List<String> actions = <String>[];
    if (rawActions != null) {
      for (final Object? item in rawActions) {
        if (item is String) {
          actions.add(item);
        } else if (asJsonMap(item) case final JsonMap m) {
          final String label =
              asStringOrNull(m['label']) ?? asStringOrNull(m['tool']) ?? '';
          if (label.isNotEmpty) actions.add(label);
        }
      }
    }
    return ConversationTurnModel(
      turnId: asStringOrNull(json['turn_id']) ?? '',
      turnIndex: (asDoubleOrNull(json['turn_index']) ?? 0).round(),
      role: asStringOrNull(json['role']) ?? 'user',
      timestamp: asStringOrNull(json['timestamp']) ??
          asStringOrNull(json['created_at']) ??
          '',
      content: asStringOrNull(json['content']) ?? '',
      audioTranscript: asStringOrNull(json['audio_transcript']),
      spokenSummary: asStringOrNull(json['spoken_summary']),
      actionsExecuted: actions,
      trajectoryId: asStringOrNull(json['trajectory_id']),
    );
  }
}

class ConversationRecordModel {
  const ConversationRecordModel({
    required this.conversationId,
    required this.sessionId,
    required this.userId,
    required this.surface,
    required this.title,
    required this.summary,
    required this.createdAt,
    required this.updatedAt,
    required this.turns,
  });

  final String conversationId;
  final String sessionId;
  final String userId;
  final String surface;
  final String title;
  final String summary;
  final String createdAt;
  final String updatedAt;
  final List<ConversationTurnModel> turns;

  factory ConversationRecordModel.fromJson(Map<String, dynamic> json) {
    final List<Object?> rawTurns =
        asJsonList(json['turns']) ?? const <Object?>[];
    return ConversationRecordModel(
      conversationId: asStringOrNull(json['conversation_id']) ?? '',
      sessionId: asStringOrNull(json['session_id']) ?? '',
      userId: asStringOrNull(json['user_id']) ?? 'demo',
      surface: asStringOrNull(json['surface']) ?? 'advisor',
      title: asStringOrNull(json['title']) ?? 'AI Conversation Thread',
      summary: asStringOrNull(json['summary']) ?? '',
      createdAt: asStringOrNull(json['created_at']) ?? '',
      updatedAt: asStringOrNull(json['updated_at']) ?? '',
      turns: <ConversationTurnModel>[
        for (final Object? item in rawTurns)
          if (asJsonMap(item) case final JsonMap m)
            ConversationTurnModel.fromJson(m),
      ],
    );
  }
}

class MemoryRecordModel {
  const MemoryRecordModel({
    required this.memoryId,
    required this.userId,
    this.conversationId,
    this.trajectoryId,
    required this.sourceType,
    required this.category,
    required this.subject,
    required this.content,
    required this.sentiment,
    required this.confidence,
    required this.tags,
    required this.createdAt,
    required this.lastReinforcedAt,
    required this.reinforcementCount,
  });

  final String memoryId;
  final String userId;
  final String? conversationId;
  final String? trajectoryId;
  final String sourceType;
  final String category;
  final String subject;
  final String content;
  final String sentiment;
  final double confidence;
  final List<String> tags;
  final String createdAt;
  final String lastReinforcedAt;
  final int reinforcementCount;

  factory MemoryRecordModel.fromJson(Map<String, dynamic> json) =>
      MemoryRecordModel(
        memoryId: asStringOrNull(json['memory_id']) ??
            asStringOrNull(json['id']) ??
            '',
        userId: asStringOrNull(json['user_id']) ?? 'demo',
        conversationId: asStringOrNull(json['conversation_id']),
        trajectoryId: asStringOrNull(json['trajectory_id']),
        sourceType: asStringOrNull(json['source_type']) ?? 'conversation',
        category: asStringOrNull(json['category']) ?? 'musical_preference',
        subject: asStringOrNull(json['subject']) ?? 'user:preference',
        content: asStringOrNull(json['content']) ?? '',
        sentiment: asStringOrNull(json['sentiment']) ?? 'positive',
        confidence: asDoubleOrNull(json['confidence']) ?? 0.9,
        tags: asStringList(json['tags']),
        createdAt: asStringOrNull(json['created_at']) ?? '',
        lastReinforcedAt: asStringOrNull(json['last_reinforced_at']) ??
            asStringOrNull(json['created_at']) ??
            '',
        reinforcementCount:
            (asDoubleOrNull(json['reinforcement_count']) ?? 1).round(),
      );
}

class TelemetrySummaryModel {
  const TelemetrySummaryModel({
    required this.totalAiCalls,
    required this.tokenUsage,
    required this.activeSessions,
    required this.totalSessions,
    required this.totalConversations,
    required this.storedMemories,
    required this.avgLatencyMs,
    required this.trajectoryCountsBySurface,
    required this.trajectoryCountsByPath,
    required this.errorCount,
  });

  final int totalAiCalls;
  final TokenUsageModel tokenUsage;
  final int activeSessions;
  final int totalSessions;
  final int totalConversations;
  final int storedMemories;
  final double avgLatencyMs;
  final Map<String, int> trajectoryCountsBySurface;
  final Map<String, int> trajectoryCountsByPath;
  final int errorCount;

  int get totalCalls => totalAiCalls;
  int get totalTokens => tokenUsage.totalTokens;
  int get totalInputTokens => tokenUsage.promptTokens;
  int get totalOutputTokens => tokenUsage.candidateTokens;
  Map<String, int> get bySurface => trajectoryCountsBySurface;

  static const TelemetrySummaryModel empty = TelemetrySummaryModel(
    totalAiCalls: 0,
    tokenUsage: TokenUsageModel.empty,
    activeSessions: 0,
    totalSessions: 0,
    totalConversations: 0,
    storedMemories: 0,
    avgLatencyMs: 0.0,
    trajectoryCountsBySurface: <String, int>{},
    trajectoryCountsByPath: <String, int>{},
    errorCount: 0,
  );

  factory TelemetrySummaryModel.fromJson(Map<String, dynamic> json) {
    final JsonMap? rawSurfaces =
        asJsonMap(json['trajectory_counts_by_surface']) ??
            asJsonMap(json['by_surface']);
    final Map<String, int> surfaces = <String, int>{};
    if (rawSurfaces != null) {
      for (final MapEntry<String, Object?> e in rawSurfaces.entries) {
        surfaces[e.key] = (asDoubleOrNull(e.value) ?? 0).round();
      }
    }
    final JsonMap? rawPaths = asJsonMap(json['trajectory_counts_by_path']);
    final Map<String, int> paths = <String, int>{};
    if (rawPaths != null) {
      for (final MapEntry<String, Object?> e in rawPaths.entries) {
        paths[e.key] = (asDoubleOrNull(e.value) ?? 0).round();
      }
    }
    final JsonMap? tokenMap = asJsonMap(json['token_usage']);
    final TokenUsageModel tokens = tokenMap != null
        ? TokenUsageModel.fromJson(tokenMap)
        : TokenUsageModel(
            promptTokens:
                (asDoubleOrNull(json['total_input_tokens']) ?? 0).round(),
            candidateTokens:
                (asDoubleOrNull(json['total_output_tokens']) ?? 0).round(),
            totalTokens: (asDoubleOrNull(json['total_tokens']) ?? 0).round(),
          );
    return TelemetrySummaryModel(
      totalAiCalls: (asDoubleOrNull(json['total_ai_calls']) ??
              asDoubleOrNull(json['total_calls']) ??
              0)
          .round(),
      tokenUsage: tokens,
      activeSessions: (asDoubleOrNull(json['active_sessions']) ?? 0).round(),
      totalSessions: (asDoubleOrNull(json['total_sessions']) ?? 0).round(),
      totalConversations:
          (asDoubleOrNull(json['total_conversations']) ?? 0).round(),
      storedMemories: (asDoubleOrNull(json['stored_memories']) ?? 0).round(),
      avgLatencyMs: asDoubleOrNull(json['avg_latency_ms']) ?? 0.0,
      trajectoryCountsBySurface: surfaces,
      trajectoryCountsByPath: paths,
      errorCount: (asDoubleOrNull(json['error_count']) ?? 0).round(),
    );
  }
}



