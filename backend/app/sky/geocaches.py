"""World Street-Art Geo-Cache Catalog for the BaroGroove Weathercaster.

Each geo-cache represents an iconic global street-art landmark across diverse
latitudes, micro-climates, and timezones. Selecting or rolling a geo-cache
shifts both the local solar/time-of-day window and the live barometric/weather
telemetry, inducing genuinely distinct weather-inspired Daylists.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field


class StreetArtGeoCache(BaseModel):
    """A curated street-art landmark with coordinates and timezone metadata."""

    id: str
    name: str
    city: str
    country: str
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    tz_offset_hours: float = Field(description="UTC offset in hours, e.g. -5.0 or +9.0")
    artist_highlight: str
    description: str
    vibe_tags: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.city})"

    def local_datetime(self, utc_now: datetime | None = None) -> datetime:
        now = utc_now or datetime.now(timezone.utc)
        tz = timezone(timedelta(hours=self.tz_offset_hours))
        return now.astimezone(tz)

    def local_time_label(self, utc_now: datetime | None = None) -> str:
        dt = self.local_datetime(utc_now)
        sign = "+" if self.tz_offset_hours >= 0 else ""
        offset_str = (
            f"UTC{sign}{int(self.tz_offset_hours)}"
            if self.tz_offset_hours.is_integer()
            else f"UTC{sign}{self.tz_offset_hours}"
        )
        return f"{dt.strftime('%H:%M')} ({offset_str})"

    def day_period(self, utc_now: datetime | None = None) -> str:
        hour = self.local_datetime(utc_now).hour
        if 5 <= hour < 12:
            return "morning"
        if 12 <= hour < 17:
            return "afternoon"
        if 17 <= hour < 22:
            return "evening"
        return "late night"


STREET_ART_GEOCACHES: tuple[StreetArtGeoCache, ...] = (
    StreetArtGeoCache(
        id="hosier_lane_melbourne",
        name="Hosier Lane",
        city="Melbourne",
        country="Australia",
        lat=-37.8166,
        lon=144.9692,
        tz_offset_hours=10.0,
        artist_highlight="Adnate, Lushsux & Melbourne stencil collective",
        description="Bluestone laneway gallery where aerosol murals evolve by the hour under Southern Ocean fronts.",
        vibe_tags=["dub", "post-punk", "electronic", "psych-rock"],
    ),
    StreetArtGeoCache(
        id="wynwood_walls_miami",
        name="Wynwood Walls",
        city="Miami",
        country="USA",
        lat=25.8011,
        lon=-80.1994,
        tz_offset_hours=-5.0,
        artist_highlight="Shepard Fairey, Os Gemeos, Maya Hayuk & Futura",
        description="Sun-drenched tropical warehouse district painted in neon geometrics and Atlantic trade-wind humidity.",
        vibe_tags=["electro-funk", "latin-breaks", "house", "synthwave"],
    ),
    StreetArtGeoCache(
        id="beco_do_batman_sao_paulo",
        name="Beco do Batman",
        city="São Paulo",
        country="Brazil",
        lat=-23.5566,
        lon=-46.6865,
        tz_offset_hours=-3.0,
        artist_highlight="Kobra, Speto, Cranio & Vila Madalena crews",
        description="Labyrinthine Vila Madalena cobblestones wrapped head-to-toe in psychedelic tropicalia and Paulistano graffiti.",
        vibe_tags=["mpb", "bossa-nova", "baile-funk", "afro-brazilian"],
    ),
    StreetArtGeoCache(
        id="east_side_gallery_berlin",
        name="East Side Gallery",
        city="Berlin",
        country="Germany",
        lat=52.5050,
        lon=13.4397,
        tz_offset_hours=1.0,
        artist_highlight="Thierry Noir, Dmitri Vrubel & 100+ international muralists",
        description="1.3 km open-air monument along the Spree River where continental pressure systems sweep across historic concrete.",
        vibe_tags=["minimal-techno", "krautrock", "industrial", "ambient"],
    ),
    StreetArtGeoCache(
        id="shimokitazawa_tokyo",
        name="Shimokitazawa Mural Alley",
        city="Tokyo",
        country="Japan",
        lat=35.6616,
        lon=139.6669,
        tz_offset_hours=9.0,
        artist_highlight="Hitotzuki (Kami & Sasu), Dragon76 & Tokyo shutter painters",
        description="Bohemian narrow alleys of vinyl shops, shutters painted at night, and crisp Pacific Kanto weather.",
        vibe_tags=["city-pop", "shibuya-kei", "jazz-fusion", "lo-fi-beats"],
    ),
    StreetArtGeoCache(
        id="comuna_13_medellin",
        name="Comuna 13 Escalators",
        city="Medellín",
        country="Colombia",
        lat=6.2520,
        lon=-75.6226,
        tz_offset_hours=-5.0,
        artist_highlight="Chota 13, YesGraff & Casa Kolacho collective",
        description="Andean hillside amphitheater of color, outdoor escalators, hip-hop culture, and eternal spring mountain storms.",
        vibe_tags=["cumbia-digital", "latin-hip-hop", "champeta", "reggaeton"],
    ),
    StreetArtGeoCache(
        id="cerro_alegre_valparaiso",
        name="Museo a Cielo Abierto",
        city="Valparaíso",
        country="Chile",
        lat=-33.0472,
        lon=-71.6127,
        tz_offset_hours=-4.0,
        artist_highlight="Inti, Charquipunk & Un Kolor Distinto",
        description="Steep Pacific port stairways and funiculars overlooking Humboldt Current fog and maritime squalls.",
        vibe_tags=["nueva-cancion", "indie-folk", "post-rock", "ambient-dub"],
    ),
    StreetArtGeoCache(
        id="maboneng_johannesburg",
        name="Maboneng Precinct",
        city="Johannesburg",
        country="South Africa",
        lat=-26.2044,
        lon=28.0583,
        tz_offset_hours=2.0,
        artist_highlight="Falko One, Faith47 & Ricky Lee Gordon",
        description="High-veld urban arts district at 1,750m altitude where dramatic afternoon electrical storms charge the air.",
        vibe_tags=["amapiano", "afro-tech", "kwaito", "spiritual-jazz"],
    ),
    StreetArtGeoCache(
        id="brick_lane_shoreditch",
        name="Brick Lane & Redchurch St",
        city="London",
        country="UK",
        lat=51.5215,
        lon=-0.0715,
        tz_offset_hours=0.0,
        artist_highlight="Banksy, ROA, Stik, Invader & Ben Eine",
        description="Victorian East End brick walls layered with paste-ups and stencils under Thames Estuary drizzle.",
        vibe_tags=["uk-garage", "trip-hop", "drum-and-bass", "dubstep"],
    ),
    StreetArtGeoCache(
        id="clarion_alley_sf",
        name="Clarion Alley",
        city="San Francisco",
        country="USA",
        lat=37.7630,
        lon=-122.4211,
        tz_offset_hours=-8.0,
        artist_highlight="Clarion Alley Mural Project (CAMP) & Mission muralists",
        description="Block-long Mission District corridor where Golden Gate marine layer fog meets sunny micro-climate pockets.",
        vibe_tags=["shoegaze", "dream-pop", "west-coast-hip-hop", "indie-rock"],
    ),
    StreetArtGeoCache(
        id="rue_denoyez_paris",
        name="Rue Dénoyez Belleville",
        city="Paris",
        country="France",
        lat=48.8716,
        lon=2.3849,
        tz_offset_hours=1.0,
        artist_highlight="Jef Aérosol, Miss.Tic & Belleville street artists",
        description="Cobblestone Belleville passage overflowing with mosaic tiles, wheatpastes, and Parisian slate-grey skies.",
        vibe_tags=["french-touch", "chanson-electro", "nu-jazz", "downtempo"],
    ),
    StreetArtGeoCache(
        id="wall_poetry_reykjavik",
        name="Wall Poetry Grandi",
        city="Reykjavík",
        country="Iceland",
        lat=64.1466,
        lon=-21.9426,
        tz_offset_hours=0.0,
        artist_highlight="Evoca1, Tankpetrol & Iceland Airwaves collaborations",
        description="Sub-arctic harbor walls pairing visual muralists with Nordic musicians under North Atlantic low-pressure lows.",
        vibe_tags=["ambient", "neo-classical", "post-rock", "nordic-electronica"],
    ),
    StreetArtGeoCache(
        id="ximending_tattoo_lane_taipei",
        name="America Street Cinema Park",
        city="Taipei",
        country="Taiwan",
        lat=25.0457,
        lon=121.5034,
        tz_offset_hours=8.0,
        artist_highlight="ANO, Reach, Bounce & Taipei graffiti crews",
        description="Neon-soaked Ximending cul-de-sac where subtropical monsoon fronts and warm night rains glisten on aerosol walls.",
        vibe_tags=["mandopop-indie", "synth-pop", "vaporwave", "future-bass"],
    ),
    StreetArtGeoCache(
        id="roma_norte_cdmx",
        name="Colonia Roma Norte Murals",
        city="Mexico City",
        country="Mexico",
        lat=19.4194,
        lon=-99.1626,
        tz_offset_hours=-6.0,
        artist_highlight="Saner, Sego, Curiot & Dhear",
        description="Tree-lined avenues at 2,240m elevation painted in neo-mythological Mexican surrealism and high-valley sunlight.",
        vibe_tags=["latin-alternative", "cumbia-rebajada", "psych-cumbia", "electro-acoustic"],
    ),
    StreetArtGeoCache(
        id="parcours_bd_brussels",
        name="Parcours BD Comic Strip Trail",
        city="Brussels",
        country="Belgium",
        lat=50.8503,
        lon=4.3517,
        tz_offset_hours=1.0,
        artist_highlight="Hergé, Franquin, Bonom & Brussels muralists",
        description="Gabled Brussels facades celebrating Franco-Belgian ligne claire art and nocturnal Bonom rooftop creatures.",
        vibe_tags=["new-beat", "ebm", "ethio-jazz", "electronic-chanson"],
    ),
)

_BY_ID: dict[str, StreetArtGeoCache] = {g.id: g for g in STREET_ART_GEOCACHES}


def get_geocache(geocache_id: str | None) -> StreetArtGeoCache | None:
    """Lookup a street-art landmark by ID, or pick one pseudo-randomly if 'random'."""
    if not geocache_id:
        return None
    if geocache_id.strip().lower() == "random":
        return random.choice(STREET_ART_GEOCACHES)
    return _BY_ID.get(geocache_id.strip().lower())


def pick_random_geocache(exclude_id: str | None = None) -> StreetArtGeoCache:
    """Pick a random street-art landmark, optionally excluding the current one."""
    pool = [g for g in STREET_ART_GEOCACHES if g.id != exclude_id]
    if not pool:
        pool = list(STREET_ART_GEOCACHES)
    return random.choice(pool)


def find_nearest_geocache(lat: float, lon: float, max_deg: float = 0.25) -> StreetArtGeoCache | None:
    """Return the matching street-art landmark if coordinates are within max_deg."""
    best: StreetArtGeoCache | None = None
    best_dist = max_deg * max_deg
    for g in STREET_ART_GEOCACHES:
        d2 = (g.lat - lat) ** 2 + (g.lon - lon) ** 2
        if d2 <= best_dist:
            best_dist = d2
            best = g
    return best
