/// Riverpod wiring. One place, so the dependency graph is readable.
///
/// Kept deliberately small. The interesting state in this app is not held
/// here — it lives in the A2UI surface controllers, which are owned by the
/// screens that fetch them. What is here is the shell: who is signed in, what
/// the backend can currently do, which providers are paired.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'a2ui/actions.dart';
import 'a2ui/catalog.dart';
import 'a2ui/renderer.dart';
import 'api/auth_interceptor.dart';
import 'api/client.dart';
import 'api/models.dart';
import 'auth/auth_service.dart';
import 'auth/pairing_service.dart';

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
    // Re-runs whenever the session changes; a different user has a different
    // set of connections.
    ref.watch(authStateProvider);
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

// ===========================================================================
// Forge selection (shell state, not domain state)
// ===========================================================================

/// What the user has picked in the forge shell. This is the ONE piece of
/// client-held selection state, and it exists only because the pickers need
/// somewhere to keep a value between opening a screen and pressing Forge.
/// The moment the surface stream carries the selection, delete this.
class ForgeSelection {
  const ForgeSelection({
    this.themeId,
    this.genreId,
    this.scenario,
    this.lat = 50.8503,
    this.lon = 4.3517,
  });

  final String? themeId;
  final String? genreId;
  final String? scenario;
  final double? lat;
  final double? lon;

  ForgeSelection copyWith({
    String? themeId,
    String? genreId,
    String? scenario,
    double? lat,
    double? lon,
    bool clearScenario = false,
  }) =>
      ForgeSelection(
        themeId: themeId ?? this.themeId,
        genreId: genreId ?? this.genreId,
        scenario: clearScenario ? null : (scenario ?? this.scenario),
        lat: lat ?? this.lat,
        lon: lon ?? this.lon,
      );

  ForgeRequest toRequest() => ForgeRequest(
        lat: lat,
        lon: lon,
        themeId: themeId,
        genreId: genreId,
        scenario: scenario,
      );
}

class ForgeSelectionNotifier extends StateNotifier<ForgeSelection> {
  ForgeSelectionNotifier() : super(const ForgeSelection());

  void setTheme(String? id) => state = state.copyWith(themeId: id);
  void setGenre(String? id) => state = state.copyWith(genreId: id);
  void setScenario(String? id) =>
      state = state.copyWith(scenario: id, clearScenario: id == null);
  void setLocation(double lat, double lon) =>
      state = state.copyWith(lat: lat, lon: lon);
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

/// Currently active track or set in the in-app embedded player.
class ActivePlayerTrack {
  const ActivePlayerTrack({
    required this.title,
    required this.artist,
    this.album,
    this.spotifyUri,
    this.lastfmUrl,
    this.playlistExternalUrl,
  });

  final String title;
  final String artist;
  final String? album;
  final String? spotifyUri;
  final String? lastfmUrl;
  final String? playlistExternalUrl;
}

final StateProvider<ActivePlayerTrack?> activePlayerTrackProvider =
    StateProvider<ActivePlayerTrack?>((Ref ref) => null);

