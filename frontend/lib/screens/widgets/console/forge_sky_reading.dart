/// The three values the Forge shows at a glance (`docs/UX_IA_SPEC.md` §3.1),
/// lifted out of the A2UI `sky` surface's data model.
///
/// The backend owns the sky: the strip never computes weather, it only reads
/// what `build_sky_surface()` already published (`/sky/heroDisplay`,
/// `/sky/dimensions[*].display`). If the surface has not arrived — offline, or
/// the backend is unreachable — every field is null and the UI says so instead
/// of inventing a number (§2 rule 4).
class ForgeSkyReading {
  const ForgeSkyReading({
    this.trendDisplay,
    this.trendTone,
    this.trendCaption,
    this.tempDisplay,
    this.lightDisplay,
    this.stale = false,
  });

  /// Formatted hero value, e.g. `-2.4 hPa`.
  final String? trendDisplay;

  /// The backend's own verdict on the hero: `falling` | `steady` | `rising`.
  /// Guided phrases its outcome from this rather than re-deciding client-side
  /// what "falling" means.
  final String? trendTone;

  /// The backend's own one-word reading of the hero, e.g. `falling fast`.
  final String? trendCaption;

  /// Temperature versus the local norm, formatted by the backend.
  final String? tempDisplay;

  /// Sun elevation, formatted by the backend.
  final String? lightDisplay;

  /// The surface told us the observation is old.
  final bool stale;

  /// Nothing to show at all — the surface never arrived.
  bool get isEmpty =>
      trendDisplay == null && tempDisplay == null && lightDisplay == null;

  static const ForgeSkyReading unavailable = ForgeSkyReading();
}
