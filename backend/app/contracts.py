"""BAROGROOVE shared contracts.

This module is the treaty. Every other module in the codebase imports its
types from here and nothing flies between modules as a bare dict. If you are
about to add a `dict[str, Any]` to a function signature, add a model here
instead.

Two vector spaces and the map between them:

    SkyVector (9 dims)  --[transfer matrix]-->  SonicVector (7 dims)

Both are *normalised*. The SkyVector is deliberately derivative-first: it
encodes how the weather is *changing*, not what it is. See
``backend/app/sonic/matrix.py`` for why that matters.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Literal, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

__all__ = [
    "SKY_DIMS",
    "SONIC_DIMS",
    "TEMPO_MIN_BPM",
    "TEMPO_MAX_BPM",
    "ThemeId",
    "Coordinates",
    "WeatherObservation",
    "WeatherWindow",
    "SkyVector",
    "SonicVector",
    "TasteVector",
    "Theme",
    "GenreCorridor",
    "ArtistRef",
    "Track",
    "ScoredTrack",
    "TrackRole",
    "Rationale",
    "Playlist",
    "ForgeRequest",
    "ForgeResult",
    "SinkKind",
    "SinkResult",
    "PlaylistSink",
    "AcousticOracle",
    "WeatherSource",
    "AlmanacStore",
    "clamp",
    "lerp",
    "normalise",
]

# --------------------------------------------------------------------------
# Dimension names. Order is load-bearing: the transfer matrix is indexed by it.
# --------------------------------------------------------------------------

SKY_DIMS: tuple[str, ...] = (
    "pressure_trend_6h",
    "pressure_norm_deviation",
    "temp_norm_deviation",
    "sun_elevation",
    "golden_hour_proximity",
    "gust_variance",
    "cloud_depth",
    "precip_intensity",
    "daylight_delta",
)

SONIC_DIMS: tuple[str, ...] = (
    "valence",
    "energy",
    "tempo",
    "acousticness",
    "density",
    "grit",
    "spatiality",
)

TEMPO_MIN_BPM: float = 60.0
TEMPO_MAX_BPM: float = 180.0

ThemeId = Literal[
    "petrichor",
    "golden_hour",
    "nordic_fog",
    "storm_front",
    "heatwave_cruise",
    "blue_hour",
    "first_frost",
    "sirocco",
]

THEME_IDS: tuple[str, ...] = (
    "petrichor",
    "golden_hour",
    "nordic_fog",
    "storm_front",
    "heatwave_cruise",
    "blue_hour",
    "first_frost",
    "sirocco",
)


# --------------------------------------------------------------------------
# Small numeric helpers. Shared so that every module clamps identically.
# --------------------------------------------------------------------------


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp ``value`` into ``[low, high]``. NaN degrades to ``low``."""
    if value != value:  # NaN
        return low
    return max(low, min(high, value))


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation, ``t`` clamped to [0, 1]."""
    t = clamp(t)
    return a + (b - a) * t


def normalise(value: float, low: float, high: float, *, signed: bool = False) -> float:
    """Map ``value`` from ``[low, high]`` onto ``[0, 1]`` (or ``[-1, 1]``).

    Values outside the range saturate rather than explode — a 40 hPa pressure
    crash is still just "as falling as it gets".
    """
    if high == low:
        return 0.0
    unit = (value - low) / (high - low)
    if signed:
        return clamp(unit * 2.0 - 1.0, -1.0, 1.0)
    return clamp(unit, 0.0, 1.0)


def _soft_sign(value: float, scale: float) -> float:
    """Squash an unbounded signed quantity into (-1, 1) with a tanh knee."""
    if scale <= 0:
        return 0.0
    return math.tanh(value / scale)


# --------------------------------------------------------------------------
# Geography & raw weather
# --------------------------------------------------------------------------


class Coordinates(BaseModel):
    """A place on the planet, plus the timezone we should reason in."""

    model_config = ConfigDict(frozen=True)

    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    timezone: str = "auto"
    label: str | None = None

    def geohash(self, precision: int = 5) -> str:
        """Geohash for cache keying. Precision 5 ≈ 4.9 km, plenty for weather."""
        alphabet = "0123456789bcdefghjkmnpqrstuvwxyz"
        lat_lo, lat_hi = -90.0, 90.0
        lon_lo, lon_hi = -180.0, 180.0
        out: list[str] = []
        bits = 0
        bit = 0
        even = True
        while len(out) < precision:
            if even:
                mid = (lon_lo + lon_hi) / 2
                if self.longitude > mid:
                    bits = (bits << 1) | 1
                    lon_lo = mid
                else:
                    bits <<= 1
                    lon_hi = mid
            else:
                mid = (lat_lo + lat_hi) / 2
                if self.latitude > mid:
                    bits = (bits << 1) | 1
                    lat_lo = mid
                else:
                    bits <<= 1
                    lat_hi = mid
            even = not even
            bit += 1
            if bit == 5:
                out.append(alphabet[bits])
                bits = 0
                bit = 0
        return "".join(out)


class WeatherObservation(BaseModel):
    """One hourly row as Open-Meteo hands it to us, already unit-normalised."""

    model_config = ConfigDict(frozen=True)

    time: _dt.datetime
    temperature_2m: float | None = None
    apparent_temperature: float | None = None
    surface_pressure: float | None = None
    pressure_msl: float | None = None
    cloud_cover: float | None = None
    precipitation: float | None = None
    wind_gusts_10m: float | None = None
    relative_humidity_2m: float | None = None

    @property
    def pressure(self) -> float | None:
        """Prefer station pressure; fall back to sea-level reduced."""
        return self.surface_pressure if self.surface_pressure is not None else self.pressure_msl


class WeatherWindow(BaseModel):
    """Everything the SkyVector extractor needs, in one immutable bundle.

    ``history`` runs oldest→newest and includes ``past_days`` so we can compute
    both the 6-hour derivative and the 7-day local norm. ``now`` is the
    observation we are treating as the present moment.
    """

    coordinates: Coordinates
    generated_at: _dt.datetime
    now: WeatherObservation
    history: list[WeatherObservation] = Field(default_factory=list)
    sunrise: _dt.datetime | None = None
    sunset: _dt.datetime | None = None
    daylight_seconds: float | None = None
    daylight_seconds_yesterday: float | None = None
    stale: bool = False
    source: str = "open-meteo"


# --------------------------------------------------------------------------
# SkyVector — 9 normalised, derivative-first dimensions
# --------------------------------------------------------------------------


class SkyVector(BaseModel):
    """The sky, reduced to nine numbers that a matrix can multiply.

    Signed dims live in ``[-1, 1]``; unsigned dims live in ``[0, 1]``.
    Every field carries its physical meaning in the description so the
    rationale generator can talk about it without a second lookup table.
    """

    model_config = ConfigDict(frozen=True)

    # --- signed: [-1, 1] ---------------------------------------------------
    pressure_trend_6h: float = Field(
        0.0, ge=-1.0, le=1.0,
        description="Δ surface pressure over the last 6h. -1 = crashing (≈ -12 hPa), +1 = building.",
    )
    pressure_norm_deviation: float = Field(
        0.0, ge=-1.0, le=1.0,
        description="Current pressure vs this location's own 7-day mean. -1 = deep low for here.",
    )
    temp_norm_deviation: float = Field(
        0.0, ge=-1.0, le=1.0,
        description="Apparent temp vs this location's 7-day mean. -1 = unseasonably raw.",
    )
    sun_elevation: float = Field(
        0.0, ge=-1.0, le=1.0,
        description="Solar elevation normalised. -1 = solar midnight, 0 = horizon, +1 = zenith.",
    )
    daylight_delta: float = Field(
        0.0, ge=-1.0, le=1.0,
        description="Day length vs yesterday. Negative = the year is closing in.",
    )

    # --- unsigned: [0, 1] --------------------------------------------------
    golden_hour_proximity: float = Field(
        0.0, ge=0.0, le=1.0,
        description="1.0 at golden hour, decaying over ±90 min around sunrise/sunset.",
    )
    gust_variance: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Spread of wind gusts over 6h. High = the air is nervous, not merely windy.",
    )
    cloud_depth: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Cloud cover weighted by humidity — the difference between haze and a lid.",
    )
    precip_intensity: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Precipitation rate, log-compressed. 0.5 ≈ steady rain, 1.0 ≈ downpour.",
    )

    # --- provenance --------------------------------------------------------
    observed_at: _dt.datetime | None = None
    coordinates: Coordinates | None = None
    stale: bool = Field(False, description="True when we served last-known-good after a fetch failure.")
    notes: list[str] = Field(default_factory=list, description="Human-readable extraction breadcrumbs.")

    def as_array(self) -> list[float]:
        """Dimension values in ``SKY_DIMS`` order. This is the matrix input."""
        return [getattr(self, dim) for dim in SKY_DIMS]

    def as_dict(self) -> dict[str, float]:
        return {dim: getattr(self, dim) for dim in SKY_DIMS}

    @classmethod
    def neutral(cls) -> "SkyVector":
        """A perfectly boring sky. Useful as a fallback and in tests."""
        return cls(notes=["neutral fallback sky"])

    @classmethod
    def from_array(cls, values: Sequence[float], **extra: Any) -> "SkyVector":
        if len(values) != len(SKY_DIMS):
            raise ValueError(f"SkyVector needs {len(SKY_DIMS)} values, got {len(values)}")
        signed = {"pressure_trend_6h", "pressure_norm_deviation", "temp_norm_deviation",
                  "sun_elevation", "daylight_delta"}
        payload: dict[str, Any] = {}
        for dim, raw in zip(SKY_DIMS, values):
            payload[dim] = clamp(raw, -1.0, 1.0) if dim in signed else clamp(raw, 0.0, 1.0)
        payload.update(extra)
        return cls(**payload)


# --------------------------------------------------------------------------
# SonicVector — 7 normalised musical dimensions
# --------------------------------------------------------------------------


class SonicVector(BaseModel):
    """The target *feeling*, in seven dimensions we can actually shop for.

    These deliberately mirror what Spotify's ``/audio-features`` used to give
    us, plus three we always wished it had (``density``, ``grit``,
    ``spatiality``). We reconstruct all seven from Last.fm's tag vocabulary —
    see ``backend/app/lastfm/lexicon.py``.
    """

    model_config = ConfigDict(frozen=True)

    valence: float = Field(0.5, ge=0.0, le=1.0, description="Emotional brightness. 0 = desolate, 1 = elated.")
    energy: float = Field(0.5, ge=0.0, le=1.0, description="Perceived intensity and drive.")
    tempo: float = Field(0.5, ge=0.0, le=1.0, description=f"Normalised BPM across [{TEMPO_MIN_BPM}, {TEMPO_MAX_BPM}].")
    acousticness: float = Field(0.5, ge=0.0, le=1.0, description="Wood and air vs silicon and voltage.")
    density: float = Field(0.5, ge=0.0, le=1.0, description="Events per bar. 0 = one note held, 1 = wall of information.")
    grit: float = Field(0.5, ge=0.0, le=1.0, description="Distortion, tape hiss, noise floor. Texture, not volume.")
    spatiality: float = Field(0.5, ge=0.0, le=1.0, description="Reverb and stereo depth. 0 = dry and close, 1 = cathedral.")

    def as_array(self) -> list[float]:
        return [getattr(self, dim) for dim in SONIC_DIMS]

    def as_dict(self) -> dict[str, float]:
        return {dim: getattr(self, dim) for dim in SONIC_DIMS}

    @computed_field
    @property
    def tempo_bpm(self) -> float:
        """Denormalised tempo, because humans say '94 BPM', not '0.28'."""
        return round(lerp(TEMPO_MIN_BPM, TEMPO_MAX_BPM, self.tempo), 1)

    @classmethod
    def from_bpm(cls, bpm: float, **kwargs: Any) -> "SonicVector":
        return cls(tempo=normalise(bpm, TEMPO_MIN_BPM, TEMPO_MAX_BPM), **kwargs)

    @classmethod
    def neutral(cls) -> "SonicVector":
        return cls()

    @classmethod
    def from_array(cls, values: Sequence[float]) -> "SonicVector":
        if len(values) != len(SONIC_DIMS):
            raise ValueError(f"SonicVector needs {len(SONIC_DIMS)} values, got {len(values)}")
        return cls(**{dim: clamp(v) for dim, v in zip(SONIC_DIMS, values)})

    def blend(self, other: "SonicVector", weight: float) -> "SonicVector":
        """Move ``weight`` of the way from self toward ``other``."""
        w = clamp(weight)
        return SonicVector.from_array(
            [lerp(a, b, w) for a, b in zip(self.as_array(), other.as_array())]
        )

    def distance(self, other: "SonicVector", weights: Sequence[float] | None = None) -> float:
        """Weighted euclidean distance, normalised to roughly [0, 1]."""
        w = list(weights) if weights else [1.0] * len(SONIC_DIMS)
        total = sum(wi * (a - b) ** 2 for wi, a, b in zip(w, self.as_array(), other.as_array()))
        denom = sum(w) or 1.0
        return math.sqrt(total / denom)


class TasteVector(BaseModel):
    """What the user actually listens to, in SonicVector space plus tags.

    Built from Last.fm scrobbles. ``confidence`` drops toward 0 when we have
    thin data, and the forge leans harder on the theme when it does.
    """

    model_config = ConfigDict(frozen=True)

    centroid: SonicVector = Field(default_factory=SonicVector.neutral)
    spread: SonicVector = Field(default_factory=SonicVector.neutral)
    top_tags: dict[str, float] = Field(default_factory=dict, description="tag -> normalised affinity 0..1")
    top_artists: list[str] = Field(default_factory=list)
    scrobble_count: int = 0
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    source: str = "lastfm"

    @classmethod
    def empty(cls) -> "TasteVector":
        return cls(confidence=0.0, source="none")


# --------------------------------------------------------------------------
# Themes & genre corridor
# --------------------------------------------------------------------------


class Theme(BaseModel):
    """A narrative lens. Bias vector + copy voice + palette.

    A theme does not *replace* the weather reading — it bends it. Petrichor on
    a rising barometer is still a brighter record than Petrichor in a collapse.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    tagline: str
    description: str
    bias: SonicVector = Field(description="Where this theme pulls the target vector.")
    bias_weight: float = Field(0.35, ge=0.0, le=1.0, description="How hard the theme pulls.")
    seed_tags: list[str] = Field(default_factory=list, description="Last.fm tags this theme fishes in.")
    avoid_tags: list[str] = Field(default_factory=list)
    palette: dict[str, str] = Field(default_factory=dict, description="Hex colours for the A2UI surface.")
    voice: str = Field("dry", description="Copy register for the rationale generator.")
    affinity: dict[str, float] = Field(
        default_factory=dict,
        description="SkyVector dim -> weight. Used to auto-suggest a theme for the current sky.",
    )


class GenreCorridor(BaseModel):
    """An orthogonal taste knob. Themes say *how it feels*; this says *what shelf*.

    Crossing a theme with a corridor is the point: 'Petrichor × krautrock' must
    not collapse into the same playlist as 'Petrichor × ambient'.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    tags: list[str] = Field(default_factory=list, description="Last.fm tags defining the corridor.")
    anchor: SonicVector | None = Field(None, description="Optional centre of mass for the genre.")
    width: float = Field(0.5, ge=0.05, le=1.0, description="How far outside the corridor we may wander.")
    description: str = ""

    @classmethod
    def any(cls) -> "GenreCorridor":
        return cls(id="any", name="No corridor", tags=[], width=1.0,
                   description="Whatever the sky and your scrobbles want.")


# --------------------------------------------------------------------------
# Tracks & playlists
# --------------------------------------------------------------------------


class ArtistRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    mbid: str | None = None
    lastfm_url: str | None = None
    spotify_id: str | None = None


class Track(BaseModel):
    """A song, provider-agnostic. Spotify IDs are optional decoration."""

    model_config = ConfigDict(frozen=True)

    title: str
    artist: str
    mbid: str | None = None
    lastfm_url: str | None = None
    spotify_id: str | None = None
    spotify_uri: str | None = None
    album: str | None = None
    duration_ms: int | None = None
    tags: list[str] = Field(default_factory=list)
    estimated: SonicVector | None = Field(
        None, description="Sonic estimate from the tag lexicon. None = unscored candidate."
    )
    listeners: int | None = None
    playcount: int | None = None

    @property
    def key(self) -> str:
        """Dedupe key. Case/punctuation-insensitive artist+title."""
        def _norm(s: str) -> str:
            return "".join(ch for ch in s.lower() if ch.isalnum() or ch == " ").strip()
        return f"{_norm(self.artist)}|{_norm(self.title)}"

    @property
    def display(self) -> str:
        return f"{self.artist} — {self.title}"


TrackRole = Literal["opener", "build", "peak", "descent", "closer", "body"]


class ScoredTrack(BaseModel):
    """A candidate with its arithmetic attached, so the UI can show its work."""

    model_config = ConfigDict(frozen=True)

    track: Track
    score: float = 0.0
    sonic_distance: float = 1.0
    taste_affinity: float = 0.0
    corridor_fit: float = 0.0
    novelty: float = 0.0
    role: TrackRole = "body"
    position: int = 0
    why: str = Field("", description="One line on why this track survived the rerank.")


class Rationale(BaseModel):
    """The hero card. If this is boring, the whole product is boring."""

    model_config = ConfigDict(frozen=True)

    headline: str
    body: str
    sky_reading: list[str] = Field(default_factory=list, description="Bullet observations about the sky.")
    sonic_moves: list[str] = Field(default_factory=list, description="What we did to the target vector and why.")
    taste_note: str = ""
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    degraded: list[str] = Field(default_factory=list, description="Which upstreams were down, in plain words.")
    trajectory_id: str | None = None


class Playlist(BaseModel):
    """The output artefact. Everything needed to render, save and explain it."""

    id: str
    title: str
    subtitle: str = ""
    tracks: list[ScoredTrack] = Field(default_factory=list)
    sky: SkyVector
    sonic_target: SonicVector
    theme_id: str
    genre_id: str = "any"
    rationale: Rationale
    created_at: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc))
    user_id: str | None = None
    coordinates: Coordinates | None = None
    sink: "SinkResult | None" = None

    @property
    def duration_ms(self) -> int:
        return sum(t.track.duration_ms or 0 for t in self.tracks)

    def plain_tracks(self) -> list[Track]:
        return [t.track for t in self.tracks]


class ForgeRequest(BaseModel):
    """Everything the forge needs. No hidden globals."""

    coordinates: Coordinates = Field(
        default_factory=lambda: Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels")
    )
    theme_id: str | None = Field(None, description="None = let the sky pick a theme.")
    genre_id: str = "any"
    length: int = Field(18, ge=4, le=60)
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    lastfm_user: str | None = None
    sink: "SinkKind" = "auto"
    at: _dt.datetime | None = Field(None, description="Override 'now' — used by fixtures and the Almanac.")
    seed: int | None = Field(None, description="Deterministic diversity shuffling for tests.")
    geocache_id: str | None = Field(None, description="Optional World Street-Art Geo-Cache ID or 'random'.")
    seed_scrobbles: list[str] = Field(
        default_factory=list,
        description="Optional scrobble keys or titles ('Artist - Title') selected from Almanac to seed the set.",
    )
    custom_temp_c: float | None = Field(None, description="Manual temperature override in °C (-15 to 42).")
    custom_light_pct: float | None = Field(None, description="Manual solar luminance override in % (0 to 100).")
    custom_color_kelvin: float | None = Field(
        None, description="Manual sky color spectrum override in Kelvin (2000K Warm Amber to 10000K Deep Cyan)."
    )
    custom_pressure_hpa: float | None = Field(None, description="Manual barometric pressure override in hPa (975 to 1040).")
    custom_trend_hpa: float | None = Field(None, description="Manual 6h pressure derivative override in hPa/6h (-6 to +6).")
    custom_target_bpm: float | None = Field(None, description="Manual target BPM override (60 to 165).")

    @model_validator(mode="before")
    @classmethod
    def _coerce_frontend_shape(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        gc_id = out.get("geocache_id")
        if gc_id:
            try:
                from .sky.geocaches import get_geocache

                gc = get_geocache(str(gc_id))
                if gc is not None:
                    out["geocache_id"] = gc.id
                    out["coordinates"] = {
                        "latitude": gc.lat,
                        "longitude": gc.lon,
                        "label": gc.label,
                    }
            except Exception:  # noqa: BLE001
                pass
        if "coordinates" not in out or out["coordinates"] is None:
            lat = out.pop("lat", None)
            lon = out.pop("lon", None)
            if lat is not None and lon is not None:
                out["coordinates"] = {"latitude": float(lat), "longitude": float(lon)}
            else:
                out["coordinates"] = {"latitude": 50.8503, "longitude": 4.3517, "label": "Brussels"}
        if "track_count" in out and "length" not in out:
            out["length"] = out.pop("track_count")
        if out.get("genre_id") is None:
            out["genre_id"] = "any"
        return out


class ForgeResult(BaseModel):
    playlist: Playlist
    degraded: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0
    trajectory_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None
    latency_ms: float | None = None
    token_usage: dict[str, Any] | None = None


SinkKind = Literal["auto", "spotify", "m3u", "none"]


class SinkResult(BaseModel):
    """What happened when we tried to write the playlist somewhere real."""

    model_config = ConfigDict(frozen=True)

    kind: SinkKind
    ok: bool
    external_id: str | None = None
    external_url: str | None = None
    matched: int = 0
    requested: int = 0
    unmatched: list[str] = Field(default_factory=list)
    payload: str | None = Field(None, description="For the M3U sink: the file body itself.")
    message: str = ""


Playlist.model_rebuild()
ForgeRequest.model_rebuild()


# --------------------------------------------------------------------------
# Protocols — the seams workers build against
# --------------------------------------------------------------------------


@runtime_checkable
class PlaylistSink(Protocol):
    """Somewhere a playlist can land. Spotify is one implementation, not the API.

    Implementations MUST degrade rather than raise: an unpaired or 403'd
    Spotify returns ``SinkResult(ok=False, ...)`` and the caller falls through
    to the M3U sink. A demo must never die because of a 5-user Dev Mode cap.
    """

    kind: SinkKind

    async def available(self, user_id: str | None) -> bool:
        """Cheap check — is this sink usable for this user right now?"""
        ...

    async def write(
        self,
        playlist: Playlist,
        *,
        user_id: str | None = None,
    ) -> SinkResult:
        """Persist the playlist. Never raises for expected upstream failures."""
        ...


@runtime_checkable
class AcousticOracle(Protocol):
    """The replacement for Spotify's dead ``/audio-features``.

    Last.fm's community tag vocabulary is the implementation, but the seam
    exists so a future MusicBrainz/AcousticBrainz oracle can drop in.
    """

    name: str

    async def taste_vector(self, handle: str) -> TasteVector:
        """Build a TasteVector for a Last.fm-style user handle."""
        ...

    async def candidates(
        self,
        *,
        taste: TasteVector,
        seed_tags: Sequence[str],
        corridor: GenreCorridor,
        limit: int = 400,
    ) -> list[Track]:
        """Retrieve a candidate pool from the taste graph + tag charts."""
        ...

    async def estimate(self, track: Track) -> Track:
        """Return ``track`` with ``estimated`` populated from its tags."""
        ...

    def estimate_from_tags(self, tags: Sequence[str] | dict[str, float]) -> SonicVector:
        """Pure, synchronous, no-network tag -> SonicVector projection."""
        ...


@runtime_checkable
class WeatherSource(Protocol):
    """Where the sky comes from. Open-Meteo in prod, fixtures in tests."""

    name: str

    async def window(self, coords: Coordinates, at: _dt.datetime | None = None) -> WeatherWindow:
        """Fetch the hourly window incl. past_days. Falls back to last-known-good."""
        ...


@runtime_checkable
class AlmanacStore(Protocol):
    """Persistence for the compounding loop. Firestore in prod, memory in tests."""

    async def record_forge(self, playlist: Playlist) -> str: ...

    async def record_feedback(
        self, *, user_id: str, playlist_id: str, track_key: str, signal: Literal["loved", "skipped"]
    ) -> None: ...

    async def history(self, user_id: str, limit: int = 50) -> list[Playlist]: ...

    async def nudge(self, user_id: str) -> list[list[float]] | None:
        """Per-user delta to the transfer matrix, or None if not enough signal."""
        ...
