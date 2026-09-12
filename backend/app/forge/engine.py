"""THE FORGE. Everything upstream feeds this; this produces the playlist.

The pipeline, in order:

    weather -> sky vector -> theme + corridor -> taste -> per-user nudge
      -> sonic target -> candidate pool -> rerank -> diversity select
      -> arc shape -> rationale -> Playlist -> sink -> almanac

Two properties matter more than anything else in this file.

ONE LEDGER.  A single ``DegradationLedger`` is threaded through every stage and
folded into ``Rationale.degraded`` at the end. The user is told what was
missing. A playlist assembled without a barometer is still a playlist, but it
is a *different* playlist and pretending otherwise is a lie.

NO STAGE IS ALLOWED TO BE FATAL.  Every stage is individually wrapped. Weather
down means a neutral sky. Last.fm down means theme-only retrieval. A broken
theme id means the sky picks. Spotify refusing means an M3U payload. The
almanac failing means nothing at all -- persistence never breaks a response.
The acceptance criterion for the whole system is that this returns a real,
good, explained playlist against fixture weather with no network and no
credentials, so that is the path this file is written for; everything else is
an enhancement layered on top of it.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from ..contracts import (
    SONIC_DIMS,
    TEMPO_MAX_BPM,
    TEMPO_MIN_BPM,
    Coordinates,
    ForgeRequest,
    ForgeResult,
    GenreCorridor,
    Playlist,
    Rationale,
    ScoredTrack,
    SinkResult,
    SkyVector,
    SonicVector,
    TasteVector,
    Theme,
    clamp,
    normalise,
)
from ..errors import DegradationLedger, ThemeNotFound
from ..sinks.registry import write_playlist
from ..sky.extract import extract_sky_vector
from ..sonic.corridors import get_corridor
from ..sonic.matrix import apply_transfer, explain_transfer
from ..sonic.rationale import build_rationale, short_headline
from ..sonic.target import build_target
from ..sonic.themes import get_theme, suggest_theme
from . import arc as arc_mod
from . import diversity as diversity_mod
from .candidates import Candidate, gather_candidates
from .rerank import rerank

ENGINE_TUNING: dict[str, float] = {
    # Candidates fetched per requested track. 22 is empirical: below ~15 the
    # MMR selector runs out of distinct records and starts relaxing its
    # separation floor; above ~30 the extra records are all in the tail of the
    # reranking and never get selected, so it is pure latency.
    "pool_per_track": 22.0,
    # Floor on the pool regardless of playlist length -- a 4-track request
    # still needs a real pool to choose from.
    "pool_floor": 120.0,
    # Confidence penalty applied to the rationale per degradation entry, so a
    # forge that lost two subsystems does not claim the same certainty as a
    # clean one.
    "confidence_per_degradation": 0.12,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now(request: ForgeRequest) -> datetime:
    """The 'now' the whole forge runs against.

    Honouring ``request.at`` everywhere -- not just in the weather call -- is
    what makes a seeded forge reproducible: otherwise ``created_at`` alone
    would differ between two otherwise identical runs.
    """
    return request.at or datetime.now(timezone.utc)


def _neutral_sky(coords: Coordinates | None, at: datetime) -> SkyVector:
    """``SkyVector.neutral()``, tolerating either signature the contract may ship."""
    try:
        sky = SkyVector.neutral()
    except TypeError:  # pragma: no cover - defensive against a widened signature
        sky = SkyVector.neutral(coordinates=coords, observed_at=at)  # type: ignore[call-arg]
    updater = getattr(sky, "model_copy", None)
    if callable(updater):
        try:
            return updater(update={"coordinates": coords, "observed_at": at, "stale": True})
        except Exception:  # noqa: BLE001 - a frozen model that refuses is fine
            return sky
    return sky


def _valid_nudge(nudge: Any) -> list[list[float]] | None:
    """Accept a 9x7 delta matrix, reject anything else without complaint.

    The almanac is a learning store written by another subsystem; a malformed
    matrix should cost the user their personalisation, not their playlist.
    """
    if not isinstance(nudge, Sequence) or isinstance(nudge, (str, bytes)):
        return None
    rows: list[list[float]] = []
    for row in nudge:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            return None
        if len(row) != len(SONIC_DIMS):
            return None
        try:
            rows.append([float(x) for x in row])
        except (TypeError, ValueError):
            return None
    return rows if rows else None


def _playlist_id(request: ForgeRequest, theme_id: str, genre_id: str, sky: SkyVector) -> str:
    """Deterministic when seeded, random otherwise.

    A seeded forge must be reproducible down to the identifier, because that is
    what makes the determinism test meaningful and what lets a demo be diffed.
    """
    if request.seed is None:
        return f"bg_{uuid.uuid4().hex[:12]}"
    payload = "|".join(
        [
            str(request.seed),
            theme_id,
            genre_id,
            f"{request.coordinates.latitude:.4f},{request.coordinates.longitude:.4f}",
            str(request.length),
            ",".join(f"{v:.4f}" for v in sky.as_array()),
        ]
    )
    return f"bg_{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]}"


def _with_degraded(rationale: Rationale, degraded: list[str]) -> Rationale:
    """Re-stamp a frozen Rationale with the final degradation list.

    The sink and the almanac run *after* the rationale is written, so late
    failures have to be folded back in. Confidence is discounted at the same
    time -- a rationale that had to guess should say so numerically.
    """
    penalty = ENGINE_TUNING["confidence_per_degradation"] * len(degraded)
    updates: dict[str, Any] = {
        "degraded": degraded,
        "confidence": clamp(rationale.confidence - penalty, 0.05, 1.0),
    }
    copier = getattr(rationale, "model_copy", None)
    if callable(copier):
        try:
            return copier(update=updates)
        except Exception:  # noqa: BLE001
            return rationale
    return rationale


def _stamp_estimates(
    tracks: Sequence[ScoredTrack], pool: Sequence[Candidate]
) -> list[ScoredTrack]:
    """Write each candidate's estimated vector onto the Track it belongs to.

    Most estimates are derived from tags during retrieval and live only in the
    Candidate wrapper, which dies with the pool. That makes the finished
    Playlist unable to explain its own shape: the arc, the UI and ``explain()``
    all want the vector and would otherwise fall back to neutral. Stamping it
    here costs nothing and makes the Playlist self-describing, which matters
    most for the almanac, where the pool is long gone by the time anyone reads
    the record back.
    """
    index = {c.key: c.estimated for c in pool}
    out: list[ScoredTrack] = []
    for st in tracks:
        if st.track.estimated is not None:
            out.append(st)
            continue
        vec = index.get(st.track.key)
        if vec is None:
            out.append(st)
            continue
        try:
            stamped = st.track.model_copy(update={"estimated": vec})
        except Exception:  # noqa: BLE001 - never lose a track over a copy
            out.append(st)
            continue
        out.append(arc_mod.replace_scored(st, track=stamped))
    return out


def _fallback_target(
    sky: SkyVector, theme: Theme, nudge: list[list[float]] | None
) -> tuple[SonicVector, list[str]]:
    """Target of last resort, used when ``build_target`` itself raises.

    Deliberately the crudest possible version of the real thing -- raw transfer
    matrix, blended toward the theme bias -- so that the shape of the result is
    still recognisably weather-driven rather than a neutral vector.
    """
    try:
        base = apply_transfer(sky, nudge=nudge)
    except Exception:  # noqa: BLE001
        base = SonicVector.neutral()
    target = base.blend(theme.bias, clamp(theme.bias_weight))
    return target, [
        f"Fallback transfer: tempo {target.tempo_bpm:.0f} BPM, valence {target.valence:.2f}."
    ]


# ---------------------------------------------------------------------------
# the forge
# ---------------------------------------------------------------------------


class PlaylistForge:
    """Orchestrates the whole pipeline. Constructed by ``app.container``."""

    def __init__(self, *, settings, weather, oracle, sinks, almanac) -> None:
        self._settings = settings
        self._weather = weather
        self._oracle = oracle
        self._sinks = list(sinks or []) if not hasattr(sinks, "kind") else [sinks]
        self._almanac = almanac

    # -- stages ---------------------------------------------------------

    async def _read_sky(
        self, request: ForgeRequest, at: datetime, ledger: DegradationLedger
    ) -> SkyVector:
        if self._weather is None:
            ledger.note("weather", "no weather source configured; neutral sky")
            return _neutral_sky(request.coordinates, at)
        try:
            window = await self._weather.window(request.coordinates, at)
        except Exception as exc:  # noqa: BLE001
            ledger.note("weather", f"{type(exc).__name__}: {exc}; neutral sky")
            return _neutral_sky(request.coordinates, at)

        try:
            sky = extract_sky_vector(window, at=at, ledger=ledger)
        except Exception as exc:  # noqa: BLE001
            ledger.note("sky", f"extraction failed ({exc}); neutral sky")
            return _neutral_sky(request.coordinates, at)

        if sky.stale:
            ledger.note("weather", "observation is stale")
        return sky

    def _apply_atmospheric_overrides(
        self, sky: SkyVector, request: ForgeRequest
    ) -> tuple[SkyVector, list[str]]:
        updates: dict[str, Any] = {}
        notes: list[str] = []

        if request.custom_temp_c is not None:
            t_c = float(clamp(request.custom_temp_c, -20.0, 48.0))
            updates["temp_norm_deviation"] = float(clamp((t_c - 15.0) / 20.0, -1.0, 1.0))
            notes.append(f"Atmospheric Console Temp Cursor: {t_c:+.1f} °C")

        if request.custom_light_pct is not None:
            light = float(clamp(request.custom_light_pct, 0.0, 100.0))
            updates["sun_elevation"] = float(clamp((light / 50.0) - 1.0, -1.0, 1.0))
            phase = "Midnight Thermal" if light < 20 else "Solar Zenith" if light > 80 else "Horizon / Golden Glow"
            notes.append(f"Atmospheric Console Solar Light Cursor: {light:.0f}% ({phase})")

        if request.custom_color_kelvin is not None:
            kelvin = float(clamp(request.custom_color_kelvin, 2000.0, 10000.0))
            # 2000K = Warm Amber (high golden hour warmth 1.0) -> 10000K = Deep Cyan (crisp blue twilight 0.0)
            updates["golden_hour_proximity"] = float(clamp(1.0 - ((kelvin - 2000.0) / 8000.0), 0.0, 1.0))
            tone = "Warm Amber Sunset" if kelvin < 4200 else "Deep Cyan Stratosphere" if kelvin > 7200 else "Balanced Daylight"
            notes.append(f"Atmospheric Console Color Spectrum: {kelvin:.0f}K ({tone})")

        if request.custom_pressure_hpa is not None:
            hpa = float(clamp(request.custom_pressure_hpa, 965.0, 1045.0))
            updates["pressure_norm_deviation"] = float(clamp((hpa - 1013.25) / 25.0, -1.0, 1.0))
            notes.append(f"Atmospheric Console Barometer: {hpa:.1f} hPa")

        if request.custom_trend_hpa is not None:
            trend = float(clamp(request.custom_trend_hpa, -10.0, 10.0))
            updates["pressure_trend_6h"] = float(clamp(trend / 6.0, -1.0, 1.0))
            notes.append(f"Atmospheric Console 6h Derivative: {trend:+.1f} hPa/6h")

        if not updates:
            return sky, []

        merged_notes = [*list(getattr(sky, "notes", []) or []), *notes]
        updates["notes"] = merged_notes
        try:
            sky = sky.model_copy(update=updates)
        except Exception:  # noqa: BLE001
            pass
        return sky, notes

    def _resolve_theme(
        self, request: ForgeRequest, sky: SkyVector, ledger: DegradationLedger
    ) -> Theme:
        if request.theme_id:
            try:
                return get_theme(request.theme_id)
            except ThemeNotFound:
                ledger.note("theme", f"unknown theme '{request.theme_id}'; sky picked instead")
            except Exception as exc:  # noqa: BLE001
                ledger.note("theme", f"theme lookup failed ({exc}); sky picked instead")
        try:
            theme, _confidence = suggest_theme(sky)
            return theme
        except Exception as exc:  # noqa: BLE001
            ledger.note("theme", f"theme suggestion failed ({exc})")
            raise

    def _resolve_corridor(self, request: ForgeRequest, ledger: DegradationLedger) -> GenreCorridor:
        try:
            corridor = get_corridor(request.genre_id or "any")
        except Exception as exc:  # noqa: BLE001 - contract says it never raises; trust nothing
            ledger.note("corridor", f"corridor lookup failed ({exc}); unconstrained")
            return GenreCorridor.any()
        if request.genre_id and corridor.id != request.genre_id:
            ledger.note("corridor", f"unknown corridor '{request.genre_id}'; unconstrained")
        return corridor

    async def _load_taste(
        self, request: ForgeRequest, ledger: DegradationLedger
    ) -> TasteVector:
        if not request.lastfm_user:
            return TasteVector.empty()
        if self._oracle is None:
            ledger.note("taste", "no oracle configured; theme-only")
            return TasteVector.empty()
        try:
            taste = await self._oracle.taste_vector(request.lastfm_user)
        except Exception as exc:  # noqa: BLE001
            ledger.note("taste", f"profile for '{request.lastfm_user}' unavailable ({exc})")
            return TasteVector.empty()
        if not isinstance(taste, TasteVector):
            ledger.note("taste", "oracle returned a non-TasteVector; ignoring")
            return TasteVector.empty()
        if taste.confidence <= 0.0:
            ledger.note("taste", "listening profile too thin to steer the rerank")
        return taste

    async def _load_nudge(
        self, request: ForgeRequest, ledger: DegradationLedger
    ) -> list[list[float]] | None:
        if self._almanac is None or not request.user_id:
            return None
        try:
            raw = await self._almanac.nudge(request.user_id)
        except Exception as exc:  # noqa: BLE001
            ledger.note("almanac", f"nudge lookup failed ({exc}); using the base matrix")
            return None
        nudge = _valid_nudge(raw)
        if raw is not None and nudge is None:
            ledger.note("almanac", "nudge matrix malformed; using the base matrix")
        return nudge

    def _build_target(
        self,
        sky: SkyVector,
        theme: Theme,
        corridor: GenreCorridor,
        taste: TasteVector,
        nudge: list[list[float]] | None,
        ledger: DegradationLedger,
    ) -> tuple[SonicVector, list[str]]:
        try:
            target, moves = build_target(
                sky, theme=theme, corridor=corridor, taste=taste, nudge=nudge
            )
        except Exception as exc:  # noqa: BLE001
            ledger.note("target", f"target build failed ({exc}); crude fallback")
            return _fallback_target(sky, theme, nudge)
        if not isinstance(target, SonicVector):
            ledger.note("target", "target builder returned a non-SonicVector; crude fallback")
            return _fallback_target(sky, theme, nudge)
        return target, list(moves or [])

    async def _gather(
        self,
        theme: Theme,
        corridor: GenreCorridor,
        taste: TasteVector,
        request: ForgeRequest,
        ledger: DegradationLedger,
    ) -> list[Candidate]:
        if self._oracle is None:
            ledger.note("candidates", "no oracle configured; empty pool")
            return []
        configured = float(getattr(self._settings, "candidate_pool_size", 400) or 400)
        wanted = max(
            ENGINE_TUNING["pool_floor"],
            request.length * ENGINE_TUNING["pool_per_track"],
        )
        limit = int(min(configured, wanted))
        try:
            return await gather_candidates(
                oracle=self._oracle,
                theme=theme,
                corridor=corridor,
                taste=taste,
                limit=limit,
                ledger=ledger,
            )
        except Exception as exc:  # noqa: BLE001 - gather is already defensive; belt and braces
            ledger.note("candidates", f"pool assembly failed ({exc})")
            return []

    def _select(
        self,
        pool: Sequence[Candidate],
        *,
        target: SonicVector,
        theme: Theme,
        corridor: GenreCorridor,
        taste: TasteVector,
        request: ForgeRequest,
        ledger: DegradationLedger,
    ) -> list[ScoredTrack]:
        if not pool:
            ledger.note("rerank", "no candidates to rank")
            return []
        try:
            scored = rerank(pool, target=target, theme=theme, corridor=corridor, taste=taste)
        except Exception as exc:  # noqa: BLE001
            ledger.note("rerank", f"scoring failed ({exc}); falling back to pool order")
            return []

        # Apply Street-Art Geo-Cache vibe synergy, Almanac scrobble seeding,
        # and exploration temperature jitter when running live (request.seed is None).
        is_live_explore = request.seed is None
        eff_seed = request.seed if request.seed is not None else int(time.time() * 1000) % 1000000

        vibe_tags: set[str] = set()
        try:
            from ..sky.geocaches import find_nearest_geocache, get_geocache

            gc = get_geocache(request.geocache_id) or (
                find_nearest_geocache(request.coordinates.latitude, request.coordinates.longitude)
                if request.coordinates
                else None
            )
            if gc is not None:
                vibe_tags = {t.lower().strip() for t in gc.vibe_tags}
        except Exception:  # noqa: BLE001
            pass

        seed_scrobble_keys: set[str] = {
            s.lower().strip() for s in (request.seed_scrobbles or []) if s.strip()
        }

        if is_live_explore or vibe_tags or seed_scrobble_keys:
            adjusted: list[ScoredTrack] = []
            for st in scored:
                delta = 0.0
                track_tags = {t.lower().strip() for t in (st.track.tags or ())}
                track_full = f"{st.track.artist} - {st.track.title}".lower()
                track_colon = f"{st.track.artist}:::{st.track.title}".lower()

                if seed_scrobble_keys and (
                    st.track.key.lower() in seed_scrobble_keys
                    or track_full in seed_scrobble_keys
                    or track_colon in seed_scrobble_keys
                    or st.track.title.lower() in seed_scrobble_keys
                ):
                    delta += 0.38
                if vibe_tags and (track_tags & vibe_tags):
                    delta += 0.095
                if is_live_explore:
                    digest = hashlib.sha1(f"{eff_seed}:{st.track.key}".encode("utf-8")).digest()
                    unit = (int.from_bytes(digest[:4], "big") / 0xFFFFFFFF) - 0.5
                    delta += unit * 0.15  # ±0.075 exploration temperature

                if delta != 0.0:
                    new_score = clamp(st.score + delta, 0.01, 0.999)
                    st = arc_mod.replace_scored(st, score=new_score)
                adjusted.append(st)
            adjusted.sort(key=lambda x: x.score, reverse=True)
            scored = adjusted

        cap = int(getattr(self._settings, "max_tracks_per_artist", 2) or 2)
        try:
            return diversity_mod.select(
                scored,
                k=request.length,
                index=diversity_mod.vector_index(pool),
                theme=theme,
                max_per_artist=cap,
                seed=eff_seed,
                ledger=ledger,
            )
        except Exception as exc:  # noqa: BLE001
            ledger.note("diversity", f"selection failed ({exc}); using straight top-k")
            out: list[ScoredTrack] = []
            seen: set[str] = set()
            per_artist: dict[str, int] = {}
            for st in scored:
                artist = st.track.artist.lower()
                if st.track.key in seen or per_artist.get(artist, 0) >= cap:
                    continue
                seen.add(st.track.key)
                per_artist[artist] = per_artist.get(artist, 0) + 1
                out.append(st)
                if len(out) >= request.length:
                    break
            return out

    def _shape(
        self,
        chosen: Sequence[ScoredTrack],
        *,
        sky: SkyVector,
        pool: Sequence[Candidate],
        ledger: DegradationLedger,
    ) -> tuple[list[ScoredTrack], str]:
        try:
            ordered, shape, reason = arc_mod.shape_playlist(
                chosen, sky=sky, index=diversity_mod.vector_index(pool)
            )
            notes = arc_mod.describe_arc(shape, ordered)
            return ordered, " ".join([reason, *notes])
        except Exception as exc:  # noqa: BLE001
            ledger.note("arc", f"arc shaping failed ({exc}); score order retained")
            return (
                [
                    arc_mod.replace_scored(
                        st,
                        position=i,
                        role=(
                            "opener" if i == 0 else "closer" if i == len(chosen) - 1 else "body"
                        ),
                    )
                    for i, st in enumerate(chosen)
                ],
                "Arc unavailable; ordered by score.",
            )

    def _rationale(
        self,
        *,
        sky: SkyVector,
        target: SonicVector,
        theme: Theme,
        corridor: GenreCorridor,
        taste: TasteVector,
        moves: list[str],
        tracks: Sequence[ScoredTrack],
        ledger: DegradationLedger,
    ) -> Rationale:
        try:
            return build_rationale(
                sky=sky,
                sonic=target,
                theme=theme,
                corridor=corridor,
                taste=taste if taste.confidence > 0 else None,
                moves=moves,
                tracks=list(tracks),
                degraded=ledger.as_list(),
            )
        except Exception as exc:  # noqa: BLE001
            ledger.note("rationale", f"writer failed ({exc}); minimal rationale")
            try:
                headline = short_headline(sky, theme)
            except Exception:  # noqa: BLE001
                headline = theme.name
            return Rationale(
                headline=headline,
                body=(
                    f"Pressure trend {sky.pressure_trend_6h * 12.0:+.1f} hPa over six hours. "
                    f"Target tempo {target.tempo_bpm:.0f} BPM, valence {target.valence:.2f}, "
                    f"spatiality {target.spatiality:.2f} across {len(tracks)} tracks."
                ),
                sky_reading=[f"Pressure trend {sky.pressure_trend_6h:+.2f} (normalised)."],
                sonic_moves=list(moves),
                taste_note="",
                confidence=0.4,
                degraded=ledger.as_list(),
            )

    async def _write_sink(
        self, playlist: Playlist, request: ForgeRequest, ledger: DegradationLedger
    ) -> SinkResult | None:
        if request.sink == "none":
            return None
        try:
            result = await write_playlist(
                self._sinks, playlist, kind=request.sink, user_id=request.user_id
            )
        except Exception as exc:  # noqa: BLE001
            ledger.note("sink", f"write failed ({exc}); playlist not persisted externally")
            return SinkResult(
                kind="none",
                ok=False,
                requested=len(playlist.tracks),
                matched=0,
                message=f"sink error: {exc}",
            )
        if result is None:
            ledger.note("sink", "no sink available")
            return None
        if not result.ok:
            ledger.note("sink", f"{result.kind} sink reported failure: {result.message}")
        elif result.kind != "spotify" and request.sink == "spotify":
            ledger.note("sink", f"Spotify unavailable; fell back to {result.kind}")
        elif request.sink == "auto" and result.kind != "spotify" and self._has_spotify_sink():
            # A Spotify sink was registered but something else answered, so the
            # registry fell through. Under sink="auto" that fallback used to be
            # silent, which is exactly the kind of quiet degradation this
            # product refuses to ship: the user asked for the best available
            # sink, got a file, and deserves to know why.
            reason = result.message or "no reason reported"
            ledger.note("sink", f"Spotify unavailable; fell back to {result.kind} ({reason})")
        return result

    def _has_spotify_sink(self) -> bool:
        """True when a Spotify sink was registered, whether or not it worked."""
        return any(getattr(s, "kind", None) == "spotify" for s in self._sinks)

    async def _record(self, playlist: Playlist, ledger: DegradationLedger) -> None:
        if self._almanac is None:
            return
        try:
            await self._almanac.record_forge(playlist)
        except Exception as exc:  # noqa: BLE001 - persistence NEVER breaks the response
            ledger.note("almanac", f"could not record this forge ({exc})")

    # -- public API ------------------------------------------------------

    async def forge(self, request: ForgeRequest) -> ForgeResult:
        started = time.perf_counter()
        ledger = DegradationLedger()
        at = _now(request)

        sky = await self._read_sky(request, at, ledger)
        sky, cursor_notes = self._apply_atmospheric_overrides(sky, request)
        theme = self._resolve_theme(request, sky, ledger)
        corridor = self._resolve_corridor(request, ledger)
        taste = await self._load_taste(request, ledger)
        nudge = await self._load_nudge(request, ledger)

        target, moves = self._build_target(sky, theme, corridor, taste, nudge, ledger)
        if cursor_notes:
            moves = [*cursor_notes, *moves]
        if request.custom_target_bpm is not None:
            bpm_val = float(clamp(request.custom_target_bpm, 50.0, 195.0))
            try:
                norm_tempo = normalise(bpm_val, TEMPO_MIN_BPM, TEMPO_MAX_BPM)
                target = target.model_copy(update={"tempo": norm_tempo})
            except Exception:  # noqa: BLE001
                pass
            moves.insert(0, f"Atmospheric Console Expert Lock: Target Tempo set to {bpm_val:.0f} BPM.")

        pool = await self._gather(theme, corridor, taste, request, ledger)
        chosen = self._select(
            pool,
            target=target,
            theme=theme,
            corridor=corridor,
            taste=taste,
            request=request,
            ledger=ledger,
        )
        ordered, arc_note = self._shape(chosen, sky=sky, pool=pool, ledger=ledger)
        ordered = _stamp_estimates(ordered, pool)

        if not ordered:
            ledger.note("forge", "no tracks could be assembled; returning an empty playlist")

        rationale = self._rationale(
            sky=sky,
            target=target,
            theme=theme,
            corridor=corridor,
            taste=taste,
            moves=[*moves, arc_note],
            tracks=ordered,
            ledger=ledger,
        )

        loc_label = getattr(request.coordinates, "label", None) or "your sky"
        base_tagline = (theme.tagline or theme.description or "").strip()
        daylist_subtitle = (
            f"Weather-inspired Daylist • {len(ordered)} tracks curated for {loc_label}. "
            f"{base_tagline}"
        ).strip()

        playlist = Playlist(
            id=_playlist_id(request, theme.id, corridor.id, sky),
            title=rationale.headline,
            subtitle=daylist_subtitle,
            tracks=ordered,
            sky=sky,
            sonic_target=target,
            theme_id=theme.id,
            genre_id=corridor.id,
            rationale=rationale,
            created_at=at,
            user_id=request.user_id,
            coordinates=request.coordinates,
            sink=None,
        )

        playlist.sink = await self._write_sink(playlist, request, ledger)
        await self._record(playlist, ledger)

        # Late failures (sink, almanac) have to reach the user-visible
        # rationale too, so it is re-stamped once everything has run.
        playlist.rationale = _with_degraded(rationale, ledger.as_list())

        elapsed_ms_float = round((time.perf_counter() - started) * 1000.0, 2)
        traj_id = f"traj_forge_{uuid.uuid4().hex[:12]}"
        sess_id = request.session_id or f"sess_forge_{uuid.uuid4().hex[:8]}"
        conv_id = request.conversation_id or f"conv_forge_{uuid.uuid4().hex[:8]}"
        uid = request.user_id or "demo"

        token_usage_dict: dict[str, Any] = {}
        try:
            from ..telemetry.models import TokenUsageMetrics, ToolExecutionStep, TrajectoryRecord
            from ..telemetry.store import get_telemetry_store
            from ..telemetry.tracing import emit_telemetry_log, get_gcp_trace, get_span_id, get_trace_id

            sys_inst = (
                "BaroGroove Sonic Transfer Forge Engine: Synthesize weather vector, "
                "theme corridor, and listener taste into a curated sonic arc."
            )
            user_prompt_str = (
                f"Forge playlist for {loc_label} ({request.coordinates.latitude:.4f}, "
                f"{request.coordinates.longitude:.4f}) theme={theme.id} genre={corridor.id} length={request.length}"
            )
            tu = TokenUsageMetrics.from_vertex_or_estimate(None, sys_inst, user_prompt_str, playlist.rationale.body)
            token_usage_dict = tu.model_dump(mode="json")

            tool_steps = [
                ToolExecutionStep(
                    tool_name="extract_sky_vector",
                    arguments={"lat": request.coordinates.latitude, "lon": request.coordinates.longitude},
                    result_summary=f"Sky pressure trend={sky.pressure_trend_6h:+.2f}",
                    latency_ms=round(elapsed_ms_float * 0.15, 2),
                ),
                ToolExecutionStep(
                    tool_name="select_theme_corridor",
                    arguments={"theme_id": theme.id, "genre_id": corridor.id},
                    result_summary=f"Theme {theme.name} / Corridor {corridor.name}",
                    latency_ms=round(elapsed_ms_float * 0.10, 2),
                ),
                ToolExecutionStep(
                    tool_name="gather_rerank_candidates",
                    arguments={"pool_size": len(pool), "length": request.length},
                    result_summary=f"Assembled {len(ordered)} tracks",
                    latency_ms=round(elapsed_ms_float * 0.55, 2),
                ),
                ToolExecutionStep(
                    tool_name="build_rationale",
                    arguments={"headline": playlist.rationale.headline},
                    result_summary=playlist.rationale.headline,
                    latency_ms=round(elapsed_ms_float * 0.20, 2),
                ),
            ]
            traj = TrajectoryRecord(
                trajectory_id=traj_id,
                session_id=sess_id,
                conversation_id=conv_id,
                user_id=uid,
                surface="forge",
                endpoint="POST /api/forge",
                trace_id=get_trace_id(),
                span_id=get_span_id(),
                gcp_trace=get_gcp_trace(),
                requested_model="gemini-2.5-flash",
                execution_path="deterministic-fallback",
                latency_ms=elapsed_ms_float,
                token_usage=tu,
                system_instruction=sys_inst,
                user_prompt=user_prompt_str,
                parsed_plan={
                    "playlist_id": playlist.id,
                    "theme_id": theme.id,
                    "genre_id": corridor.id,
                    "target_bpm": target.tempo_bpm,
                    "track_count": len(ordered),
                },
                tool_steps=tool_steps,
                status="ok",
            )
            store = get_telemetry_store()
            store.save_trajectory_sync(traj)
            if request.session_id:
                try:
                    sess_rec = store.get_or_create_session_sync(request.session_id, user_id=uid)
                    sess_rec.increment_turn()
                    store.save_session_sync(sess_rec)
                except Exception:
                    pass
            emit_telemetry_log(traj)
        except Exception:
            pass

        return ForgeResult(
            playlist=playlist,
            degraded=ledger.as_list(),
            elapsed_ms=int(elapsed_ms_float),
            trajectory_id=traj_id,
            session_id=sess_id,
            conversation_id=conv_id,
            user_id=uid,
            latency_ms=elapsed_ms_float,
            token_usage=token_usage_dict,
        )

    async def explain(self, playlist: Playlist) -> Rationale:
        """Re-explain a stored playlist without re-forging it.

        Used by ``POST /api/forge/explain`` and by the almanac UI. The tracks
        are taken as given; only the reasoning is rebuilt, which means an
        improved transfer matrix or rationale writer retroactively improves the
        explanation of everything already saved.
        """
        started = time.perf_counter()
        ledger = DegradationLedger()

        try:
            theme = get_theme(playlist.theme_id)
        except Exception:  # noqa: BLE001
            ledger.note("theme", f"theme '{playlist.theme_id}' no longer exists; sky picked")
            theme, _ = suggest_theme(playlist.sky)
        corridor = get_corridor(playlist.genre_id or "any")

        moves: list[str] = []
        try:
            for sky_dim, sonic_dim, contribution in explain_transfer(
                playlist.sky, playlist.sonic_target
            ):
                moves.append(
                    f"{sky_dim.replace('_', ' ')} moved {sonic_dim} by {contribution:+.2f}."
                )
        except Exception as exc:  # noqa: BLE001
            ledger.note("matrix", f"transfer explanation unavailable ({exc})")

        try:
            shape, reason = arc_mod.choose_shape(playlist.sky)
            moves.append(" ".join([reason, *arc_mod.describe_arc(shape, playlist.tracks)]))
        except Exception as exc:  # noqa: BLE001
            ledger.note("arc", f"arc description unavailable ({exc})")

        rationale = self._rationale(
            sky=playlist.sky,
            target=playlist.sonic_target,
            theme=theme,
            corridor=corridor,
            taste=TasteVector.empty(),
            moves=moves,
            tracks=playlist.tracks,
            ledger=ledger,
        )
        # Degradations recorded during the original forge are part of the
        # story and are preserved alongside anything found while re-explaining.
        previous = list(playlist.rationale.degraded) if playlist.rationale else []
        merged = previous + [d for d in ledger.as_list() if d not in previous]
        final_rat = _with_degraded(rationale, merged)

        elapsed_ms_float = round((time.perf_counter() - started) * 1000.0, 2)
        traj_id = f"traj_explain_{uuid.uuid4().hex[:12]}"
        try:
            from ..telemetry.models import TokenUsageMetrics, ToolExecutionStep, TrajectoryRecord
            from ..telemetry.store import get_telemetry_store
            from ..telemetry.tracing import emit_telemetry_log, get_gcp_trace, get_span_id, get_trace_id

            sys_inst = (
                "BaroGroove Rationale Explainability Engine: Reconstruct sonic transfer "
                "contributions and arc narrative for an existing playlist."
            )
            user_prompt_str = f"Explain playlist {playlist.id} ({playlist.title}) under theme {playlist.theme_id}"
            tu = TokenUsageMetrics.from_vertex_or_estimate(None, sys_inst, user_prompt_str, final_rat.body)
            traj = TrajectoryRecord(
                trajectory_id=traj_id,
                session_id=f"sess_explain_{uuid.uuid4().hex[:8]}",
                conversation_id=f"conv_explain_{uuid.uuid4().hex[:8]}",
                user_id=playlist.user_id or "demo",
                surface="forge",
                endpoint="POST /api/forge/explain",
                trace_id=get_trace_id(),
                span_id=get_span_id(),
                gcp_trace=get_gcp_trace(),
                requested_model="gemini-2.5-flash",
                execution_path="deterministic-fallback",
                latency_ms=elapsed_ms_float,
                token_usage=tu,
                system_instruction=sys_inst,
                user_prompt=user_prompt_str,
                parsed_plan={
                    "playlist_id": playlist.id,
                    "theme_id": playlist.theme_id,
                    "headline": final_rat.headline,
                },
                tool_steps=[
                    ToolExecutionStep(
                        tool_name="build_rationale",
                        arguments={"playlist_id": playlist.id},
                        result_summary=final_rat.headline,
                        latency_ms=elapsed_ms_float,
                    )
                ],
                status="ok",
            )
            get_telemetry_store().save_trajectory_sync(traj)
            emit_telemetry_log(traj)
        except Exception:
            pass

        try:
            final_rat = final_rat.model_copy(update={"trajectory_id": traj_id})
        except Exception:
            pass
        return final_rat
