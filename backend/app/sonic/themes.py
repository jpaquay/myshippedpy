"""The eight themes: narrative lenses that bend the transfer's output.

A theme is not a genre and it is not a mood preset. It is a *reading* of the
sky -- an argument about what today is, which the matrix on its own cannot make
because the matrix is nine independent scalars and today is a story.

Mechanically a theme is a bias vector plus a weight: after
:func:`~.matrix.apply_transfer` has done the physics, the target is pulled
``bias_weight`` of the way toward ``bias``. The weight is small on purpose
(0.33-0.42). A theme should colour a result, not overwrite it -- if the sky
says 83 BPM and the theme says 130, the honest answer is somewhere in between,
because the sky is the thing that is actually happening.

Each theme also carries an ``affinity`` map over ``SKY_DIMS``, which runs in
reverse: given a sky, :func:`suggest_theme` scores every theme's affinity as a
normalised dot product and proposes the best fit. Signed dims take signed
weights -- ``first_frost`` wants ``temp_norm_deviation`` at -0.9, meaning "the
colder relative to normal, the more this is me".

House style for the copy: dry, literate, specific, confident. A good
record-shop staff pick, not a wellness app. Nobody says "vibes". Nobody says
"cozy". If a tagline could appear on a scented candle, it gets rewritten.
"""

from __future__ import annotations

from ..contracts import SKY_DIMS, THEME_IDS, SkyVector, SonicVector, Theme, clamp
from ..errors import ThemeNotFound

__all__ = ["THEMES", "get_theme", "list_themes", "suggest_theme", "score_themes"]


# ---------------------------------------------------------------------------
# The eight
# ---------------------------------------------------------------------------

_PETRICHOR = Theme(
    id="petrichor",
    name="Petrichor",
    tagline="The twenty minutes before it breaks.",
    description=(
        "Petrichor is not rain. It is the smell of the first drops landing on stone that "
        "has been hot all day -- geosmin off the soil bacteria, ozone dragged down from "
        "altitude by the downdraught running ahead of the cell. You can smell a storm "
        "before you can see it, and this is the music for that gap: held, humid, a little "
        "too still, waiting on a downbeat that has not arrived yet. The tension in this "
        "theme is anticipatory. When the rain actually starts, it resolves."
    ),
    bias=SonicVector(
        valence=0.38,
        energy=0.40,
        tempo=0.36,  # ~103 BPM
        acousticness=0.58,
        density=0.34,
        grit=0.42,
        spatiality=0.72,
    ),
    bias_weight=0.36,
    seed_tags=[
        "ambient",
        "slowcore",
        "post-rock",
        "rainy day",
        "melancholy",
        "dream pop",
        "shoegaze",
        "4ad",
    ],
    avoid_tags=["party", "eurodance", "happy hardcore", "power pop", "hair metal"],
    palette={
        "ink": "#1B2430",  # wet slate before the light goes
        "slate": "#33414F",
        "stone": "#8C7B68",  # the hot flagstone the first drops hit
        "ozone": "#7FA6A0",
        "flare": "#D9A441",  # the last sunlight under the anvil
    },
    voice="hushed",
    affinity={
        "pressure_trend_6h": -0.90,  # the defining fact: it is falling
        "pressure_norm_deviation": -0.30,
        "temp_norm_deviation": 0.40,  # hot stone is the other half of the smell
        "gust_variance": 0.30,  # the outflow arrives before the rain
        "cloud_depth": 0.55,
        "precip_intensity": 0.30,  # a little. This is the *before*, not the during
    },
)

_GOLDEN_HOUR = Theme(
    id="golden_hour",
    name="Golden Hour",
    tagline="Forty minutes of good light and nowhere to be.",
    description=(
        "The sun is low enough that everything picks up an edge and a long shadow, and "
        "warm enough that nobody wants to go inside yet. It is a generous hour and a "
        "faintly sad one, because the light is only this good on its way out. Rhodes, "
        "brushes, an upright bass that refuses to hurry, side two of a record you have "
        "owned since school. Warm and slow -- which, and this is the whole trick, is not "
        "the same axis as happy and fast."
    ),
    bias=SonicVector(
        valence=0.66,
        energy=0.44,
        tempo=0.34,  # ~101 BPM
        acousticness=0.66,
        density=0.42,
        grit=0.30,
        spatiality=0.60,
    ),
    bias_weight=0.34,
    seed_tags=[
        "soul",
        "spiritual jazz",
        "sunday morning",
        "bossa nova",
        "singer-songwriter",
        "mellow",
        "70s",
        "smooth",
    ],
    avoid_tags=["black metal", "harsh noise", "industrial", "grindcore", "speedcore"],
    palette={
        "amber": "#E0A458",
        "clay": "#C36F3A",
        "wine": "#7A3B2E",
        "dusk": "#3E3552",  # the sky opposite the sun, already going
        "cream": "#F3E4C8",
    },
    voice="warm",
    affinity={
        "golden_hour_proximity": 1.00,
        "sun_elevation": 0.30,  # still above the horizon -- this is what splits it from blue_hour
        "cloud_depth": -0.45,  # a lid cancels golden hour outright
        "precip_intensity": -0.40,
        "temp_norm_deviation": 0.25,
    },
)

_NORDIC_FOG = Theme(
    id="nordic_fog",
    name="Nordic Fog",
    tagline="Visibility 300 metres. No hurry.",
    description=(
        "Less weather than the absence of it. Deep cloud, saturated air, no wind, no "
        "shadow and no reliable sense of what time it is. Sound behaves strangely in fog "
        "-- it carries and it deadens in the same breath, which is why a foghorn is "
        "audible for miles and a conversation ten metres away is not. Slow harmonic "
        "motion, a great deal of room tone, nothing that resolves in a hurry. Music for a "
        "day with no events in it."
    ),
    bias=SonicVector(
        valence=0.36,
        energy=0.26,
        tempo=0.28,  # ~94 BPM
        acousticness=0.48,
        density=0.22,
        grit=0.34,
        spatiality=0.82,
    ),
    bias_weight=0.40,
    seed_tags=[
        "ambient",
        "drone",
        "minimalism",
        "modern classical",
        "icelandic",
        "post-rock",
        "atmospheric",
        "field recordings",
    ],
    avoid_tags=["dance", "funk", "pop punk", "disco", "hi-nrg"],
    palette={
        "fog": "#C9D1D3",
        "pine": "#3C4A47",
        "iron": "#5A646B",
        "moss": "#7C8C7A",
        "bone": "#EDEFEE",
    },
    voice="spare",
    affinity={
        "cloud_depth": 1.00,
        "gust_variance": -0.70,  # fog cannot survive wind; stillness is definitional
        "precip_intensity": -0.15,
        "sun_elevation": -0.20,
        "temp_norm_deviation": -0.30,
        "daylight_delta": -0.20,
    },
)

_STORM_FRONT = Theme(
    id="storm_front",
    name="Storm Front",
    tagline="The barometer is in free fall. Turn it up.",
    description=(
        "A front is a boundary you can hear coming. The gust spread widens, the pressure "
        "drops off a cliff, and the light goes an unpleasant yellow-grey that photographs "
        "badly and feels tremendous. There is nothing sad about this. It is the most "
        "exciting weather there is, and the only honest response is kinetic: loud in "
        "texture rather than in volume, rhythmically unstable in a way that finally has an "
        "excuse, and completely uninterested in resolving."
    ),
    bias=SonicVector(
        valence=0.34,
        energy=0.82,
        tempo=0.58,  # ~130 BPM
        acousticness=0.22,
        density=0.76,
        grit=0.78,
        spatiality=0.56,
    ),
    bias_weight=0.42,  # the strongest hand in the deck; a squall is not subtle
    seed_tags=[
        "post-punk",
        "krautrock",
        "noise rock",
        "industrial",
        "no wave",
        "motorik",
        "post-hardcore",
        "dark",
    ],
    avoid_tags=["easy listening", "lounge", "chillout", "new age", "smooth jazz"],
    palette={
        "squall": "#20262E",
        "bruise": "#454B6B",
        "sodium": "#D6A14B",  # streetlights coming on at three in the afternoon
        "flint": "#6C7480",
        "strike": "#EDE6DA",
    },
    voice="clipped",
    affinity={
        "pressure_trend_6h": -1.00,
        "pressure_norm_deviation": -0.50,
        "gust_variance": 0.95,
        "cloud_depth": 0.50,
        "precip_intensity": 0.60,
    },
)

_HEATWAVE_CRUISE = Theme(
    id="heatwave_cruise",
    name="Heatwave Cruise",
    tagline="Too hot to think. Ideal for driving.",
    description=(
        "Somewhere above thirty degrees the day gives up on productivity and becomes "
        "purely physical. Everything slows, the light goes flat and white, tarmac starts "
        "lying to you about puddles, and the only sensible plan left is motion with the "
        "windows down. Long-form, groove-led, mostly electric, entirely without urgency. "
        "Heat is high-energy and low-tempo at once, which almost no other weather manages."
    ),
    bias=SonicVector(
        valence=0.62,
        energy=0.58,
        tempo=0.44,  # ~113 BPM -- a cruise, not a chase
        acousticness=0.30,
        density=0.50,
        grit=0.44,
        spatiality=0.40,
    ),
    bias_weight=0.33,
    seed_tags=[
        "driving",
        "krautrock",
        "desert blues",
        "psychedelic",
        "dub",
        "boogie",
        "funk",
        "summer",
    ],
    avoid_tags=["christmas", "winter", "black metal", "emo", "sadcore"],
    palette={
        "tarmac": "#4A4340",
        "haze": "#E8D9B5",
        "sun": "#F0B429",
        "rust": "#B4553A",
        "sky": "#8FB8CE",
    },
    voice="loose",
    affinity={
        "temp_norm_deviation": 1.00,
        "sun_elevation": 0.70,
        "gust_variance": -0.25,  # heatwaves are still; that stillness is the oppression
        "cloud_depth": -0.60,
        "precip_intensity": -0.50,
    },
)

_BLUE_HOUR = Theme(
    id="blue_hour",
    name="Blue Hour",
    tagline="The sun has gone and the lights aren't on yet.",
    description=(
        "The twenty-five minutes after sunset when the sky holds a colour with no daytime "
        "equivalent and the streetlights have not caught up. Photographers quietly rate it "
        "above golden hour and they are right: the light is coming from everywhere at once "
        "and casting nothing. Synthetic, cool, unhurried, faintly cinematic. Music that "
        "sounds like a city seen from a train you are not getting off."
    ),
    bias=SonicVector(
        valence=0.44,
        energy=0.42,
        tempo=0.42,  # ~110 BPM
        acousticness=0.24,
        density=0.44,
        grit=0.30,
        spatiality=0.70,
    ),
    bias_weight=0.36,
    seed_tags=[
        "cold wave",
        "synthpop",
        "dream pop",
        "downtempo",
        "trip hop",
        "ethereal",
        "minimal wave",
        "nightdrive",
    ],
    avoid_tags=["country", "bluegrass", "comedy", "novelty", "happy"],
    palette={
        "indigo": "#26355C",
        "cobalt": "#3F5C9A",
        "neon": "#7FB3D5",
        "plum": "#553A5C",
        "salt": "#DCE3EE",
    },
    voice="cool",
    affinity={
        "golden_hour_proximity": 0.70,  # shares the window with golden_hour...
        "sun_elevation": -0.55,  # ...and is separated from it entirely by this sign
        "cloud_depth": 0.10,
        "precip_intensity": -0.20,
        "daylight_delta": -0.25,
    },
)

_FIRST_FROST = Theme(
    id="first_frost",
    name="First Frost",
    tagline="Minus two, no wind, and the year has turned.",
    description=(
        "A clear night bleeds heat straight out to space, the ground drops below zero, and "
        "you wake into a world with an edge on it. Cold air is denser and carries sound "
        "further, which is exactly why the first frost morning is both the quietest and "
        "the most detailed of the year -- you can hear a gate close three streets away. "
        "High, brittle, close-mic'd, and considerably more hopeful than the temperature "
        "suggests. Frost arrives with high pressure, and high pressure is good news."
    ),
    bias=SonicVector(
        valence=0.52,
        energy=0.38,
        tempo=0.36,  # ~103 BPM
        acousticness=0.78,
        density=0.30,
        grit=0.22,  # the cleanest theme in the set; frost has no haze in it
        spatiality=0.58,
    ),
    bias_weight=0.35,
    seed_tags=[
        "folk",
        "modern classical",
        "chamber pop",
        "slowcore",
        "acoustic",
        "winter",
        "piano",
        "melancholy",
    ],
    avoid_tags=["dubstep", "big beat", "hard rock", "reggaeton", "summer"],
    palette={
        "rime": "#DCE7EC",
        "steel": "#7E93A0",
        "spruce": "#2F4442",
        "ember": "#C4763F",  # the one warm thing in the frame
        "paper": "#F6F5F1",
    },
    voice="dry",
    affinity={
        "temp_norm_deviation": -0.90,
        "pressure_trend_6h": 0.35,  # frost rides in behind a building high
        "pressure_norm_deviation": 0.45,
        "sun_elevation": 0.15,
        "gust_variance": -0.50,  # wind stirs the boundary layer and kills the frost
        "cloud_depth": -0.70,  # cloud is a blanket; frost needs a clear sky to radiate
        "precip_intensity": -0.35,
        "daylight_delta": -0.35,
    },
)

_SIROCCO = Theme(
    id="sirocco",
    name="Sirocco",
    tagline="A warm wind from the wrong direction.",
    description=(
        "The sirocco comes up off the Sahara, arrives ten degrees too warm for the season, "
        "carries enough dust to turn the light orange and put a film on every car in the "
        "city, and makes everyone irritable in a way the forecast cannot account for. Warm "
        "and unsettling simultaneously, which most weather never manages -- warm usually "
        "means good. Modal, droning, percussive, sand in the tape heads and no resolution "
        "on offer."
    ),
    bias=SonicVector(
        valence=0.42,
        energy=0.62,
        tempo=0.48,  # ~118 BPM
        acousticness=0.52,
        density=0.62,
        grit=0.68,
        spatiality=0.52,
    ),
    bias_weight=0.38,
    seed_tags=[
        "desert blues",
        "tuareg",
        "gnawa",
        "ethio-jazz",
        "psychedelic",
        "drone",
        "raga",
        "krautrock",
    ],
    avoid_tags=["twee", "chiptune", "christmas", "shoegaze", "easy listening"],
    palette={
        "dust": "#C9A227",
        "sand": "#E3CFA5",
        "kiln": "#9A4B25",
        "shade": "#4A3B32",
        "sky": "#B7B49E",  # not blue. Nothing is blue during a sirocco
    },
    voice="wry",
    affinity={
        "temp_norm_deviation": 0.85,  # warm *for the season* -- that is the whole complaint
        "gust_variance": 0.80,
        "pressure_trend_6h": -0.30,
        "pressure_norm_deviation": -0.35,
        "cloud_depth": -0.20,
        "precip_intensity": -0.45,
    },
)


THEMES: dict[str, Theme] = {
    theme.id: theme
    for theme in (
        _PETRICHOR,
        _GOLDEN_HOUR,
        _NORDIC_FOG,
        _STORM_FRONT,
        _HEATWAVE_CRUISE,
        _BLUE_HOUR,
        _FIRST_FROST,
        _SIROCCO,
    )
}

# The contract froze the eight ids. If this file and contracts.py ever disagree
# about what the themes are, everything downstream quietly picks a side.
if tuple(THEMES) != tuple(sorted(THEMES, key=THEME_IDS.index)) or set(THEMES) != set(THEME_IDS):
    raise RuntimeError(f"THEMES {sorted(THEMES)} does not match contracts.THEME_IDS {sorted(THEME_IDS)}")

for _theme in THEMES.values():
    _unknown = set(_theme.affinity) - set(SKY_DIMS)
    if _unknown:
        raise RuntimeError(f"theme {_theme.id!r} has affinity for unknown sky dims: {sorted(_unknown)}")


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def get_theme(theme_id: str) -> Theme:
    """Fetch a theme by id.

    Raises :class:`ThemeNotFound` rather than falling back. A theme is a user's
    explicit choice, and silently serving them a different one is worse than an
    error. (Genre corridors take the opposite view -- see
    :func:`~.corridors.get_corridor` -- because a genre is a filter, and an
    unrecognised filter should never kill a forge.)
    """
    try:
        return THEMES[theme_id]
    except KeyError:
        raise ThemeNotFound(
            f"unknown theme {theme_id!r}; known themes: {', '.join(THEMES)}"
        ) from None


def list_themes() -> list[Theme]:
    """All eight, in the canonical contract order."""
    return [THEMES[theme_id] for theme_id in THEME_IDS]


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------


def _affinity_score(theme: Theme, sky: SkyVector) -> float:
    """Normalised dot product of a theme's affinity against a sky, in ``[-1, 1]``.

    Dividing by the sum of absolute weights is what makes themes with six
    affinity terms comparable to themes with four. Without it, ``first_frost``
    -- which cares about eight of the nine dims -- would win nearly every sky
    simply by having more surface area, which is a scoring bug that looks
    convincingly like a personality.
    """
    values = sky.as_dict()
    weight_total = sum(abs(w) for w in theme.affinity.values())
    if weight_total <= 0.0:
        return 0.0
    dot = sum(weight * values[dim] for dim, weight in theme.affinity.items())
    return max(-1.0, min(1.0, dot / weight_total))


def score_themes(sky: SkyVector) -> list[tuple[Theme, float]]:
    """Every theme scored against ``sky``, best first. Ties break on contract order."""
    scored = [(THEMES[tid], _affinity_score(THEMES[tid], sky)) for tid in THEME_IDS]
    scored.sort(key=lambda pair: (-pair[1], THEME_IDS.index(pair[0].id)))
    return scored


def suggest_theme(sky: SkyVector) -> tuple[Theme, float]:
    """Pick the theme this sky is asking for, with a confidence.

    Confidence is built from two independent things, because they fail
    independently:

    * **fit** -- how strongly the winner's affinity actually aligns with the
      sky. A sky can match a theme's shape weakly and still match it best.
    * **margin** -- how far clear of the runner-up it finished. A collapsing
      barometer with rain is unambiguously ``storm_front``; a mild overcast
      Tuesday is four themes in a photo finish, and the card should say so
      instead of projecting false certainty.

    A perfectly neutral sky scores 0 fit and 0 margin and lands at 0.15, which
    is the correct amount of confidence to have about nothing at all.
    """
    ranked = score_themes(sky)
    best, best_fit = ranked[0]
    runner_up_fit = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = max(0.0, best_fit - runner_up_fit)

    confidence = 0.15 + 0.65 * max(0.0, best_fit) + 1.00 * margin
    if sky.stale:
        # Last-known-good sky. The reading may be hours old; the theme it
        # implies is a guess about a sky we cannot currently see.
        confidence -= 0.15
    return best, round(clamp(confidence, 0.0, 0.97), 3)
