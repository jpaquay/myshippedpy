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
  });

  final String status;

  /// Feature flags the backend reports, e.g. `{"spotify": true}`.
  final Map<String, bool> capabilities;

  /// Things currently not working. Surfaced verbatim in the UI.
  final List<String> degraded;

  bool get ok => status == 'ok' || status == 'healthy';

  bool capability(String name) => capabilities[name] ?? false;

  static const HealthStatus unknown = HealthStatus(
    status: 'unknown',
    capabilities: <String, bool>{},
    degraded: <String>['backend unreachable'],
  );

  factory HealthStatus.fromJson(JsonMap json) {
    final JsonMap caps = asJsonMap(json['capabilities']) ?? const <String, Object?>{};
    return HealthStatus(
      status: asStringOrNull(json['status']) ?? 'unknown',
      capabilities: <String, bool>{
        for (final MapEntry<String, Object?> e in caps.entries)
          e.key: asBoolOrNull(e.value) ?? false,
      },
      degraded: asStringList(json['degraded']),
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
  });

  final double? lat;
  final double? lon;
  final String? themeId;
  final String? genreId;

  /// Named scenario instead of live weather. Mutually exclusive with lat/lon
  /// in practice, though the backend decides.
  final String? scenario;

  final int? trackCount;

  JsonMap toJson() => <String, Object?>{
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
        if (themeId != null) 'theme_id': themeId,
        if (genreId != null) 'genre_id': genreId,
        if (scenario != null) 'scenario': scenario,
        if (trackCount != null) 'track_count': trackCount,
      };

  ForgeRequest copyWith({
    double? lat,
    double? lon,
    String? themeId,
    String? genreId,
    String? scenario,
    int? trackCount,
  }) =>
      ForgeRequest(
        lat: lat ?? this.lat,
        lon: lon ?? this.lon,
        themeId: themeId ?? this.themeId,
        genreId: genreId ?? this.genreId,
        scenario: scenario ?? this.scenario,
        trackCount: trackCount ?? this.trackCount,
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
  });

  final String id;
  final String title;
  final String themeId;
  final String createdAt;
  final int trackCount;
  final String? headline;
  final double? pressureTrend6h;

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
      );
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
