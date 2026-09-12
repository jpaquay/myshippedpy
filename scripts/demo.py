"""``python -m scripts.demo`` -- forge a playlist from fixture weather, offline.

No network, no credentials, no container. Everything this script needs -- a
weather source, an acoustic oracle with a small hand-built corpus, a sink --
is defined right here, implementing the same protocols the real adapters do.
That is the point: if the forge can produce something worth reading from a
hundred records and a fake barograph, the pipeline is sound and the rest is
plumbing.

    python -m scripts.demo
    python -m scripts.demo --scenario rising --genre guitars
    python -m scripts.demo --theme glass-barometer --length 12
    python -m scripts.demo --compare          # falling vs rising, side by side
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

# The app package is rooted at ``backend/``. Resolved from this file rather
# than hard-coded so the script works from any working directory.
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.contracts import (  # noqa: E402
    Coordinates,
    ForgeRequest,
    GenreCorridor,
    Playlist,
    SinkResult,
    SonicVector,
    TasteVector,
    Track,
    WeatherWindow,
)
from app.forge.engine import PlaylistForge  # noqa: E402
from app.sky.fixtures import SCENARIOS as REAL_SCENARIOS  # noqa: E402
from app.sky.fixtures import FixtureWeatherSource  # noqa: E402

# ---------------------------------------------------------------------------
# terminal styling -- restrained, and gone entirely when not a TTY
# ---------------------------------------------------------------------------

_COLOUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None and os.environ.get(
    "TERM", ""
) not in ("dumb", "")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


def dim(t: str) -> str:
    return _c("2", t)


def bold(t: str) -> str:
    return _c("1", t)


def sky_blue(t: str) -> str:
    return _c("38;5;74", t)


def gold(t: str) -> str:
    return _c("38;5;179", t)


def slate(t: str) -> str:
    return _c("38;5;103", t)


WIDTH = 84


def _visible_len(s: str) -> int:
    """Length ignoring ANSI escapes, so box borders line up when coloured."""
    out, i = 0, 0
    while i < len(s):
        if s[i] == "\033":
            while i < len(s) and s[i] != "m":
                i += 1
            i += 1
            continue
        out += 1
        i += 1
    return out


def rule(left: str, fill: str, right: str, label: str = "") -> str:
    if label:
        text = f" {label} "
        pad = WIDTH - 2 - len(text)
        return slate(left + fill + text + fill * max(0, pad - 1) + right)
    return slate(left + fill * (WIDTH - 2) + right)


def row(text: str = "") -> str:
    pad = WIDTH - 2 - _visible_len(text)
    return slate("\u2502") + text + " " * max(0, pad) + slate("\u2502")


def wrap(text: str, indent: int = 1) -> list[str]:
    limit = WIDTH - 3 - indent
    words, line, lines = text.split(), "", []
    for w in words:
        if line and len(line) + 1 + len(w) > limit:
            lines.append(" " * indent + line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        lines.append(" " * indent + line)
    return lines


# ---------------------------------------------------------------------------
# fixture corpus
# ---------------------------------------------------------------------------
# (artist, title, seconds, listeners, tags). Chosen to span the theme and
# corridor tag space with enough overlap that the reranker has real decisions
# to make rather than a lookup table.
_CORPUS: tuple[tuple[str, str, int, int, tuple[str, ...]], ...] = (
    ("Talk Talk", "New Grass", 589, 240_000, ("post-rock", "art rock", "ambient", "jazz")),
    ("Talk Talk", "Ascension Day", 366, 210_000, ("post-rock", "art rock", "noise rock")),
    ("Talk Talk", "I Believe in You", 496, 330_000, ("art rock", "ambient", "dream pop")),
    ("Bark Psychosis", "Absent Friend", 428, 62_000, ("post-rock", "slowcore", "ambient")),
    ("Codeine", "Sea", 300, 78_000, ("slowcore", "indie rock", "sadcore")),
    ("Low", "Sunflower", 262, 340_000, ("slowcore", "sadcore", "indie rock")),
    ("Low", "Dinosaur Act", 265, 220_000, ("slowcore", "indie rock", "noise rock")),
    ("Duster", "Inside Out", 174, 410_000, ("slowcore", "indie rock", "lo-fi")),
    ("Red House Painters", "Katy Song", 512, 290_000, ("slowcore", "sadcore", "folk")),
    ("Mark Hollis", "A Life (1895-1915)", 496, 88_000, ("chamber pop", "folk", "ambient")),
    ("Grouper", "Heavy Water/I'd Rather Be Sleeping", 214, 300_000, ("ambient", "dream pop", "drone")),
    ("Grouper", "Alien Observer", 288, 260_000, ("ambient", "dream pop", "drone")),
    ("Stars of the Lid", "Requiem for Dying Mothers", 428, 190_000, ("ambient", "drone", "minimal")),
    ("Brian Eno", "An Ending (Ascent)", 264, 690_000, ("ambient", "minimal", "electronic")),
    ("Brian Eno", "By This River", 183, 420_000, ("ambient", "art rock", "minimal")),
    ("Harold Budd", "The Room Alone", 226, 71_000, ("ambient", "minimal", "modern classical")),
    ("Slowdive", "Dagger", 219, 380_000, ("shoegaze", "dream pop", "slowcore")),
    ("Slowdive", "Alison", 227, 620_000, ("shoegaze", "dream pop", "indie rock")),
    ("Cocteau Twins", "Cherry-Coloured Funk", 194, 540_000, ("dream pop", "shoegaze", "ambient pop")),
    ("Beach House", "Space Song", 320, 1_400_000, ("dream pop", "indie pop", "ambient pop")),
    ("Mazzy Star", "Fade Into You", 295, 1_900_000, ("dream pop", "folk", "sadcore")),
    ("My Bloody Valentine", "Soon", 397, 470_000, ("shoegaze", "noise rock", "dream pop")),
    ("Ride", "Vapour Trail", 260, 330_000, ("shoegaze", "indie rock", "dream pop")),
    ("Portishead", "Roads", 302, 900_000, ("trip hop", "downtempo", "sadcore")),
    ("Massive Attack", "Teardrop", 330, 1_600_000, ("trip hop", "downtempo", "electronic")),
    ("Tricky", "Aftermath", 452, 180_000, ("trip hop", "downtempo", "industrial")),
    ("Boards of Canada", "Roygbiv", 151, 780_000, ("idm", "downtempo", "electronic")),
    ("Boards of Canada", "Dayvan Cowboy", 300, 520_000, ("idm", "downtempo", "ambient")),
    ("Aphex Twin", "Rhubarb", 457, 640_000, ("ambient", "idm", "minimal")),
    ("Autechre", "Second Bad Vilbel", 296, 210_000, ("idm", "electronic", "minimal")),
    ("Basic Channel", "Phylyps Trak", 429, 62_000, ("dub techno", "techno", "minimal")),
    ("Gas", "Pop 1", 445, 74_000, ("ambient", "dub techno", "drone")),
    ("Donato Dozzy", "Parola", 402, 41_000, ("techno", "minimal", "dub techno")),
    ("Jeff Mills", "The Bells", 320, 290_000, ("techno", "minimal", "electronic")),
    ("Caterina Barbieri", "Fantas", 500, 58_000, ("minimal", "electronic", "modern classical")),
    ("Neu!", "Hallogallo", 610, 260_000, ("krautrock", "indie rock", "minimal")),
    ("Can", "Vitamin C", 213, 420_000, ("krautrock", "post-punk", "art rock")),
    ("Harmonia", "Watussi", 292, 68_000, ("krautrock", "electronic", "minimal")),
    ("Stereolab", "French Disko", 168, 250_000, ("indie pop", "krautrock", "post-punk")),
    ("Broadcast", "Come On Let's Go", 189, 210_000, ("indie pop", "dream pop", "krautrock")),
    ("The Feelies", "Let's Go", 218, 74_000, ("indie rock", "power pop", "post-punk")),
    ("Television", "Marquee Moon", 585, 480_000, ("post-punk", "indie rock", "art rock")),
    ("Wire", "Outdoor Miner", 105, 190_000, ("post-punk", "power pop", "indie pop")),
    ("The Cure", "A Forest", 350, 1_100_000, ("post-punk", "new wave", "gothic rock")),
    ("Joy Division", "Atmosphere", 249, 1_300_000, ("post-punk", "new wave", "sadcore")),
    ("New Order", "Age of Consent", 305, 900_000, ("new wave", "post-punk", "indie pop")),
    ("Talking Heads", "The Great Curve", 405, 380_000, ("new wave", "afrobeat", "art rock")),
    ("Fela Kuti", "Water No Get Enemy", 654, 260_000, ("afrobeat", "jazz", "funk")),
    ("Tony Allen", "Kilode", 428, 62_000, ("afrobeat", "jazz", "electronic")),
    ("William Onyeabor", "Fantastic Man", 507, 130_000, ("afrobeat", "funk", "electronic")),
    ("Alice Coltrane", "Journey in Satchidananda", 396, 300_000, ("spiritual jazz", "jazz", "modal jazz")),
    ("Pharoah Sanders", "The Creator Has a Master Plan", 1_960, 210_000, ("spiritual jazz", "free jazz", "jazz")),
    ("Bill Evans", "Peace Piece", 401, 260_000, ("jazz", "modal jazz", "minimal")),
    ("Miles Davis", "Blue in Green", 337, 800_000, ("modal jazz", "jazz", "chamber pop")),
    ("Alabaster DePlume", "Visit Croatia", 254, 48_000, ("spiritual jazz", "jazz", "folk")),
    ("Nick Drake", "Pink Moon", 121, 1_100_000, ("folk", "singer-songwriter", "sadcore")),
    ("Vashti Bunyan", "Diamond Day", 130, 190_000, ("folk", "singer-songwriter", "chamber pop")),
    ("Bill Callahan", "Jim Cain", 293, 200_000, ("singer-songwriter", "americana", "folk")),
    ("Gillian Welch", "Everything Is Free", 269, 180_000, ("americana", "folk", "singer-songwriter")),
    ("Judee Sill", "The Kiss", 268, 96_000, ("chamber pop", "folk", "singer-songwriter")),
    ("Arthur Russell", "A Little Lost", 194, 300_000, ("chamber pop", "balearic", "singer-songwriter")),
    ("Sade", "Kiss of Life", 265, 700_000, ("soul", "balearic", "downtempo")),
    ("Marvin Gaye", "Mercy Mercy Me", 195, 1_500_000, ("soul", "funk", "jazz")),
    ("Khruangbin", "August 10", 254, 900_000, ("balearic", "downtempo", "funk")),
    ("Sault", "Wildfires", 200, 500_000, ("soul", "funk", "downtempo")),
    ("Sonic Youth", "Schizophrenia", 258, 420_000, ("noise rock", "indie rock", "post-punk")),
    ("Swans", "Screen Shot", 336, 180_000, ("noise rock", "industrial", "drone")),
    ("Big Black", "Kerosene", 566, 120_000, ("noise rock", "industrial", "hardcore")),
    ("Godflesh", "Like Rats", 288, 96_000, ("industrial", "drone", "hardcore")),
    ("Sunn O)))", "Aghartha", 1_137, 78_000, ("drone", "ambient", "industrial")),
    ("Fugazi", "Waiting Room", 155, 620_000, ("hardcore", "post-punk", "indie rock")),
    ("Unwound", "Corpse Pose", 168, 90_000, ("noise rock", "post-punk", "hardcore")),
    ("Slint", "Good Morning, Captain", 460, 300_000, ("post-rock", "slowcore", "noise rock")),
    ("Mogwai", "Take Me Somewhere Nice", 262, 380_000, ("post-rock", "shoegaze", "ambient")),
    ("Do Make Say Think", "Horns of a Rabbit", 358, 62_000, ("post-rock", "jazz", "krautrock")),
    ("Yo La Tengo", "Green Arrow", 342, 210_000, ("indie rock", "slowcore", "ambient")),
    ("The Sea and Cake", "Parasol", 235, 74_000, ("indie pop", "jazz", "post-rock")),
    ("Belle and Sebastian", "The Stars of Track and Field", 289, 480_000, ("indie pop", "chamber pop", "folk")),
    ("Teenage Fanclub", "Star Sign", 275, 190_000, ("power pop", "indie pop", "indie rock")),
    ("Big Star", "Thirteen", 154, 420_000, ("power pop", "indie pop", "folk")),
    ("Alvvays", "Dreams Tonite", 233, 700_000, ("indie pop", "dream pop", "shoegaze")),
)

# Tag -> partial SonicVector. Only the dims a tag genuinely says something
# about are listed; the estimator averages what it finds and leaves the rest
# at neutral. This is a toy version of what the real oracle does with the
# Last.fm tag graph, and it is deliberately coarse -- coarse is honest.
_TAG_PROFILES: dict[str, dict[str, float]] = {
    "slowcore": {"valence": 0.24, "energy": 0.22, "tempo": 0.20, "acousticness": 0.58, "density": 0.30, "spatiality": 0.72},
    "sadcore": {"valence": 0.18, "energy": 0.26, "tempo": 0.28, "acousticness": 0.62, "spatiality": 0.66},
    "ambient": {"valence": 0.46, "energy": 0.16, "tempo": 0.18, "acousticness": 0.42, "density": 0.24, "grit": 0.18, "spatiality": 0.92},
    "drone": {"valence": 0.30, "energy": 0.30, "tempo": 0.12, "acousticness": 0.34, "density": 0.44, "grit": 0.62, "spatiality": 0.88},
    "minimal": {"valence": 0.48, "energy": 0.38, "tempo": 0.44, "acousticness": 0.30, "density": 0.26, "spatiality": 0.68},
    "post-rock": {"valence": 0.40, "energy": 0.50, "tempo": 0.42, "acousticness": 0.44, "density": 0.60, "spatiality": 0.80},
    "art rock": {"valence": 0.46, "energy": 0.52, "tempo": 0.48, "acousticness": 0.44, "density": 0.62, "grit": 0.44},
    "dream pop": {"valence": 0.56, "energy": 0.40, "tempo": 0.42, "acousticness": 0.38, "density": 0.50, "grit": 0.28, "spatiality": 0.86},
    "ambient pop": {"valence": 0.60, "energy": 0.38, "tempo": 0.40, "acousticness": 0.40, "spatiality": 0.84},
    "shoegaze": {"valence": 0.44, "energy": 0.62, "tempo": 0.52, "acousticness": 0.18, "density": 0.78, "grit": 0.66, "spatiality": 0.84},
    "indie rock": {"valence": 0.52, "energy": 0.60, "tempo": 0.56, "acousticness": 0.30, "density": 0.58, "grit": 0.52},
    "indie pop": {"valence": 0.68, "energy": 0.58, "tempo": 0.58, "acousticness": 0.36, "density": 0.52, "grit": 0.34},
    "power pop": {"valence": 0.76, "energy": 0.70, "tempo": 0.66, "acousticness": 0.28, "density": 0.56, "grit": 0.42},
    "post-punk": {"valence": 0.38, "energy": 0.66, "tempo": 0.62, "acousticness": 0.20, "density": 0.54, "grit": 0.62, "spatiality": 0.56},
    "new wave": {"valence": 0.62, "energy": 0.66, "tempo": 0.64, "acousticness": 0.22, "density": 0.56, "grit": 0.40},
    "gothic rock": {"valence": 0.26, "energy": 0.58, "tempo": 0.54, "acousticness": 0.20, "grit": 0.58, "spatiality": 0.72},
    "noise rock": {"valence": 0.34, "energy": 0.80, "tempo": 0.64, "acousticness": 0.12, "density": 0.78, "grit": 0.86},
    "industrial": {"valence": 0.24, "energy": 0.82, "tempo": 0.62, "acousticness": 0.08, "density": 0.80, "grit": 0.92},
    "hardcore": {"valence": 0.38, "energy": 0.92, "tempo": 0.82, "acousticness": 0.08, "density": 0.76, "grit": 0.88},
    "krautrock": {"valence": 0.56, "energy": 0.62, "tempo": 0.66, "acousticness": 0.26, "density": 0.54, "grit": 0.44, "spatiality": 0.62},
    "trip hop": {"valence": 0.34, "energy": 0.42, "tempo": 0.38, "acousticness": 0.24, "density": 0.62, "grit": 0.44, "spatiality": 0.74},
    "downtempo": {"valence": 0.48, "energy": 0.36, "tempo": 0.36, "acousticness": 0.28, "density": 0.48, "spatiality": 0.70},
    "idm": {"valence": 0.48, "energy": 0.52, "tempo": 0.54, "acousticness": 0.10, "density": 0.66, "grit": 0.48, "spatiality": 0.66},
    "techno": {"valence": 0.46, "energy": 0.78, "tempo": 0.76, "acousticness": 0.06, "density": 0.70, "grit": 0.52, "spatiality": 0.58},
    "dub techno": {"valence": 0.42, "energy": 0.54, "tempo": 0.60, "acousticness": 0.08, "density": 0.52, "grit": 0.38, "spatiality": 0.90},
    "electronic": {"valence": 0.52, "energy": 0.58, "tempo": 0.60, "acousticness": 0.10, "density": 0.60, "grit": 0.40},
    "modern classical": {"valence": 0.44, "energy": 0.26, "tempo": 0.30, "acousticness": 0.80, "density": 0.34, "grit": 0.16, "spatiality": 0.78},
    "chamber pop": {"valence": 0.54, "energy": 0.36, "tempo": 0.40, "acousticness": 0.78, "density": 0.44, "grit": 0.18, "spatiality": 0.58},
    "folk": {"valence": 0.50, "energy": 0.30, "tempo": 0.36, "acousticness": 0.90, "density": 0.26, "grit": 0.16, "spatiality": 0.44},
    "singer-songwriter": {"valence": 0.48, "energy": 0.32, "tempo": 0.38, "acousticness": 0.86, "density": 0.28, "grit": 0.20},
    "americana": {"valence": 0.52, "energy": 0.38, "tempo": 0.42, "acousticness": 0.84, "density": 0.34, "grit": 0.28},
    "jazz": {"valence": 0.58, "energy": 0.44, "tempo": 0.50, "acousticness": 0.76, "density": 0.56, "grit": 0.30, "spatiality": 0.58},
    "modal jazz": {"valence": 0.54, "energy": 0.38, "tempo": 0.44, "acousticness": 0.82, "density": 0.48, "grit": 0.24, "spatiality": 0.62},
    "spiritual jazz": {"valence": 0.60, "energy": 0.50, "tempo": 0.48, "acousticness": 0.74, "density": 0.62, "grit": 0.30, "spatiality": 0.76},
    "free jazz": {"valence": 0.46, "energy": 0.72, "tempo": 0.58, "acousticness": 0.70, "density": 0.84, "grit": 0.56},
    "soul": {"valence": 0.68, "energy": 0.52, "tempo": 0.50, "acousticness": 0.58, "density": 0.56, "grit": 0.30},
    "funk": {"valence": 0.74, "energy": 0.72, "tempo": 0.64, "acousticness": 0.44, "density": 0.68, "grit": 0.42},
    "afrobeat": {"valence": 0.72, "energy": 0.70, "tempo": 0.62, "acousticness": 0.52, "density": 0.74, "grit": 0.40},
    "balearic": {"valence": 0.70, "energy": 0.44, "tempo": 0.48, "acousticness": 0.44, "density": 0.44, "grit": 0.22, "spatiality": 0.72},
    "lo-fi": {"valence": 0.44, "energy": 0.38, "tempo": 0.42, "acousticness": 0.50, "density": 0.34, "grit": 0.64},
}


# ---------------------------------------------------------------------------
# fixture adapters -- the same protocols the real ones implement
# ---------------------------------------------------------------------------

# Six hours of barograph, five ways. The only thing that differs between the
# first two is the *sign of the derivative*, which is the entire thesis.
SCENARIOS: dict[str, dict[str, float]] = {
    "falling": {
        "start_pressure": 1017.0, "end_pressure": 1008.0, "wind": 0.42,
        "cloud": 0.86, "precip": 0.30, "light": 0.22, "golden": 0.78, "temp": -0.35,
        "humidity": 0.84,
    },
    "rising": {
        "start_pressure": 1006.0, "end_pressure": 1016.0, "wind": 0.26,
        "cloud": 0.24, "precip": 0.0, "light": 0.82, "golden": 0.05, "temp": 0.30,
        "humidity": 0.48,
    },
    "flat": {
        "start_pressure": 1012.0, "end_pressure": 1012.4, "wind": 0.22,
        "cloud": 0.92, "precip": 0.06, "light": 0.38, "golden": 0.10, "temp": -0.10,
        "humidity": 0.78,
    },
    "golden": {
        "start_pressure": 1014.0, "end_pressure": 1013.2, "wind": 0.18,
        "cloud": 0.30, "precip": 0.0, "light": 0.34, "golden": 0.92, "temp": 0.15,
        "humidity": 0.60,
    },
    "squall": {
        "start_pressure": 1015.0, "end_pressure": 1004.0, "wind": 0.88,
        "cloud": 0.95, "precip": 0.72, "light": 0.16, "golden": 0.20, "temp": -0.50,
        "humidity": 0.93,
    },
}


class FixtureWeather:
    """A barograph in a jar. Deterministic, offline, six hours deep."""

    name = "fixture"

    def __init__(self, scenario: str = "falling") -> None:
        self.scenario = scenario if scenario in SCENARIOS else "falling"

    async def window(self, coords: Coordinates, at: datetime | None = None) -> WeatherWindow:
        s = SCENARIOS[self.scenario]
        base = at or datetime.now(timezone.utc)
        samples = []
        steps = 7
        for i in range(steps):
            frac = i / (steps - 1)
            samples.append(
                {
                    "at": (base - timedelta(hours=6 - i * 1.0)).isoformat(),
                    "pressure": s["start_pressure"]
                    + (s["end_pressure"] - s["start_pressure"]) * frac,
                    "wind": s["wind"],
                    "cloud": s["cloud"],
                    "precip": s["precip"],
                    "light": s["light"],
                    "golden": s["golden"],
                    "humidity": s["humidity"],
                    "temp_anomaly": s["temp"],
                }
            )
        return WeatherWindow(
            coordinates=coords, observed_at=base, samples=samples, source="fixture"
        )


class FixtureOracle:
    """A tag graph in a box. Never touches the network."""

    name = "fixture"

    def __init__(self, corpus=_CORPUS) -> None:
        self._tracks = [
            Track(
                title=title,
                artist=artist,
                duration_ms=secs * 1000,
                tags=list(tags),
                listeners=listeners,
                playcount=listeners * 7,
                lastfm_url=f"https://www.last.fm/music/{artist.replace(' ', '+')}",
            )
            for artist, title, secs, listeners, tags in corpus
        ]

    # -- protocol ------------------------------------------------------
    def estimate_from_tags(self, tags: Sequence[str]) -> SonicVector:
        acc: dict[str, list[float]] = {}
        for tag in tags:
            profile = _TAG_PROFILES.get(str(tag).lower())
            if not profile:
                continue
            for dim, value in profile.items():
                acc.setdefault(dim, []).append(value)
        if not acc:
            # Unknown tags still deserve a stable, non-neutral answer -- a
            # hash keeps it deterministic without pretending to knowledge.
            h = hashlib.sha1("".join(sorted(str(t) for t in tags)).encode()).digest()
            return SonicVector.from_array([0.35 + (h[i] % 60) / 200.0 for i in range(7)])
        return SonicVector(**{dim: sum(v) / len(v) for dim, v in acc.items()})

    async def estimate(self, track: Track) -> Track:
        return track.model_copy(update={"estimated": self.estimate_from_tags(track.tags)})

    async def taste_vector(self, handle: str) -> TasteVector:
        return TasteVector(
            centroid=SonicVector(valence=0.38, energy=0.44, tempo=0.42, acousticness=0.52,
                                 density=0.48, grit=0.42, spatiality=0.76),
            spread=SonicVector(valence=0.18, energy=0.20, tempo=0.16, acousticness=0.22,
                               density=0.18, grit=0.20, spatiality=0.14),
            top_tags={"post-rock": 1.0, "slowcore": 0.86, "ambient": 0.72,
                      "dream pop": 0.61, "post-punk": 0.44, "jazz": 0.31},
            top_artists=["Talk Talk", "Low", "Grouper", "Slowdive", "Bark Psychosis"],
            scrobble_count=48_210,
            confidence=0.82,
            source="fixture",
        )

    async def candidates(
        self,
        *,
        taste: TasteVector,
        seed_tags: Sequence[str],
        corridor: GenreCorridor,
        limit: int = 400,
    ) -> list[Track]:
        # The tags asked for outrank the corridor, which acts as a filter. A
        # chart for "slowcore" is not a chart for "everything with guitars".
        seeds = {str(t).lower() for t in seed_tags}
        corridor_tags = {t.lower() for t in (corridor.tags or ())}
        top_artists = {a.lower() for a in (taste.top_artists or ())}
        top_tags = taste.top_tags or {}

        scored: list[tuple[float, str, Track]] = []
        for track in self._tracks:
            tags = {t.lower() for t in track.tags}
            corridor_hit = len(tags & corridor_tags)
            if corridor_tags and not corridor_hit:
                continue
            relevance = (
                2.0 * len(tags & seeds)
                + 0.6 * corridor_hit
                + 1.4 * sum(top_tags.get(t, 0.0) for t in tags)
                + 2.0 * (1.0 if track.artist.lower() in top_artists else 0.0)
            )
            if relevance <= 0:
                continue
            scored.append((-relevance, track.key, track))

        scored.sort()
        return [t for _, _, t in scored[: max(1, limit)]]


class M3USink:
    """Writes nowhere, returns a real M3U payload. Good enough to paste."""

    kind = "m3u"

    async def available(self, user_id: str | None) -> bool:
        return True

    async def write(self, playlist: Playlist, *, user_id: str | None = None) -> SinkResult:
        lines = ["#EXTM3U", f"#PLAYLIST:{playlist.title}"]
        for st in playlist.tracks:
            secs = int((st.track.duration_ms or 0) / 1000)
            lines.append(f"#EXTINF:{secs},{st.track.display}")
            lines.append(st.track.lastfm_url or st.track.display)
        payload = "\n".join(lines)
        return SinkResult(
            kind="m3u", ok=True, matched=len(playlist.tracks),
            requested=len(playlist.tracks), payload=payload,
            message=f"{len(playlist.tracks)} tracks written to an M3U payload.",
        )


class MemoryAlmanac:
    """Remembers this process only, and forgives itself for it."""

    def __init__(self) -> None:
        self.saved: list[Playlist] = []

    async def record_forge(self, playlist: Playlist) -> str:
        self.saved.append(playlist)
        return playlist.id

    async def record_feedback(self, *args, **kwargs) -> None:
        return None

    async def history(self, user_id: str, limit: int = 50) -> list[Playlist]:
        return self.saved[-limit:]

    async def nudge(self, user_id: str) -> list[list[float]] | None:
        return None


class DemoSettings:
    default_playlist_length = 18
    candidate_pool_size = 400
    max_tracks_per_artist = 2
    has_lastfm = False
    has_spotify = False


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

_ROLE_GLYPH = {
    "opener": "\u25b8",
    "build": "\u2571",
    "peak": "\u25b2",
    "descent": "\u2572",
    "closer": "\u25c2",
    "body": "\u2500",
}


def _bar(value: float, width: int = 18) -> str:
    filled = int(round(max(0.0, min(1.0, value)) * width))
    return "\u2588" * filled + dim("\u2591" * (width - filled))


def _fmt_duration(ms: int) -> str:
    total = int(ms / 1000)
    return f"{total // 60}:{total % 60:02d}"


def render(result, *, scenario: str) -> str:
    playlist = result.playlist
    sky = playlist.sky
    target = playlist.sonic_target
    rat = playlist.rationale
    out: list[str] = []

    out.append(rule("\u250c", "\u2500", "\u2510"))
    out.append(row(" " + bold(gold("BAROGROOVE")) + dim("  \u00b7  your sky has a soundtrack")))
    out.append(row(" " + dim(f"scenario={scenario}  theme={playlist.theme_id}  "
                             f"genre={playlist.genre_id}  {result.elapsed_ms}ms")))
    out.append(rule("\u251c", "\u2500", "\u2524", "SKY"))

    for line in rat.sky_reading:
        out.append(row(" " + sky_blue("\u25cf ") + line))
    out.append(row(" " + dim(f"observed {sky.observed_at:%Y-%m-%d %H:%M} \u00b7 "
                             f"{'stale' if sky.stale else 'fresh'}")))

    out.append(rule("\u251c", "\u2500", "\u2524", "SONIC TARGET"))
    dims = [
        ("valence", target.valence), ("energy", target.energy),
        ("tempo", target.tempo), ("acousticness", target.acousticness),
        ("density", target.density), ("grit", target.grit),
        ("spatiality", target.spatiality),
    ]
    for name, value in dims:
        extra = f"  {target.tempo_bpm:5.1f} BPM" if name == "tempo" else ""
        out.append(row(f"  {name:<13}{_bar(value)} {value:.2f}{gold(extra)}"))

    out.append(rule("\u251c", "\u2500", "\u2524", "RATIONALE"))
    out.append(row(" " + bold(rat.headline)))
    out.append(row())
    for line in wrap(rat.body, indent=1):
        out.append(row(line))
    if rat.sonic_moves:
        out.append(row())
        for move in rat.sonic_moves:
            for i, line in enumerate(wrap(move, indent=3)):
                out.append(row((dim(" \u2192") if i == 0 else "   ") + line[2:]))
    if rat.taste_note:
        out.append(row())
        for line in wrap(rat.taste_note, indent=1):
            out.append(row(slate(line)))
    out.append(row())
    out.append(row(f" confidence {rat.confidence:.2f}"))

    out.append(rule("\u251c", "\u2500", "\u2524", f"TRACKLIST ({len(playlist.tracks)})"))
    for st in playlist.tracks:
        glyph = _ROLE_GLYPH.get(st.role, "\u2500")
        num = f"{st.position + 1:>2}"
        title = st.track.display
        if len(title) > 44:
            title = title[:43] + "\u2026"
        dur = _fmt_duration(st.track.duration_ms or 0)
        role_cell = "{:<8}".format(st.role)
        dur_cell = "{:>6}".format(dur)
        out.append(
            row(f" {dim(num)} {sky_blue(glyph)} {title:<44} {dim(role_cell)}{dim(dur_cell)}")
        )
        why = st.why or ""
        if why:
            for line in wrap(why, indent=6):
                out.append(row(dim(line)))

    out.append(rule("\u251c", "\u2500", "\u2524", "FOOTER"))
    out.append(row(f" {len(playlist.tracks)} tracks \u00b7 {_fmt_duration(playlist.duration_ms)} "
                   f"\u00b7 {len({t.track.artist for t in playlist.tracks})} artists"))
    if playlist.sink:
        out.append(row(f" sink: {playlist.sink.kind} \u00b7 {playlist.sink.message}"))
    if result.degraded:
        out.append(row())
        out.append(row(" " + gold("degraded:")))
        for d in result.degraded:
            for line in wrap(d, indent=3):
                out.append(row(gold(line)))
    else:
        out.append(row(" " + dim("no degradation \u2014 every subsystem answered")))
    out.append(rule("\u2514", "\u2500", "\u2518"))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


# The real fixture vocabulary lives in backend/app/sky/fixtures.py. These two
# aliases exist because "falling" and "rising" are what a human types when they
# want to see the headline effect.
SCENARIO_ALIASES = {
    "falling": "front_collapse",
    "rising": "ridge_building",
    "flat": "flat_grey",
    "frost": "first_frost",
    "heatwave": "heatwave_evening",
    "gusty": "gusty_front",
}


def _resolve_scenario(name: str) -> str:
    """Map a friendly name onto a real fixture scenario."""
    resolved = SCENARIO_ALIASES.get(name, name)
    if resolved not in REAL_SCENARIOS:
        raise SystemExit(
            f"unknown scenario {name!r}. Try one of: "
            + ", ".join(sorted(set(REAL_SCENARIOS) | set(SCENARIO_ALIASES)))
        )
    return resolved


def _build_forge(scenario: str) -> PlaylistForge:
    return PlaylistForge(
        settings=DemoSettings(),
        weather=FixtureWeatherSource(_resolve_scenario(scenario)),
        oracle=FixtureOracle(),
        sinks=[M3USink()],
        almanac=MemoryAlmanac(),
    )


async def _run(args: dict[str, str | int | None]) -> int:
    scenario = str(args.get("scenario") or "falling")
    request = ForgeRequest(
        coordinates=Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels"),
        theme_id=args.get("theme") or None,  # type: ignore[arg-type]
        genre_id=str(args.get("genre") or "any"),
        length=int(args.get("length") or 14),
        lastfm_user=None if args.get("no_taste") else "demo",
        sink="m3u",
        seed=int(args.get("seed") or 7),
        at=datetime(2026, 10, 17, 17, 40, tzinfo=timezone.utc),
    )

    if args.get("compare"):
        for scen in ("falling", "rising"):
            result = await _build_forge(scen).forge(request)
            print(render(result, scenario=scen))
            print()
        return 0

    result = await _build_forge(scenario).forge(request)
    print(render(result, scenario=scenario))
    return 0


def _parse(argv: Sequence[str]) -> dict[str, str | int | None]:
    """Minimal flag parsing. No argparse ceremony, no required arguments."""
    out: dict[str, str | int | None] = {}
    it = iter(argv)
    for token in it:
        if not token.startswith("--"):
            continue
        name = token[2:].replace("-", "_")
        if name in ("compare", "no_taste"):
            out[name] = "1"
            continue
        out[name] = next(it, None)
    return out


def main(argv: Iterable[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        print("  flags: --scenario " + "|".join(SCENARIOS))
        print("         --theme <id>  --genre <id>  --length <n>  --seed <n>")
        print("         --compare     --no-taste")
        return 0
    return asyncio.run(_run(_parse(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
