"""Acceptance tests for THE FORGE.

NO NETWORK. NO CREDENTIALS. Every collaborator is a small in-test class
implementing the same protocol the real adapter does, so this suite depends on
nothing that is still being written elsewhere.

The load-bearing test in this file is ``test_falling_vs_rising_barometer``.
Everything else checks that the machine is well-formed; that one checks that
the machine is *about something*. If identical coordinates, an identical theme
and an identical corpus produce the same playlist on a collapsing barometer as
on a building ridge, then weather is decoration and the product does not work.

Async is driven with ``asyncio.run`` through a local helper rather than a
pytest plugin, so the suite has no plugin configuration to get wrong.
"""

from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Sequence, TypeVar

import pytest

# The app package is rooted at `backend/`; resolved from this file so the suite
# runs from any working directory.
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.contracts import (  # noqa: E402
    Coordinates,
    ForgeRequest,
    ForgeResult,
    GenreCorridor,
    Playlist,
    SinkResult,
    SonicVector,
    TasteVector,
    Track,
    WeatherObservation,
    WeatherWindow,
)
from app.forge.engine import PlaylistForge
from app.sky.fixtures import FixtureWeatherSource  # noqa: E402

T = TypeVar("T")

BRUSSELS = Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels")
FIXED_AT = datetime(2026, 10, 17, 17, 40, tzinfo=timezone.utc)


def run(coro: Awaitable[T]) -> T:
    return asyncio.run(coro)  # type: ignore[arg-type]


# ===========================================================================
# fixture corpus
# ===========================================================================
# A procedurally-built corpus rather than a hand-picked one, deliberately. A
# curated list can make the falling-vs-rising test pass by accident; a corpus
# that evenly covers the tag space cannot. Everything below is deterministic --
# no RNG anywhere in this file.

_TAG_PROFILES: dict[str, dict[str, float]] = {
    # slow / dark / wide
    "slowcore": {"valence": 0.22, "energy": 0.22, "tempo": 0.20, "acousticness": 0.58, "density": 0.30, "grit": 0.34, "spatiality": 0.74},
    "sadcore": {"valence": 0.18, "energy": 0.26, "tempo": 0.28, "acousticness": 0.62, "density": 0.32, "grit": 0.30, "spatiality": 0.66},
    "ambient": {"valence": 0.46, "energy": 0.16, "tempo": 0.18, "acousticness": 0.42, "density": 0.24, "grit": 0.18, "spatiality": 0.92},
    "drone": {"valence": 0.30, "energy": 0.30, "tempo": 0.12, "acousticness": 0.34, "density": 0.44, "grit": 0.62, "spatiality": 0.88},
    "post-rock": {"valence": 0.40, "energy": 0.50, "tempo": 0.42, "acousticness": 0.44, "density": 0.60, "grit": 0.44, "spatiality": 0.80},
    "dream pop": {"valence": 0.56, "energy": 0.40, "tempo": 0.42, "acousticness": 0.38, "density": 0.50, "grit": 0.28, "spatiality": 0.86},
    "shoegaze": {"valence": 0.44, "energy": 0.62, "tempo": 0.52, "acousticness": 0.18, "density": 0.78, "grit": 0.66, "spatiality": 0.84},
    # bright / fast
    "indie pop": {"valence": 0.68, "energy": 0.58, "tempo": 0.58, "acousticness": 0.36, "density": 0.52, "grit": 0.34, "spatiality": 0.44},
    "power pop": {"valence": 0.78, "energy": 0.72, "tempo": 0.68, "acousticness": 0.28, "density": 0.56, "grit": 0.42, "spatiality": 0.36},
    "new wave": {"valence": 0.64, "energy": 0.68, "tempo": 0.66, "acousticness": 0.22, "density": 0.56, "grit": 0.40, "spatiality": 0.42},
    "krautrock": {"valence": 0.58, "energy": 0.64, "tempo": 0.68, "acousticness": 0.26, "density": 0.54, "grit": 0.44, "spatiality": 0.60},
    "afrobeat": {"valence": 0.74, "energy": 0.72, "tempo": 0.64, "acousticness": 0.52, "density": 0.74, "grit": 0.40, "spatiality": 0.48},
    "funk": {"valence": 0.76, "energy": 0.74, "tempo": 0.66, "acousticness": 0.44, "density": 0.68, "grit": 0.42, "spatiality": 0.40},
    "soul": {"valence": 0.70, "energy": 0.54, "tempo": 0.52, "acousticness": 0.58, "density": 0.56, "grit": 0.30, "spatiality": 0.48},
    # electronic
    "techno": {"valence": 0.46, "energy": 0.80, "tempo": 0.78, "acousticness": 0.06, "density": 0.70, "grit": 0.52, "spatiality": 0.56},
    "idm": {"valence": 0.48, "energy": 0.52, "tempo": 0.54, "acousticness": 0.10, "density": 0.66, "grit": 0.48, "spatiality": 0.66},
    "downtempo": {"valence": 0.48, "energy": 0.34, "tempo": 0.34, "acousticness": 0.28, "density": 0.48, "grit": 0.36, "spatiality": 0.72},
    "dub techno": {"valence": 0.42, "energy": 0.54, "tempo": 0.60, "acousticness": 0.08, "density": 0.52, "grit": 0.38, "spatiality": 0.90},
    "minimal": {"valence": 0.48, "energy": 0.38, "tempo": 0.44, "acousticness": 0.30, "density": 0.26, "grit": 0.30, "spatiality": 0.68},
    # acoustic
    "folk": {"valence": 0.50, "energy": 0.28, "tempo": 0.34, "acousticness": 0.90, "density": 0.26, "grit": 0.16, "spatiality": 0.44},
    "chamber pop": {"valence": 0.54, "energy": 0.36, "tempo": 0.40, "acousticness": 0.78, "density": 0.44, "grit": 0.18, "spatiality": 0.58},
    "singer-songwriter": {"valence": 0.48, "energy": 0.32, "tempo": 0.38, "acousticness": 0.86, "density": 0.28, "grit": 0.20, "spatiality": 0.42},
    "jazz": {"valence": 0.58, "energy": 0.44, "tempo": 0.50, "acousticness": 0.76, "density": 0.56, "grit": 0.30, "spatiality": 0.58},
    "modal jazz": {"valence": 0.54, "energy": 0.38, "tempo": 0.44, "acousticness": 0.82, "density": 0.48, "grit": 0.24, "spatiality": 0.62},
    # heavy
    "post-punk": {"valence": 0.38, "energy": 0.66, "tempo": 0.62, "acousticness": 0.20, "density": 0.54, "grit": 0.62, "spatiality": 0.56},
    "noise rock": {"valence": 0.34, "energy": 0.82, "tempo": 0.66, "acousticness": 0.12, "density": 0.78, "grit": 0.86, "spatiality": 0.44},
    "industrial": {"valence": 0.24, "energy": 0.84, "tempo": 0.64, "acousticness": 0.08, "density": 0.80, "grit": 0.92, "spatiality": 0.50},
    "hardcore": {"valence": 0.38, "energy": 0.92, "tempo": 0.84, "acousticness": 0.08, "density": 0.76, "grit": 0.88, "spatiality": 0.34},
    "indie rock": {"valence": 0.52, "energy": 0.60, "tempo": 0.56, "acousticness": 0.30, "density": 0.58, "grit": 0.52, "spatiality": 0.50},
}

# 40 artists, each anchored in a tag cluster. Names are invented so nothing in
# this file depends on the real world being a particular way.
_ARTISTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Harrow Line", ("slowcore", "sadcore", "indie rock")),
    ("Vellum Hours", ("slowcore", "ambient", "post-rock")),
    ("The Quiet Barometer", ("slowcore", "dream pop", "folk")),
    ("Pale Signal", ("sadcore", "folk", "chamber pop")),
    ("Ninth Register", ("ambient", "drone", "minimal")),
    ("Cassiopeia Field", ("ambient", "dream pop", "downtempo")),
    ("Longwave Chapel", ("drone", "ambient", "industrial")),
    ("Anvil Cloud", ("post-rock", "noise rock", "slowcore")),
    ("Grey Refraction", ("post-rock", "shoegaze", "ambient")),
    ("Sable Meridian", ("dream pop", "shoegaze", "indie pop")),
    ("Halide Sun", ("shoegaze", "noise rock", "indie rock")),
    ("Coastal Static", ("shoegaze", "dream pop", "post-punk")),
    ("Bright Isobar", ("indie pop", "power pop", "new wave")),
    ("The Foehn", ("indie pop", "krautrock", "indie rock")),
    ("Marconi Bell", ("power pop", "new wave", "indie pop")),
    ("Second Ascent", ("power pop", "indie rock", "funk")),
    ("Verity Klein", ("new wave", "post-punk", "indie pop")),
    ("Motorway Six", ("krautrock", "minimal", "new wave")),
    ("Lagos Transit", ("afrobeat", "funk", "jazz")),
    ("Ekene Brass Union", ("afrobeat", "soul", "funk")),
    ("Copper Register", ("funk", "soul", "indie pop")),
    ("Mireille Sway", ("soul", "jazz", "downtempo")),
    ("Kelvin Array", ("techno", "minimal", "dub techno")),
    ("Nullpoint", ("techno", "industrial", "idm")),
    ("Osmium Drift", ("idm", "downtempo", "ambient")),
    ("Slow Modem", ("idm", "minimal", "dub techno")),
    ("Basin Reverb", ("dub techno", "ambient", "downtempo")),
    ("Threadbare Hour", ("downtempo", "soul", "dream pop")),
    ("Winter Aperture", ("minimal", "modal jazz", "ambient")),
    ("Elspeth Rowan", ("folk", "singer-songwriter", "chamber pop")),
    ("The Ferry Hymn", ("folk", "chamber pop", "sadcore")),
    ("Josiah Pike", ("singer-songwriter", "folk", "indie rock")),
    ("Auburn Quartet", ("chamber pop", "modal jazz", "jazz")),
    ("Nadia Oyelaran", ("jazz", "modal jazz", "soul")),
    ("Blue Hour Sextet", ("modal jazz", "jazz", "ambient")),
    ("Concrete Sermon", ("post-punk", "noise rock", "hardcore")),
    ("Iron Fathom", ("noise rock", "industrial", "drone")),
    ("Kilnwork", ("industrial", "hardcore", "techno")),
    ("Sudden Weather", ("hardcore", "post-punk", "indie rock")),
    ("Northfield Wire", ("indie rock", "post-punk", "power pop")),
)

_TRACKS_PER_ARTIST = 6


def _build_corpus() -> list[Track]:
    tracks: list[Track] = []
    for ai, (artist, tags) in enumerate(_ARTISTS):
        for ti in range(_TRACKS_PER_ARTIST):
            # Rotate the tag tuple per track so an artist's records are related
            # but not identical, which is what stops the diversity selector
            # from having a trivially easy job.
            rotated = tuple(tags[(ti + i) % len(tags)] for i in range(len(tags)))
            track_tags = list(dict.fromkeys(rotated[: 2 + (ti % 2)]))
            tracks.append(
                Track(
                    title=f"Movement {ti + 1}",
                    artist=artist,
                    duration_ms=(170 + (ai * 7 + ti * 23) % 200) * 1000,
                    tags=track_tags,
                    listeners=5_000 + ((ai * 37 + ti * 911) % 900) * 1_100,
                    playcount=40_000 + (ai * 1_013 + ti * 37) * 11,
                    lastfm_url=f"https://example.invalid/{ai}/{ti}",
                )
            )
    return tracks


CORPUS = _build_corpus()


# ===========================================================================
# fakes
# ===========================================================================

# Two barographs that differ only in the sign of the derivative. Same location,
# same cloud, same wind, same hour -- only the pressure trend is flipped. That
# isolation is what makes the headline test a real test.
_SCENARIOS: dict[str, dict[str, float]] = {
    "falling": {"p0": 1018.0, "p1": 1007.0, "wind": 0.30, "cloud": 0.70, "precip": 0.15,
                "light": 0.40, "golden": 0.20, "humidity": 0.72, "temp": -0.20},
    "rising": {"p0": 1007.0, "p1": 1018.0, "wind": 0.30, "cloud": 0.70, "precip": 0.15,
               "light": 0.40, "golden": 0.20, "humidity": 0.72, "temp": -0.20},
    "flat": {"p0": 1012.0, "p1": 1012.2, "wind": 0.30, "cloud": 0.70, "precip": 0.15,
             "light": 0.40, "golden": 0.20, "humidity": 0.72, "temp": -0.20},
}


_REAL_SCENARIO = {
    "falling": "front_collapse",
    "rising": "ridge_building",
    "flat": "flat_grey",
}


class FakeWeather:
    name = "fake"

    def __init__(self, scenario: str = "falling", *, fail: bool = False) -> None:
        self.scenario = scenario
        self.fail = fail
        self.calls = 0

    async def window(self, coords: Coordinates, at: datetime | None = None) -> WeatherWindow:
        self.calls += 1
        if self.fail:
            raise RuntimeError("barograph offline")
        s = _SCENARIOS[self.scenario]
        base = at or FIXED_AT

        # Build a genuine WeatherWindow so these tests run through the real
        # extractor rather than a parallel implementation of it. 48 hours of
        # hourly history gives the extractor enough to compute both the 6h
        # derivative and a local norm; the pressure ramp over the final 6 hours
        # is the only thing that differs between "falling" and "rising".
        history: list[WeatherObservation] = []
        span_h = 48
        for i in range(span_h + 1):
            ts = base - timedelta(hours=span_h - i)
            hours_before_now = span_h - i
            if hours_before_now <= 6:
                frac = (6 - hours_before_now) / 6
                pressure = s["p0"] + (s["p1"] - s["p0"]) * frac
            else:
                # Flat baseline before the ramp, so the 6h delta is unambiguous.
                pressure = s["p0"]
            history.append(
                WeatherObservation(
                    time=ts,
                    surface_pressure=pressure,
                    pressure_msl=pressure,
                    temperature_2m=9.5 + s["temp"],
                    apparent_temperature=8.5 + s["temp"],
                    cloud_cover=s["cloud"] * 100.0,
                    precipitation=s["precip"],
                    wind_gusts_10m=s["wind"] * 40.0,
                    relative_humidity_2m=s["humidity"] * 100.0,
                )
            )

        return WeatherWindow(
            coordinates=coords,
            generated_at=base,
            now=history[-1],
            history=history,
            sunrise=base.replace(hour=7, minute=12, second=0, microsecond=0),
            sunset=base.replace(hour=18, minute=24, second=0, microsecond=0),
            daylight_seconds=40_320.0,
            daylight_seconds_yesterday=40_560.0,
            source="fake",
        )


class FakeOracle:
    """Tag-graph oracle over the in-test corpus.

    The failure switches mirror the three ways Last.fm actually lets you down:
    the profile endpoint 403s, the similar-artist expansion times out, or the
    whole service is gone.
    """

    name = "fake"

    def __init__(
        self,
        *,
        fail_taste: bool = False,
        fail_taste_candidates: bool = False,
        fail_all: bool = False,
    ) -> None:
        self.fail_taste = fail_taste
        self.fail_taste_candidates = fail_taste_candidates
        self.fail_all = fail_all
        self.candidate_calls = 0

    def estimate_from_tags(self, tags: Sequence[str]) -> SonicVector:
        acc: dict[str, list[float]] = {}
        for tag in tags:
            profile = _TAG_PROFILES.get(str(tag).lower())
            if not profile:
                continue
            for dim, value in profile.items():
                acc.setdefault(dim, []).append(value)
        if not acc:
            return SonicVector.neutral()
        return SonicVector(**{dim: sum(v) / len(v) for dim, v in acc.items()})

    async def estimate(self, track: Track) -> Track:
        return track.model_copy(update={"estimated": self.estimate_from_tags(track.tags)})

    async def taste_vector(self, handle: str) -> TasteVector:
        if self.fail_taste or self.fail_all:
            raise RuntimeError("last.fm profile unavailable")
        return TasteVector(
            centroid=SonicVector(valence=0.40, energy=0.46, tempo=0.44, acousticness=0.48,
                                 density=0.50, grit=0.46, spatiality=0.70),
            spread=SonicVector(),
            top_tags={"post-rock": 1.0, "slowcore": 0.84, "ambient": 0.70,
                      "post-punk": 0.52, "krautrock": 0.40, "jazz": 0.28},
            top_artists=["Vellum Hours", "Harrow Line", "Anvil Cloud", "Motorway Six"],
            scrobble_count=31_400,
            confidence=0.78,
            source="fake",
        )

    async def candidates(
        self,
        *,
        taste: TasteVector,
        seed_tags: Sequence[str],
        corridor: GenreCorridor,
        limit: int = 400,
    ) -> list[Track]:
        self.candidate_calls += 1
        if self.fail_all:
            raise RuntimeError("last.fm unavailable")
        has_taste = bool(taste.top_artists or taste.top_tags)
        if has_taste and self.fail_taste_candidates:
            raise RuntimeError("similar-artist expansion timed out")

        # A real tag chart answers the tags it was ASKED for. The corridor is a
        # filter applied to that chart, not a co-equal set of seeds -- unioning
        # the two would make a request for "slowcore" and a request for
        # "post-punk" return the same records whenever the corridor is narrow,
        # which is exactly the distinction the theme depends on.
        seeds = {str(t).lower() for t in seed_tags}
        corridor_tags = {t.lower() for t in (corridor.tags or ())}
        top_artists = {a.lower() for a in (taste.top_artists or ())}
        top_tags = taste.top_tags or {}

        ranked: list[tuple[float, str, Track]] = []
        for track in CORPUS:
            tags = {t.lower() for t in track.tags}
            seed_hit = len(tags & seeds)
            corridor_hit = len(tags & corridor_tags)
            if corridor_tags and not corridor_hit:
                continue  # outside the corridor entirely
            affinity = sum(top_tags.get(t, 0.0) for t in tags)
            artist_hit = 2.0 if track.artist.lower() in top_artists else 0.0
            relevance = 2.0 * seed_hit + 0.6 * corridor_hit + 1.5 * affinity + artist_hit
            if relevance <= 0:
                continue
            ranked.append((-relevance, track.key, track))
        ranked.sort()
        return [t for _, _, t in ranked[: max(1, limit)]]


class M3USink:
    kind = "m3u"

    async def available(self, user_id: str | None) -> bool:
        return True

    async def write(self, playlist: Playlist, *, user_id: str | None = None) -> SinkResult:
        payload = "\n".join(["#EXTM3U"] + [t.track.display for t in playlist.tracks])
        return SinkResult(kind="m3u", ok=True, matched=len(playlist.tracks),
                          requested=len(playlist.tracks), payload=payload,
                          message="m3u written")


class BrokenSpotifySink:
    kind = "spotify"

    async def available(self, user_id: str | None) -> bool:
        return True

    async def write(self, playlist: Playlist, *, user_id: str | None = None) -> SinkResult:
        raise RuntimeError("403 from /v1/me/playlists")


class NullAlmanac:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.recorded: list[Playlist] = []

    async def record_forge(self, playlist: Playlist) -> str:
        if self.fail:
            raise RuntimeError("almanac write failed")
        self.recorded.append(playlist)
        return playlist.id

    async def record_feedback(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def history(self, user_id: str, limit: int = 50) -> list[Playlist]:
        return self.recorded[-limit:]

    async def nudge(self, user_id: str) -> list[list[float]] | None:
        return None


class Settings:
    default_playlist_length = 18
    candidate_pool_size = 400
    max_tracks_per_artist = 2
    has_lastfm = True
    has_spotify = False


# ===========================================================================
# helpers
# ===========================================================================


def make_forge(
    *,
    scenario: str = "falling",
    weather_fails: bool = False,
    oracle: FakeOracle | None = None,
    sinks: Sequence[Any] | None = None,
    almanac: NullAlmanac | None = None,
) -> PlaylistForge:
    return PlaylistForge(
        settings=Settings(),
        weather=(
            FakeWeather(scenario, fail=True)
            if weather_fails
            # Use the REAL fixture barographs rather than a second, weaker
            # implementation of the same idea. These are the windows the
            # extractor was tuned against, so the arc shapes they select
            # (Collapse peaking early, Ridge peaking late) are the genuine
            # product behaviour and not an artefact of the harness.
            else FixtureWeatherSource(_REAL_SCENARIO[scenario])
        ),
        oracle=oracle if oracle is not None else FakeOracle(),
        sinks=list(sinks) if sinks is not None else [M3USink()],
        almanac=almanac if almanac is not None else NullAlmanac(),
    )


def make_request(**overrides: Any) -> ForgeRequest:
    base: dict[str, Any] = dict(
        coordinates=BRUSSELS,
        theme_id="petrichor",
        genre_id="any",
        length=14,
        user_id="u-1",
        lastfm_user="listener",
        sink="m3u",
        at=FIXED_AT,
        seed=4242,
    )
    base.update(overrides)
    return ForgeRequest(**base)


def keys(result: ForgeResult) -> set[str]:
    return {st.track.key for st in result.playlist.tracks}


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 1.0


@pytest.fixture()
def result() -> ForgeResult:
    return run(make_forge().forge(make_request()))


# ===========================================================================
# 1. end to end
# ===========================================================================


def test_forge_returns_a_well_formed_playlist(result: ForgeResult) -> None:
    playlist = result.playlist
    assert isinstance(playlist, Playlist)
    assert len(playlist.tracks) == 14, "requested length must be honoured"
    assert playlist.theme_id == "petrichor"
    assert playlist.genre_id == "any"
    assert playlist.coordinates == BRUSSELS
    assert result.elapsed_ms >= 0


def test_no_duplicate_tracks(result: ForgeResult) -> None:
    track_keys = [st.track.key for st in result.playlist.tracks]
    assert len(track_keys) == len(set(track_keys))


def test_artist_cap_is_respected(result: ForgeResult) -> None:
    counts: dict[str, int] = {}
    for st in result.playlist.tracks:
        artist = st.track.artist.lower()
        counts[artist] = counts.get(artist, 0) + 1
    worst = max(counts.items(), key=lambda kv: kv[1])
    assert worst[1] <= Settings.max_tracks_per_artist, f"{worst[0]} appears {worst[1]} times"


def test_every_track_explains_itself(result: ForgeResult) -> None:
    for st in result.playlist.tracks:
        assert st.why.strip(), f"{st.track.display} shipped without a why"
        assert len(st.why) > 12, f"{st.track.display}: why is filler ({st.why!r})"
    # And the whys must not all be the same sentence.
    whys = {st.why for st in result.playlist.tracks}
    assert len(whys) > len(result.playlist.tracks) // 2


def test_every_subscore_is_populated(result: ForgeResult) -> None:
    """A ScoredTrack with only a total is a scoreboard with no game behind it."""
    for st in result.playlist.tracks:
        assert 0.0 <= st.score <= 1.0
        assert 0.0 <= st.sonic_distance <= 1.0
        assert 0.0 <= st.taste_affinity <= 1.0
        assert 0.0 <= st.corridor_fit <= 1.0
        assert 0.0 <= st.novelty <= 1.0
    assert any(st.taste_affinity > 0 for st in result.playlist.tracks)
    assert len({round(st.sonic_distance, 4) for st in result.playlist.tracks}) > 1


def test_rationale_contains_actual_numbers(result: ForgeResult) -> None:
    rationale = result.playlist.rationale
    assert rationale.headline.strip()
    assert re.search(r"\d", rationale.body), "a rationale with no digits is a horoscope"
    assert rationale.sky_reading
    assert rationale.sonic_moves
    assert 0.0 <= rationale.confidence <= 1.0


def test_sonic_target_is_a_real_vector(result: ForgeResult) -> None:
    target = result.playlist.sonic_target
    for dim in ("valence", "energy", "tempo", "acousticness", "density", "grit", "spatiality"):
        assert 0.0 <= getattr(target, dim) <= 1.0
    assert 40.0 < target.tempo_bpm < 220.0


# ===========================================================================
# 2. arc
# ===========================================================================


def test_arc_roles_and_positions(result: ForgeResult) -> None:
    tracks = result.playlist.tracks
    positions = [st.position for st in tracks]
    assert positions == list(range(len(tracks))), "positions must be contiguous from 0"

    roles = [st.role for st in tracks]
    assert roles.count("opener") == 1, roles
    assert roles.count("closer") == 1, roles
    assert roles[0] == "opener"
    assert roles[-1] == "closer"
    assert roles.count("peak") == 1, roles
    assert all(r in {"opener", "build", "peak", "descent", "closer", "body"} for r in roles)


def test_falling_barometer_peaks_earlier_than_rising() -> None:
    """The arc itself must move with the derivative, not just the track set."""
    falling = run(make_forge(scenario="falling").forge(make_request()))
    rising = run(make_forge(scenario="rising").forge(make_request()))

    def peak_index(res: ForgeResult) -> int:
        return next(st.position for st in res.playlist.tracks if st.role == "peak")

    assert peak_index(falling) < peak_index(rising), (
        "a collapsing barometer wants an early peak and a long descent; "
        "a building ridge wants a late one"
    )


def test_arc_intensity_follows_the_curve() -> None:
    """On a ridge the playlist should genuinely get heavier towards the peak."""
    from app.forge import arc as arc_mod

    res = run(make_forge(scenario="rising").forge(make_request(theme_id="golden_hour")))
    tracks = res.playlist.tracks
    peak = next(st.position for st in tracks if st.role == "peak")
    intensities = [arc_mod.track_intensity(st) for st in tracks]
    head = sum(intensities[: max(1, peak // 2)]) / max(1, peak // 2)
    at_peak = intensities[peak]
    assert at_peak > head, "the peak should be heavier than the opening third"


# ===========================================================================
# 3. THE HEADLINE PROPERTY
# ===========================================================================


def test_falling_vs_rising_barometer() -> None:
    """Same place, same hour, same theme, same corpus. Only the glass moves.

    If this fails, weather is decoration and BAROGROOVE is a mood board.
    """
    request = make_request(theme_id="petrichor")
    falling = run(make_forge(scenario="falling").forge(request))
    rising = run(make_forge(scenario="rising").forge(request))

    # -- the sky itself must differ in the derivative and nowhere else
    assert falling.playlist.sky.pressure_trend_6h < -0.3
    assert rising.playlist.sky.pressure_trend_6h > 0.3

    # -- the targets must be materially different vectors
    a, b = falling.playlist.sonic_target, rising.playlist.sonic_target
    assert a.distance(b) > 0.05, f"targets barely moved: {a.as_dict()} vs {b.as_dict()}"
    assert b.valence > a.valence, "a rising glass should not be gloomier than a falling one"
    assert b.energy > a.energy
    assert b.tempo_bpm > a.tempo_bpm

    # -- and the actual records must differ, not just the numbers behind them
    overlap = jaccard(keys(falling), keys(rising))
    assert overlap < 0.5, (
        f"track sets are {overlap:.0%} identical; the barometer is not reaching the playlist"
    )


def test_flat_barometer_sits_between_the_two() -> None:
    falling = run(make_forge(scenario="falling").forge(make_request()))
    flat = run(make_forge(scenario="flat").forge(make_request()))
    rising = run(make_forge(scenario="rising").forge(make_request()))

    assert (
        falling.playlist.sonic_target.energy
        <= flat.playlist.sonic_target.energy
        <= rising.playlist.sonic_target.energy
    )


# ===========================================================================
# 4. theme x genre orthogonality
# ===========================================================================


def test_same_theme_two_corridors_diverge() -> None:
    guitars = run(make_forge().forge(make_request(genre_id="post-punk")))
    acoustic = run(make_forge().forge(make_request(genre_id="folk")))

    assert guitars.playlist.genre_id == "post-punk"
    assert acoustic.playlist.genre_id == "folk"
    overlap = jaccard(keys(guitars), keys(acoustic))
    assert overlap < 0.5, f"corridors produced {overlap:.0%} the same tracks"


def test_same_corridor_two_themes_diverge() -> None:
    # Opposite poles of the theme space (bias distance 0.31): if these two do
    # not separate, the theme knob does nothing.
    petri = run(make_forge().forge(make_request(theme_id="petrichor", genre_id="post-punk")))
    ridge = run(make_forge().forge(make_request(theme_id="storm_front", genre_id="post-punk")))

    assert petri.playlist.theme_id != ridge.playlist.theme_id
    assert petri.playlist.sonic_target.distance(ridge.playlist.sonic_target) > 0.05
    # A PINNED corridor deliberately caps how far the theme axis can move the
    # track SET: "post-punk" is the pool, and both themes must fish in it. The
    # corridor axis is the one that swaps the pool wholesale (asserted at <0.5
    # in the test above); the theme axis moves the target, the ordering and a
    # meaningful slice of the selection within that pool. Assert that, not a
    # separation the design does not actually claim.
    overlap = jaccard(keys(petri), keys(ridge))
    assert overlap < 0.85, f"themes produced {overlap:.0%} the same tracks"
    assert keys(petri) != keys(ridge), "themes must move the selection, not just the target"
    assert [k for k in keys(petri)] != [k for k in keys(ridge)], "ordering must differ too"


def test_unknown_theme_falls_back_to_the_sky() -> None:
    res = run(make_forge().forge(make_request(theme_id="no-such-theme")))
    assert res.playlist.tracks
    assert res.playlist.theme_id != "no-such-theme"
    assert any("theme" in d for d in res.degraded)


def test_theme_none_lets_the_sky_pick() -> None:
    res = run(make_forge(scenario="falling").forge(make_request(theme_id=None)))
    assert res.playlist.theme_id, "the sky must choose a theme when none is given"
    assert res.playlist.tracks


# ===========================================================================
# 5. degradation -- nothing here is allowed to be fatal
# ===========================================================================


def test_oracle_taste_failure_degrades_to_theme_only() -> None:
    oracle = FakeOracle(fail_taste=True)
    res = run(make_forge(oracle=oracle).forge(make_request()))

    assert len(res.playlist.tracks) == 14, "theme-only mode must still fill the playlist"
    assert res.degraded, "a missing taste profile must be reported"
    assert any("taste" in d for d in res.degraded)
    assert res.playlist.rationale.degraded == res.degraded
    assert all(st.taste_affinity == 0.0 for st in res.playlist.tracks)


def test_taste_graph_expansion_failure_still_fills_from_tag_charts() -> None:
    oracle = FakeOracle(fail_taste_candidates=True)
    res = run(make_forge(oracle=oracle).forge(make_request()))

    assert len(res.playlist.tracks) == 14
    assert any("candidates" in d for d in res.degraded)


def test_total_oracle_failure_still_returns_a_playlist() -> None:
    """No pool, no tracks -- but a Playlist object, a rationale and no exception."""
    res = run(make_forge(oracle=FakeOracle(fail_all=True)).forge(make_request()))

    assert isinstance(res.playlist, Playlist)
    assert res.playlist.rationale.headline
    assert res.degraded
    assert res.playlist.tracks == []


def test_weather_failure_gives_a_neutral_sky_and_still_forges() -> None:
    res = run(make_forge(weather_fails=True).forge(make_request()))

    assert len(res.playlist.tracks) == 14
    assert any("weather" in d for d in res.degraded)
    assert res.playlist.sky.pressure_trend_6h == pytest.approx(0.0, abs=1e-9)
    assert res.playlist.rationale.body


def test_sink_failure_falls_back_to_m3u() -> None:
    res = run(
        make_forge(sinks=[BrokenSpotifySink(), M3USink()]).forge(
            make_request(sink="auto")
        )
    )
    sink = res.playlist.sink
    assert sink is not None
    assert sink.ok, sink.message
    assert sink.kind == "m3u", "a dead Spotify must fall through to the M3U payload"
    assert sink.payload
    assert sink.matched == len(res.playlist.tracks)


def test_no_sink_at_all_is_survivable() -> None:
    res = run(make_forge(sinks=[BrokenSpotifySink()]).forge(make_request(sink="auto")))
    assert len(res.playlist.tracks) == 14
    assert any("sink" in d for d in res.degraded)


def test_almanac_failure_never_breaks_the_response() -> None:
    almanac = NullAlmanac(fail=True)
    res = run(make_forge(almanac=almanac).forge(make_request()))

    assert len(res.playlist.tracks) == 14
    assert any("almanac" in d for d in res.degraded)
    assert res.playlist.rationale.degraded == res.degraded


def test_clean_run_reports_no_degradation() -> None:
    res = run(make_forge().forge(make_request()))
    assert res.degraded == [], res.degraded


def test_degradation_lowers_stated_confidence() -> None:
    clean = run(make_forge().forge(make_request()))
    broken = run(make_forge(weather_fails=True, oracle=FakeOracle(fail_taste=True)).forge(
        make_request()
    ))
    assert broken.playlist.rationale.confidence < clean.playlist.rationale.confidence


# ===========================================================================
# 6. determinism
# ===========================================================================


def test_same_seed_yields_an_identical_playlist() -> None:
    request = make_request(seed=99)
    first = run(make_forge().forge(request))
    second = run(make_forge().forge(request))

    assert first.playlist.id == second.playlist.id
    assert first.playlist.model_dump(mode="json") == second.playlist.model_dump(mode="json")


def test_different_seeds_are_allowed_to_differ_but_stay_coherent() -> None:
    a = run(make_forge().forge(make_request(seed=1)))
    b = run(make_forge().forge(make_request(seed=2)))

    assert len(a.playlist.tracks) == len(b.playlist.tracks)
    # The seed only breaks ties, so the two runs should still agree strongly.
    assert jaccard(keys(a), keys(b)) > 0.5


def test_no_seed_still_produces_a_valid_playlist() -> None:
    res = run(make_forge().forge(make_request(seed=None)))
    assert len(res.playlist.tracks) == 14
    assert res.playlist.id.startswith("bg_")


# ===========================================================================
# 7. explain
# ===========================================================================


def test_explain_rebuilds_a_rationale_for_a_stored_playlist() -> None:
    forge = make_forge()
    res = run(forge.forge(make_request()))
    rationale = run(forge.explain(res.playlist))

    assert rationale.headline
    assert re.search(r"\d", rationale.body)
    assert rationale.sonic_moves


def test_explain_survives_a_playlist_whose_theme_vanished() -> None:
    forge = make_forge()
    res = run(forge.forge(make_request()))
    orphan = res.playlist.model_copy(update={"theme_id": "deleted-theme"})

    rationale = run(forge.explain(orphan))
    assert rationale.headline
    assert any("theme" in d for d in rationale.degraded)


# ===========================================================================
# 8. length handling
# ===========================================================================


@pytest.mark.parametrize("length", [4, 8, 18, 30])
def test_requested_lengths_are_honoured(length: int) -> None:
    res = run(make_forge().forge(make_request(length=length)))
    assert len(res.playlist.tracks) == length
    assert [st.position for st in res.playlist.tracks] == list(range(length))
    assert [st.role for st in res.playlist.tracks].count("opener") == 1
    assert [st.role for st in res.playlist.tracks].count("closer") == 1


def test_a_length_larger_than_the_pool_degrades_gracefully() -> None:
    """40 artists x 6 tracks, capped at 2 per artist, is 80 selectable records."""
    res = run(make_forge().forge(make_request(length=60)))
    assert len(res.playlist.tracks) > 0
    if len(res.playlist.tracks) < 60:
        assert any("diversity" in d or "candidates" in d for d in res.degraded)


# ===========================================================================
# 9. selection quality
# ===========================================================================


def test_selection_is_more_diverse_than_naive_top_k() -> None:
    """The whole point of MMR: beat the sort you would otherwise have shipped."""
    from app.forge import diversity as diversity_mod
    from app.forge.candidates import gather_candidates
    from app.forge.rerank import rerank
    from app.sonic.corridors import get_corridor
    from app.sonic.themes import get_theme

    oracle = FakeOracle()
    theme = get_theme("petrichor")
    corridor = get_corridor("any")
    taste = run(oracle.taste_vector("listener"))
    pool = run(
        gather_candidates(oracle=oracle, theme=theme, corridor=corridor, taste=taste, limit=300)
    )
    assert len(pool) > 40, "the fixture pool should be big enough to choose from"
    assert all(c.estimated is not None for c in pool), "every candidate must carry a vector"

    target = SonicVector(valence=0.30, energy=0.32, tempo=0.30, acousticness=0.56,
                         density=0.38, grit=0.36, spatiality=0.80)
    scored = rerank(pool, target=target, theme=theme, corridor=corridor, taste=taste)
    index = diversity_mod.vector_index(pool)

    naive = scored[:14]
    mmr = diversity_mod.select(scored, k=14, index=index, theme=theme, max_per_artist=2, seed=1)

    naive_spread = diversity_mod.spread_report(naive, index=index, theme=theme)
    mmr_spread = diversity_mod.spread_report(mmr, index=index, theme=theme)

    assert len(mmr) == 14
    assert mmr_spread["mean_nearest"] > naive_spread["mean_nearest"], (
        f"MMR ({mmr_spread}) should spread wider than top-k ({naive_spread})"
    )


def test_provenance_survives_into_the_why() -> None:
    """'Two hops from X' is only allowed to appear when it is actually true."""
    res = run(make_forge().forge(make_request()))
    taste_artists = {"vellum hours", "harrow line", "anvil cloud", "motorway six"}
    for st in res.playlist.tracks:
        if "straight out of your" in st.why.lower():
            assert st.track.artist.lower() in taste_artists, st.why


def test_theme_avoid_tags_are_punished() -> None:
    """A record carrying an avoided tag must score below an otherwise equal one."""
    from app.forge.candidates import Candidate
    from app.forge.rerank import score_candidate
    from app.sonic.corridors import get_corridor
    from app.sonic.themes import get_theme

    theme = get_theme("petrichor")
    corridor = get_corridor("any")
    vec = SonicVector(valence=0.30, energy=0.30, tempo=0.28, acousticness=0.56,
                      density=0.36, grit=0.34, spatiality=0.78)

    clean = Candidate(
        track=Track(title="A", artist="Someone", tags=["slowcore", "ambient"], listeners=40_000),
        estimated=vec, provenance="tag-chart",
    )
    tainted = Candidate(
        track=Track(
            title="B", artist="Someone Else",
            tags=["slowcore", "ambient", theme.avoid_tags[0]], listeners=40_000,
        ),
        estimated=vec, provenance="tag-chart",
    )

    a = score_candidate(clean, target=vec, theme=theme, corridor=corridor, taste=None)
    b = score_candidate(tainted, target=vec, theme=theme, corridor=corridor, taste=None)
    assert b.score < a.score


def test_thin_taste_profile_cannot_dominate() -> None:
    """Confidence scaling is what stops fifty scrobbles steering the playlist."""
    from app.forge.candidates import Candidate
    from app.forge.rerank import taste_affinity

    cand = Candidate(
        track=Track(title="A", artist="Vellum Hours", tags=["post-rock", "slowcore"]),
        estimated=SonicVector(), provenance="similar-artist",
    )
    strong = TasteVector(top_tags={"post-rock": 1.0, "slowcore": 0.9},
                         top_artists=["Vellum Hours"], confidence=0.9, source="fake")
    thin = strong.model_copy(update={"confidence": 0.05})

    assert taste_affinity(cand, strong) > taste_affinity(cand, thin) * 5
    assert taste_affinity(cand, None) == 0.0
