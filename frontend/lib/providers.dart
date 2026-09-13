/// Riverpod wiring. One place, so the dependency graph is readable.
///
/// Kept deliberately small. The interesting state in this app is not held
/// here — it lives in the A2UI surface controllers, which are owned by the
/// screens that fetch them. What is here is the shell: who is signed in, what
/// the backend can currently do, which providers are paired.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'a2ui/actions.dart';
import 'a2ui/catalog.dart';
import 'a2ui/renderer.dart';
import 'api/auth_interceptor.dart';
import 'api/client.dart';
import 'api/models.dart';
import 'app_theme.dart';
import 'auth/auth_service.dart';
import 'auth/pairing_service.dart';

// ===========================================================================
// Appearance
// ===========================================================================

/// Holds the user's Dark / Light / As-host choice and persists it.
///
/// Storage is `shared_preferences`, which the pairing service already uses —
/// on web that is `localStorage`, so the choice survives a reload and a new
/// session on the same browser. Persistence is deliberately best-effort:
/// a browser with storage disabled, or a private window, must give you a
/// working app that simply forgets, not a start-up crash.
///
/// First run, or an unreadable value: [BgThemeChoice.host]. The app follows
/// the OS until the user says otherwise.
class BgThemeController extends StateNotifier<BgThemeChoice> {
  BgThemeController({Future<SharedPreferences>? preferences})
      : _preferences = preferences ?? SharedPreferences.getInstance(),
        super(BgThemeChoice.fallback) {
    restored = _restore();
  }

  /// The key the choice is stored under. Part of the contract; do not rename.
  static const String storageKey = 'bg.theme.choice';

  final Future<SharedPreferences> _preferences;

  /// Completes once the stored choice (if any) has been applied. Tests await
  /// it; the app does not need to — the first frame renders on the default
  /// and swaps in the stored value on the next one.
  late final Future<void> restored;

  Future<void> _restore() async {
    try {
      final SharedPreferences prefs = await _preferences;
      final BgThemeChoice? stored =
          BgThemeChoice.byId(prefs.getString(storageKey));
      if (stored != null && mounted) state = stored;
    } catch (_) {
      // Storage unavailable. Keep the default; this is not worth a dialog.
    }
  }

  /// Records an explicit choice. The UI updates immediately; the write is
  /// fire-and-forget because a failed write must not block a repaint.
  Future<void> choose(BgThemeChoice choice) async {
    if (mounted) state = choice;
    try {
      final SharedPreferences prefs = await _preferences;
      await prefs.setString(storageKey, choice.id);
    } catch (_) {
      // See above.
    }
  }
}

/// The three-option appearance control's state (Settings → APPEARANCE).
final StateNotifierProvider<BgThemeController, BgThemeChoice>
    bgThemeChoiceProvider =
    StateNotifierProvider<BgThemeController, BgThemeChoice>(
  (Ref ref) => BgThemeController(),
);

/// What `MaterialApp` consumes. Derived — there is one source of truth and it
/// is [bgThemeChoiceProvider].
final Provider<ThemeMode> themeModeProvider = Provider<ThemeMode>(
  (Ref ref) => ref.watch(bgThemeChoiceProvider).mode,
);

// ===========================================================================
// Settings deep links
// ===========================================================================

/// The sections of Settings that something else in the app can point at.
enum SettingsSection { account, appearance, connections, install }

/// A one-shot request to open Settings somewhere specific.
///
/// The account menu and the header connection badges set this and then
/// navigate; `SettingsScreen` consumes it, scrolls the section into view and
/// clears it. It is a navigation intent, not state: nothing reads it twice.
@immutable
class SettingsFocus {
  const SettingsFocus({required this.section, this.provider});

  final SettingsSection section;

  /// Which pairing card to bring into view, for
  /// [SettingsSection.connections].
  final PairingProvider? provider;
}

final StateProvider<SettingsFocus?> settingsFocusProvider =
    StateProvider<SettingsFocus?>((Ref ref) => null);

// ===========================================================================
// Infrastructure
// ===========================================================================

final Provider<BarogrooveApi> apiProvider = Provider<BarogrooveApi>(
  (Ref ref) {
    final BarogrooveApi api = BarogrooveApi();
    ref.onDispose(api.dispose);
    return api;
  },
);

final Provider<AuthService> authServiceProvider =
    Provider<AuthService>((Ref ref) => AuthService());

final Provider<PairingService> pairingServiceProvider =
    Provider<PairingService>(
  (Ref ref) => PairingService(ref.watch(apiProvider)),
);

/// The component catalog binding. Built once — it is immutable.
final Provider<A2uiCatalog> catalogProvider =
    Provider<A2uiCatalog>((Ref ref) => buildBarogrooveCatalog());

/// The dispatcher every surface uses to talk back to the agent.
final Provider<A2uiActionDispatcher> actionDispatcherProvider =
    Provider<A2uiActionDispatcher>(
  (Ref ref) {
    final HttpActionDispatcher dispatcher =
        HttpActionDispatcher(headers: authHeaders);
    ref.onDispose(dispatcher.dispose);
    return dispatcher;
  },
);

/// Creates a fresh surface controller for a named surface.
///
/// Screens `ref.watch` this with their surface id, hand the controller to an
/// [A2uiSurfaceView], and feed it whatever the API returned. The controller
/// is disposed with the screen.
final AutoDisposeProviderFamily<A2uiSurfaceController, String>
    surfaceControllerProvider =
    Provider.autoDispose.family<A2uiSurfaceController, String>(
  (Ref ref, String surfaceId) {
    final A2uiSurfaceController controller = A2uiSurfaceController(
      surfaceId: surfaceId,
      catalog: ref.watch(catalogProvider),
      dispatcher: ref.watch(actionDispatcherProvider),
    );
    ref.onDispose(controller.dispose);
    return controller;
  },
);

// ===========================================================================
// Session
// ===========================================================================

/// The signed-in user, or null. Drives routing.
final StreamProvider<BgUser?> authStateProvider = StreamProvider<BgUser?>(
  (Ref ref) => ref.watch(authServiceProvider).userChanges,
);

/// Convenience: are we signed in right now?
final Provider<bool> isSignedInProvider = Provider<bool>(
  (Ref ref) => ref.watch(authStateProvider).valueOrNull != null,
);

// ===========================================================================
// Backend state
// ===========================================================================

/// Backend health and capability flags. Refreshed on demand.
final FutureProvider<HealthStatus> healthProvider =
    FutureProvider<HealthStatus>(
  (Ref ref) async {
    final ApiResult<HealthStatus> res = await ref.watch(apiProvider).health();
    // A health check that fails is itself a health signal, not an error to
    // propagate: the UI should say "backend unreachable", not blow up.
    return res.valueOrNull ?? HealthStatus.unknown;
  },
);

/// Which providers are paired. Re-read after every pairing action.
final FutureProvider<PairingStatus> pairingStatusProvider =
    FutureProvider<PairingStatus>(
  (Ref ref) async {
    // Re-runs whenever the *identity* changes; a different user has a
    // different set of connections, and a signed-out client has none. Keying
    // on the uid (rather than on the auth AsyncValue) means a user switch
    // rebuilds this provider, so the next user can never be served the
    // previous user's connections.
    final String? uid = ref.watch(
      authStateProvider.select((AsyncValue<BgUser?> u) => u.valueOrNull?.uid),
    );
    if (uid == null) {
      // Signed out: do not ask, and do not keep the last answer. Whatever was
      // connected belonged to whoever was signed in a moment ago.
      return PairingStatus.none;
    }
    final ApiResult<PairingStatus> res =
        await ref.watch(pairingServiceProvider).status();
    return res.valueOrNull ?? PairingStatus.none;
  },
);

/// The eight themes.
final FutureProvider<List<SkyTheme>> themesProvider =
    FutureProvider<List<SkyTheme>>(
  (Ref ref) async {
    final ApiResult<List<SkyTheme>> res = await ref.watch(apiProvider).themes();
    return res.valueOrNull ?? const <SkyTheme>[];
  },
);

/// The genre corridors.
final FutureProvider<List<GenreCorridorModel>> genresProvider =
    FutureProvider<List<GenreCorridorModel>>(
  (Ref ref) async {
    final ApiResult<List<GenreCorridorModel>> res =
        await ref.watch(apiProvider).genres();
    return res.valueOrNull ?? const <GenreCorridorModel>[];
  },
);

/// Canned sky scenarios, for demoing without waiting for weather.
final FutureProvider<List<SkyScenario>> scenariosProvider =
    FutureProvider<List<SkyScenario>>(
  (Ref ref) async {
    final ApiResult<List<SkyScenario>> res =
        await ref.watch(apiProvider).scenarios();
    return res.valueOrNull ?? const <SkyScenario>[];
  },
);

/// Curated World Street-Art Geo-Cache landmarks.
final FutureProvider<List<StreetArtGeoCache>> geocachesProvider =
    FutureProvider<List<StreetArtGeoCache>>(
  (Ref ref) async {
    final ApiResult<List<StreetArtGeoCache>> res =
        await ref.watch(apiProvider).geocaches();
    return res.valueOrNull ?? const <StreetArtGeoCache>[];
  },
);

/// Currently active World Street-Art Geo-Cache landmark on the Forge screen.
final StateProvider<StreetArtGeoCache?> activeGeocacheProvider =
    StateProvider<StreetArtGeoCache?>((Ref ref) => null);

/// Scrobbles selected in the Almanac Scrobble Explorer to seed the next Forge.
final StateProvider<Set<String>> selectedSeedScrobblesProvider =
    StateProvider<Set<String>>((Ref ref) => <String>{});

// ===========================================================================
// Forge selection (shell state, not domain state)
// ===========================================================================

class ForgeSelection {
  const ForgeSelection({
    this.themeId,
    this.genreId,
    this.scenario,
    this.lat = 50.8503,
    this.lon = 4.3517,
    this.label = 'Parcours BD Comic Strip Trail (Brussels)',
    this.geocacheId = 'parcours_bd_brussels',
    this.seedScrobbles = const <String>[],
    this.consoleMode = 'guided',
    this.customTempC = 14.0,
    this.customLightPct = 45.0,
    this.customColorKelvin = 4200.0,
    this.customPressureHpa = 1009.0,
    this.customTrendHpa = -1.5,
    this.customTargetBpm = 102.0,
  });

  final String? themeId;
  final String? genreId;
  final String? scenario;
  final double? lat;
  final double? lon;
  final String label;
  final String? geocacheId;
  final List<String> seedScrobbles;

  /// 'guided' | 'easy' | 'expert'
  final String consoleMode;
  final double customTempC;
  final double customLightPct;
  final double customColorKelvin;
  final double customPressureHpa;
  final double customTrendHpa;
  final double customTargetBpm;

  ForgeSelection copyWith({
    String? themeId,
    String? genreId,
    String? scenario,
    double? lat,
    double? lon,
    String? label,
    String? geocacheId,
    List<String>? seedScrobbles,
    String? consoleMode,
    double? customTempC,
    double? customLightPct,
    double? customColorKelvin,
    double? customPressureHpa,
    double? customTrendHpa,
    double? customTargetBpm,
    bool clearScenario = false,
    bool clearGeocache = false,
  }) =>
      ForgeSelection(
        themeId: themeId ?? this.themeId,
        genreId: genreId ?? this.genreId,
        scenario: clearScenario ? null : (scenario ?? this.scenario),
        lat: lat ?? this.lat,
        lon: lon ?? this.lon,
        label: label ?? this.label,
        geocacheId: clearGeocache ? null : (geocacheId ?? this.geocacheId),
        seedScrobbles: seedScrobbles ?? this.seedScrobbles,
        consoleMode: consoleMode ?? this.consoleMode,
        customTempC: customTempC ?? this.customTempC,
        customLightPct: customLightPct ?? this.customLightPct,
        customColorKelvin: customColorKelvin ?? this.customColorKelvin,
        customPressureHpa: customPressureHpa ?? this.customPressureHpa,
        customTrendHpa: customTrendHpa ?? this.customTrendHpa,
        customTargetBpm: customTargetBpm ?? this.customTargetBpm,
      );

  ForgeRequest toRequest() {
    final bool isGuided = consoleMode == 'guided';
    final bool isExpert = consoleMode == 'expert';
    return ForgeRequest(
      lat: lat,
      lon: lon,
      themeId: themeId,
      genreId: genreId,
      scenario: scenario,
      geocacheId: geocacheId,
      seedScrobbles: seedScrobbles,
      customTempC: isGuided ? null : customTempC,
      customLightPct: isGuided ? null : customLightPct,
      customColorKelvin: isGuided ? null : customColorKelvin,
      customPressureHpa: isExpert ? customPressureHpa : null,
      customTrendHpa: isExpert ? customTrendHpa : null,
      customTargetBpm: isExpert ? customTargetBpm : null,
    );
  }
}

class ForgeSelectionNotifier extends StateNotifier<ForgeSelection> {
  ForgeSelectionNotifier() : super(const ForgeSelection());

  void setTheme(String? id) => state = state.copyWith(themeId: id);
  void setGenre(String? id) => state = state.copyWith(genreId: id);
  void setScenario(String? id) =>
      state = state.copyWith(scenario: id, clearScenario: id == null);
  void setLocation(double lat, double lon, {String? label, String? geocacheId}) =>
      state = state.copyWith(
        lat: lat,
        lon: lon,
        label: label,
        geocacheId: geocacheId,
        clearGeocache: geocacheId == null,
      );
  void setGeocache(StreetArtGeoCache gc) => state = state.copyWith(
        lat: gc.lat,
        lon: gc.lon,
        label: gc.label,
        geocacheId: gc.id,
        clearScenario: true,
      );
  void setSeedScrobbles(List<String> scrobbles) =>
      state = state.copyWith(seedScrobbles: scrobbles);
  void setConsoleMode(String mode) =>
      state = state.copyWith(consoleMode: mode);
  void setAtmosphericCursors({
    double? tempC,
    double? lightPct,
    double? colorKelvin,
    double? pressureHpa,
    double? trendHpa,
    double? targetBpm,
  }) =>
      state = state.copyWith(
        customTempC: tempC,
        customLightPct: lightPct,
        customColorKelvin: colorKelvin,
        customPressureHpa: pressureHpa,
        customTrendHpa: trendHpa,
        customTargetBpm: targetBpm,
      );
}

final StateNotifierProvider<ForgeSelectionNotifier, ForgeSelection>
    forgeSelectionProvider =
    StateNotifierProvider<ForgeSelectionNotifier, ForgeSelection>(
  (Ref ref) => ForgeSelectionNotifier(),
);

/// The most recent forge result, so the playlist screen has something to show
/// after the home screen triggers a forge.
final StateProvider<ForgeResult?> lastForgeProvider =
    StateProvider<ForgeResult?>((Ref ref) => null);

/// The server-side forge job this client is currently following, if any.
///
/// Lives here rather than in the home screen's State because that is the
/// whole point: the screen can be disposed — navigated away from, rebuilt,
/// dropped by the IndexedStack — and the id survives, so coming back rejoins
/// the run instead of starting a second one. A full page reload does clear
/// it; the home screen recovers from that by asking the backend for any job
/// still active (`activeForgeJobs`).
final StateProvider<String?> forgeJobIdProvider =
    StateProvider<String?>((Ref ref) => null);

/// Currently active track or set in the in-app embedded player.
class ActivePlayerTrack {
  const ActivePlayerTrack({
    required this.title,
    required this.artist,
    this.album,
    this.spotifyUri,
    this.lastfmUrl,
    this.playlistExternalUrl,
    this.index = 0,
    this.total = 1,
  });

  final String title;
  final String artist;
  final String? album;
  final String? spotifyUri;
  final String? lastfmUrl;
  final String? playlistExternalUrl;
  final int index;
  final int total;
}

final StateProvider<ActivePlayerTrack?> activePlayerTrackProvider =
    StateProvider<ActivePlayerTrack?>((Ref ref) => null);

