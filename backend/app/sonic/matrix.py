"""BAROGROOVE's transfer function: nine numbers about the sky, seven about music.

WHY THIS FILE EXISTS
====================
Every weather-playlist toy ever shipped implements the same lookup table::

    rain  -> sad songs
    sun   -> happy songs
    snow  -> Christmas

That is worthless, and not because it is simple. It is worthless because it is
reading the wrong variable. Weather's emotional signal does not live in the
absolute value. It lives in the **derivative**.

Eight degrees on a *falling* barometer, forty minutes before sunset, in the
third week of October -- the year visibly closing -- is a completely different
room from eight degrees on a *rising* barometer at ten in the morning in March.
Identical thermometer. Opposite records. Any system that cannot tell those two
apart has nothing to say about weather and music, and most of them cannot,
because they only ever asked the thermometer.

So the ``SkyVector`` is built derivative-first: pressure *trend* over six hours,
temperature *relative to this location's own recent norm*, day length *versus
yesterday*, the *spread* of gusts rather than the mean. Five of the nine dims
are signed rates of change or deviations from a local baseline. This file is
where that belief stops being a design manifesto and becomes arithmetic.

HOW IT WORKS
============
The model is deliberately, unfashionably linear::

    sonic = squash( BASE_SONIC + sky @ (TRANSFER_MATRIX + nudge) )

* ``BASE_SONIC`` is the **intercept**: what a perfectly neutral sky produces.
  Because the matrix only ever expresses *deflection from neutral*, every
  coefficient stays small, signed and legible. A reader can look at
  ``+0.22`` and know it is worth a fifth of the valence range. Nobody can read
  a 63-parameter absolute model.
* ``nudge`` is the per-user ridge-regression correction the Almanac learns from
  loves and skips. It is a delta on the coefficients, never a replacement, so a
  user can bend the model but never break it.
* Linear is a feature. It is the only functional form where
  :func:`explain_transfer` can hand the UI an exact, additive attribution --
  "pressure trend moved valence by -0.19" -- and have that be literally true
  rather than a post-hoc story. Explainability is the product. We are not
  trading it for two points of fit.

THE REFERENCE SKY
=================
``SkyVector.neutral()`` is all zeros. Physically that reads as: pressure
steady, pressure at the local norm, temperature at the local norm, **sun on the
horizon**, not golden hour, no gust spread, no cloud, no precipitation, day
length holding. Call it the blank sky. ``BASE_SONIC`` is what the blank sky
sounds like, and every coefficient below is a push away from it.

The four unsigned dims (``golden_hour_proximity``, ``gust_variance``,
``cloud_depth``, ``precip_intensity``) live in ``[0, 1]``, so they can only ever
push in one direction from the blank sky. That is correct: there is no such
thing as negative rain. The five signed dims live in ``[-1, 1]`` and swing both
ways, which is exactly why they carry most of the weight in this table.

READING THE TABLE
=================
:data:`SKY_TO_SONIC` is the source of truth and is meant to be *edited by a
human with an opinion*. The dense :data:`TRANSFER_MATRIX` is derived from it at
import time so the arithmetic is a flat list-of-lists, but nobody should ever
hand-edit the dense form. Every non-zero coefficient carries its argument
inline. Cells that are genuinely zero are left out on purpose -- a matrix with
no zeros in it is a matrix nobody thought about.

Sign convention, because it trips everyone up once: a **positive** coefficient
means the sonic dim moves *with* the sky dim. ``pressure_trend_6h -> valence``
is positive, and ``pressure_trend_6h`` is *negative* when the barometer is
falling, so falling pressure *lowers* valence. Read it twice.

Pure Python. No numpy. Nine by seven does not need a BLAS.
"""

from __future__ import annotations

import hashlib
import math
from typing import Sequence

from ..contracts import SKY_DIMS, SONIC_DIMS, SkyVector, SonicVector, clamp

__all__ = [
    "MATRIX_VERSION",
    "BASE_SONIC",
    "SKY_TO_SONIC",
    "TRANSFER_MATRIX",
    "COEFFICIENT_NOTES",
    "coefficient",
    "apply_transfer",
    "explain_transfer",
    "matrix_rows",
]


# ---------------------------------------------------------------------------
# The intercept: what a blank sky sounds like
# ---------------------------------------------------------------------------

BASE_SONIC: SonicVector = SonicVector(
    # Slightly above the midpoint. A featureless sky is not a sad one, and the
    # single most common failure mode of mood engines is defaulting to gloom.
    valence=0.52,
    # Dead centre. Energy is something the sky earns, in either direction.
    energy=0.50,
    # 0.47 of [60, 180] is 116.4 BPM. That is the tempo of walking somewhere
    # with mild purpose, which is the correct null hypothesis for a human.
    tempo=0.47,
    # A shade under half. Left of centre because the listening baseline in
    # 2026 is electric, and because it leaves headroom for rain and frost to
    # pull it up, which they do more often than heat pulls it down.
    acousticness=0.45,
    # Just under centre: a default of "a band playing" rather than "a wall".
    density=0.48,
    # Low. Grit is texture the weather adds -- hiss, dust, saturation. Clean is
    # the resting state, so this dim has a long runway upward and a short one
    # down, which matches how the coefficients below actually use it.
    grit=0.38,
    # Moderate room. Enough that a dry mix reads as a choice.
    spatiality=0.45,
)


# ---------------------------------------------------------------------------
# The table. This is the argument. Edit it with a reason, not a hunch.
# ---------------------------------------------------------------------------

SKY_TO_SONIC: dict[str, dict[str, float]] = {
    # =====================================================================
    # 1. pressure_trend_6h  -- signed. -1 = crashing (~-12 hPa/6h), +1 = building.
    # ---------------------------------------------------------------------
    # The hero row, and the reason this project exists. Pressure *trend* is the
    # single best weather predictor of human affect we have, and it is the one
    # every consumer app ignores because it is not on the little icon.
    # =====================================================================
    "pressure_trend_6h": {
        # Falling pressure is the body's oldest weather signal. It precedes the
        # front by six to twelve hours, it is measurable in joint pain, sinus
        # pressure and migraine onset long before the first drop lands, and it
        # presents subjectively as *unease* rather than sadness. Nobody knows
        # why they feel off on the morning before a front. This coefficient is
        # the largest single valence term in the table and it has earned it.
        "valence": +0.22,
        # A building barometer is subsidence: settled, dry, moving air out of
        # the way. It lets you get on with things. Kept modest, because the
        # *drama* of a low is supplied by gusts and rain further down -- the
        # trend on its own is a mood, not an event.
        "energy": +0.10,
        # The pre-frontal slump is real and it is slow. Falling pressure drags
        # tempo down; a rising barometer is the sky clearing its throat and you
        # walk faster without deciding to.
        "tempo": +0.12,
        # acousticness: deliberately zero. The barometer has no opinion about
        # instrumentation, and pretending otherwise to fill the cell would be
        # the exact kind of fake precision this file exists to avoid.
        #
        # Falling pressure *empties the room*. The hours before a front are the
        # pre-frontal hush: air stills, birds stop, the world holds. So density
        # drops as pressure drops. This is the cell that separates pressure
        # (which owns weight and space) from gust_variance (which owns texture
        # and event count) -- without it the two rows would say the same thing.
        "density": +0.09,
        # Small negative, i.e. falling pressure adds grit. Pre-frontal air
        # carries haze and static; the records that fit it are tape-warm and
        # slightly saturated rather than glassy and clean.
        "grit": -0.07,
        # Negative, i.e. **falling pressure raises reverb**, and this is a
        # physical claim, not a poetic one. The temperature inversions that ride
        # ahead of a warm front refract sound back toward the ground, which is
        # why you can hear the motorway before it rains. Low-pressure days
        # genuinely carry sound further, and the music that fits them is the
        # music with room in it.
        "spatiality": -0.16,
    },
    # =====================================================================
    # 2. pressure_norm_deviation -- signed. Current pressure vs this location's
    #    own 7-day mean. -1 = a deep low *for here*.
    # ---------------------------------------------------------------------
    # The level, not the derivative. Every coefficient here is roughly half its
    # row-1 counterpart, and that asymmetry IS the thesis: you habituate to a
    # level within a day and you never habituate to a change.
    # =====================================================================
    "pressure_norm_deviation": {
        # A settled high is quietly good news; a standing low is a lid on the
        # week. Under half the trend's authority, on purpose.
        "valence": +0.09,
        # Mild. High pressure means dry air and a horizon.
        "energy": +0.05,
        "tempo": +0.04,
        # A persistent low is murk, and murk has a noise floor.
        "grit": -0.05,
        # Same acoustics as row 1, halved: standing low pressure, standing
        # reverb. A week under a low sounds bigger than a week under a high.
        "spatiality": -0.08,
    },
    # =====================================================================
    # 3. temp_norm_deviation -- signed. Apparent temp vs the local 7-day mean.
    # ---------------------------------------------------------------------
    # Note carefully: *deviation*, not temperature. 8 degC in Malaga in August
    # is an event; 8 degC in Brussels in March is Tuesday. Absolute temperature
    # is a fact about latitude. Deviation is a fact about how today feels.
    # =====================================================================
    "temp_norm_deviation": {
        # Warmth relative to expectation is the most reliable mood lift in the
        # whole table. Unseasonable mildness in February is a gift and everyone
        # treats it as one; unseasonable cold in June is a small, real grief.
        "valence": +0.16,
        # Heat mobilises, up to a point. The point where it stops mobilising and
        # starts flattening you is above what this linear term can express --
        # that ceiling is the heatwave_cruise theme's job, not the matrix's.
        "energy": +0.11,
        # Cold shortens the stride, musically as well as literally. Raw days
        # want slower music and nobody has ever had to be told this.
        "tempo": +0.10,
        # Negative: **cold reads acoustic**. Wood, breath, close-mic'd rooms,
        # the sound of somebody indoors and near a lamp. Heat reads electric --
        # synths, drum machines, the sound of a night that will not cool down.
        "acousticness": -0.09,
        # Warm air is busy air: insects, traffic, people who came outside.
        "density": +0.05,
        # grit: zero. Temperature has no honest claim on texture.
        #
        # Negative, i.e. cold raises reverb. Two reasons that happen to agree:
        # cold air is denser and propagates sound more cleanly, and the entire
        # cold-climate canon leans on reverb to fill a room it cannot heat.
        "spatiality": -0.06,
    },
    # =====================================================================
    # 4. sun_elevation -- signed. -1 = solar midnight, 0 = horizon, +1 = zenith.
    # ---------------------------------------------------------------------
    # The obvious row. It is allowed exactly one obvious coefficient.
    # =====================================================================
    "sun_elevation": {
        # Light lifts mood -- but less than you would guess, and less than any
        # of the pressure terms. Night has a deep catalogue of high-valence
        # music and midday has plenty of grim. Kept honest at +0.14.
        "valence": +0.14,
        # THE obvious one, and the only obvious one this table permits itself.
        # Circadian arousal tracks solar elevation almost linearly; cortisol
        # does not care what genre you like. Biggest energy term here.
        "energy": +0.20,
        # The diurnal tempo curve is real and radio programmers have exploited
        # it since the 1930s: BPM climbs through late morning, peaks again at
        # drive time, and falls off a cliff after dark.
        "tempo": +0.15,
        # acousticness: zero. Daylight has no instrumentation preference; the
        # *hour* does (see golden_hour_proximity) but the elevation does not.
        #
        # A high sun is a busy world with a lot going on in it.
        "density": +0.09,
        # Negative: **darkness is the strongest reverb cue in the table.** You
        # cannot see the walls, so your ear stops assuming there are any and the
        # music expands to fill a space you can no longer measure. Noon is dry
        # and close; 3am is a cathedral.
        "spatiality": -0.12,
    },
    # =====================================================================
    # 5. golden_hour_proximity -- unsigned. 1.0 at golden hour, decaying over
    #    +/-90 min around sunrise and sunset.
    # ---------------------------------------------------------------------
    # The most important non-linear feature the extractor computes, and the one
    # that turns "40 minutes to sunset" into a musical fact.
    # =====================================================================
    "golden_hour_proximity": {
        # Positive but **deliberately modest**, and this restraint is load-
        # bearing. Golden hour is warm; it is not happy. It has loss built into
        # it, because the light is only that good on its way out. Push this past
        # about +0.12 and the app starts serving sunshine pop at dusk, which is
        # the single most common failure of the entire category.
        "valence": +0.10,
        # The day is standing down. Nothing urgent happens in good light.
        "energy": -0.08,
        # Golden hour is unhurried, and separating *warm and slow* from *happy
        # and fast* is most of what this whole table is for. Note the sign
        # disagreement with valence directly above: that disagreement is the
        # entire point of having seven dims instead of one mood slider.
        "tempo": -0.13,
        # A domestic hour. Guitars, Rhodes, brushes, the sound of a room that
        # somebody actually stood in.
        "acousticness": +0.09,
        # Fewer events, more space between them.
        "density": -0.07,
        # Long light, long shadows, long reverb tails. Golden hour is the most
        # photographed hour of the day for the same reason it is the most
        # reverberant one: everything gets a tail.
        "spatiality": +0.12,
    },
    # =====================================================================
    # 6. gust_variance -- unsigned. The *spread* of gusts over 6h, not the mean.
    # ---------------------------------------------------------------------
    # Steady 40 km/h is boring. 14 gusting 33 is nervous. We measure the second
    # thing, because the second thing is the one you can hear.
    # =====================================================================
    "gust_variance": {
        # Mildly unsettling, and only mildly: gusty weather is exhilarating
        # roughly as often as it is grim, and the table should not pretend to
        # know which one today is.
        "valence": -0.07,
        # Unsettled air is kinetic. Straightforward.
        "energy": +0.13,
        # Some, but restrained. Gusts are *irregular*, and irregularity reads as
        # syncopation rather than speed. The density cell below carries most of
        # what this row wants to say; tempo would be the lazy place to put it.
        "tempo": +0.06,
        # THE headline claim of this row. Variance is events, and events are
        # density. Nervous air wants a hi-hat that will not sit still and a
        # kosmische pulse with something loose riding on top. Not volume:
        # information. Largest density coefficient in the table.
        "density": +0.17,
        # The same argument in the texture domain. Unsettled air wants a noise
        # floor and a mic that is slightly too hot. Again: texture, not volume.
        "grit": +0.15,
        # Moving air smears a reverb tail rather than lengthening it. Small.
        "spatiality": +0.05,
    },
    # =====================================================================
    # 7. cloud_depth -- unsigned. Cover weighted by humidity: haze vs a lid.
    # ---------------------------------------------------------------------
    # =====================================================================
    "cloud_depth": {
        # This is the closest the table comes to the naive `overcast -> sad`
        # mapping, and it earns the right because the coefficient sits on
        # *depth* rather than *cover*: high thin cirrus at 90% cover barely
        # moves it, while a saturated 600 m stratus lid moves it a lot. And
        # unlike rain, a lid lasts all day, which is what actually grinds.
        "valence": -0.15,
        # Flat light, flat drive.
        "energy": -0.10,
        "tempo": -0.07,
        # Overcast is an indoor day, and indoor days sound like wood.
        "acousticness": +0.06,
        # A lid flattens detail. Grey is a low-information sky and the music
        # that matches it holds notes rather than counting them.
        "density": -0.06,
        # The grain of an overcast day: not distortion, but the visual noise of
        # low contrast, rendered as tape hiss.
        "grit": +0.08,
        # A cloud deck is a physical ceiling that reflects sound back down. This
        # is not a metaphor -- it is why cities are measurably louder under low
        # cloud, and why an approaching aircraft sounds close on a grey day.
        "spatiality": +0.14,
    },
    # =====================================================================
    # 8. precip_intensity -- unsigned, log-compressed. 0.5 ~ steady, 1.0 ~ downpour.
    # ---------------------------------------------------------------------
    # The dim that every naive app puts its entire weight on. Here it is one of
    # nine, and it barely touches valence. That is not an oversight.
    # =====================================================================
    "precip_intensity": {
        # Almost provocatively small. **Rain is not sadness.** Ask anyone who
        # has ever been glad it was raining. The unease of a wet day arrived on
        # the barometer six hours earlier (see row 1); by the time water is
        # actually falling, the tension has *broken*. Rain is enclosing, not
        # depressing, and the difference is the whole product.
        "valence": -0.06,
        # Mild damping. The world postpones things.
        "energy": -0.05,
        # Rain slows traffic, footsteps and plans.
        "tempo": -0.08,
        # Rain is the most acoustic weather there is -- it is already a
        # percussion track. Music that fits it leaves room for it and matches
        # its timbre: brushed, wooden, unquantised. Largest acousticness term
        # in the table.
        "acousticness": +0.12,
        # Steady rain is itself dense information, and music under it either
        # matches that density or gets washed out. Deliberately fights
        # cloud_depth's negative: a downpour under a lid nets out near neutral,
        # which is exactly right, because that is a *heavy* sky, not a busy one.
        "density": +0.07,
        # Wet asphalt, tyre spray, the noise floor of a downpour.
        "grit": +0.10,
        # Rain shrinks the world to a room and then fills that room with early
        # reflections. There is a reason dub sounds like rain: delay, space,
        # water. Second-largest spatiality term.
        "spatiality": +0.13,
    },
    # =====================================================================
    # 9. daylight_delta -- signed. Day length vs yesterday. Negative = closing in.
    # ---------------------------------------------------------------------
    # The slowest derivative in the table and the one nobody else models. It is
    # the entire difference between a cold clear morning in March and an
    # identical cold clear morning in October. Same photograph. Different record.
    # =====================================================================
    "daylight_delta": {
        # A seasonal-affect term, and the literature is clear that the
        # *direction* of change predicts mood better than the level: late
        # January is objectively darker than early November and feels
        # categorically better, because one is opening and one is closing.
        "valence": +0.11,
        # The opening year is outward-facing.
        "energy": +0.06,
        "tempo": +0.05,
        # Small negative: the closing year turns inward and acoustic, the
        # opening year turns outward and electric. Genuinely arguable, which is
        # precisely why it is small.
        "acousticness": -0.05,
        # density, grit: zero. Neither has any business tracking the calendar.
        #
        # Autumn is a reverberant season. This one is cultural rather than
        # physical and the coefficient is sized to admit that.
        "spatiality": -0.06,
    },
}


# ---------------------------------------------------------------------------
# Short, machine-readable versions of the arguments above.
#
# The inline comments are for whoever maintains the model. These one-clause
# notes are for the *user*: rationale.py cites them on the hero card so the
# explanation says not just "pressure moved valence" but why that is a claim
# anyone should believe. Curated, not exhaustive -- only the cells strong
# enough to be worth a sentence of a stranger's attention.
# ---------------------------------------------------------------------------

COEFFICIENT_NOTES: dict[tuple[str, str], str] = {
    ("pressure_trend_6h", "valence"): "a falling barometer reads as unease hours before the first drop",
    ("pressure_trend_6h", "tempo"): "the pre-frontal slump is slow before it is anything else",
    ("pressure_trend_6h", "spatiality"): "low pressure genuinely carries sound further, so the music gets room",
    ("pressure_trend_6h", "density"): "the hush ahead of a front empties the arrangement out",
    ("pressure_norm_deviation", "valence"): "a standing low is a lid on the whole week",
    ("pressure_norm_deviation", "spatiality"): "settled low pressure, settled reverb",
    ("temp_norm_deviation", "valence"): "warmth measured against what you expected, not against a thermometer",
    ("temp_norm_deviation", "acousticness"): "cold sounds like wood and breath; heat sounds like voltage",
    ("temp_norm_deviation", "tempo"): "raw days shorten the stride",
    ("sun_elevation", "energy"): "circadian arousal tracks the sun almost linearly",
    ("sun_elevation", "tempo"): "the diurnal BPM curve radio has exploited since the 1930s",
    ("sun_elevation", "spatiality"): "in the dark you stop assuming there are walls",
    ("golden_hour_proximity", "tempo"): "golden hour is unhurried, which is not the same as happy",
    ("golden_hour_proximity", "spatiality"): "long light, long shadows, long tails",
    ("golden_hour_proximity", "acousticness"): "the domestic hour: guitars, Rhodes, brushes",
    ("golden_hour_proximity", "valence"): "warm, but the light is only this good on its way out",
    ("gust_variance", "density"): "unsettled air wants event density, not volume",
    ("gust_variance", "grit"): "nervous air wants a noise floor",
    ("gust_variance", "energy"): "gust spread is kinetic in a way steady wind never is",
    ("cloud_depth", "valence"): "a saturated lid lasts all day, which is what actually grinds",
    ("cloud_depth", "spatiality"): "a cloud deck is a ceiling and it reflects sound back down",
    ("cloud_depth", "grit"): "the grain of low contrast, rendered as tape hiss",
    ("precip_intensity", "acousticness"): "rain is already a percussion track; leave it room",
    ("precip_intensity", "spatiality"): "there is a reason dub sounds like rain",
    ("precip_intensity", "valence"): "rain is enclosing rather than sad; the tension broke hours ago",
    ("precip_intensity", "grit"): "wet asphalt has a noise floor",
    ("daylight_delta", "valence"): "the year opening or closing beats the year being dark",
    ("daylight_delta", "spatiality"): "autumn is a reverberant season",
}


# ---------------------------------------------------------------------------
# Densification and shape validation
# ---------------------------------------------------------------------------


def _densify(table: dict[str, dict[str, float]]) -> tuple[tuple[float, ...], ...]:
    """Flatten the legible table into a ``SKY_DIMS x SONIC_DIMS`` grid.

    Runs once at import. Unlisted cells are exactly zero, which is how the
    source table gets to stay readable: silence means "no claim", not "forgot".
    """
    unknown_sky = set(table) - set(SKY_DIMS)
    if unknown_sky:
        raise ValueError(f"SKY_TO_SONIC has unknown sky dims: {sorted(unknown_sky)}")
    missing_sky = set(SKY_DIMS) - set(table)
    if missing_sky:
        raise ValueError(f"SKY_TO_SONIC is missing sky dims: {sorted(missing_sky)}")

    rows: list[tuple[float, ...]] = []
    for sky_dim in SKY_DIMS:
        row = table[sky_dim]
        unknown_sonic = set(row) - set(SONIC_DIMS)
        if unknown_sonic:
            raise ValueError(
                f"SKY_TO_SONIC[{sky_dim!r}] has unknown sonic dims: {sorted(unknown_sonic)}"
            )
        rows.append(tuple(float(row.get(sonic_dim, 0.0)) for sonic_dim in SONIC_DIMS))
    return tuple(rows)


TRANSFER_MATRIX: tuple[tuple[float, ...], ...] = _densify(SKY_TO_SONIC)

# Shape is load-bearing: the whole pipeline indexes by position, and a silent
# off-by-one here would produce plausible-sounding nonsense forever.
assert len(TRANSFER_MATRIX) == len(SKY_DIMS), "transfer matrix row count != len(SKY_DIMS)"
assert all(len(row) == len(SONIC_DIMS) for row in TRANSFER_MATRIX), "ragged transfer matrix"


def _fingerprint() -> str:
    """Eight hex characters that change whenever any coefficient changes.

    The Almanac trains per-user ``nudge`` matrices against a specific set of
    coefficients. Retune the table and those nudges are corrections to a model
    that no longer exists, so the version string has to move on its own -- a
    human remembering to bump a constant is not a mechanism.
    """
    digest = hashlib.blake2b(digest_size=4)
    for sky_dim, row in zip(SKY_DIMS, TRANSFER_MATRIX):
        digest.update(sky_dim.encode())
        for value in row:
            digest.update(f"{value:+.4f}".encode())
    for value in BASE_SONIC.as_array():
        digest.update(f"{value:+.4f}".encode())
    return digest.hexdigest()


MATRIX_VERSION: str = f"1.0.0+{_fingerprint()}"


# ---------------------------------------------------------------------------
# The squash
# ---------------------------------------------------------------------------

#: Below this the response is exactly linear. Above it, we bend.
_SHOULDER: float = 0.85
_FLOOR: float = 1.0 - _SHOULDER  # 0.15, symmetric


def _squash(value: float) -> float:
    """Fold a raw matrix output into ``(0, 1)`` without flattening the extremes.

    A hard clamp would be simpler, and wrong in a specific way: two genuinely
    different skies -- a bad day and a *catastrophic* day -- would both come out
    at exactly 0.0 valence and become indistinguishable to every downstream
    ranker. So we stay perfectly linear across ``[0.15, 0.85]``, which is where
    virtually every real reading lands and where interpretability matters most,
    then bend the overshoot through a tanh knee.

    The knee is C-1 continuous at both shoulders (``tanh'(0) == 1`` and the
    scale factors cancel exactly), so there is no kink for a downstream
    gradient or a curious reader to trip over, and ordering is preserved all the
    way out to infinity: a worse sky always scores lower, just by less.
    """
    if value > _SHOULDER:
        return _SHOULDER + _FLOOR * math.tanh((value - _SHOULDER) / _FLOOR)
    if value < _FLOOR:
        return _FLOOR - _FLOOR * math.tanh((_FLOOR - value) / _FLOOR)
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def coefficient(sky_dim: str, sonic_dim: str) -> float:
    """Look one coefficient up by name. Unset cells are ``0.0``, not an error."""
    if sky_dim not in SKY_DIMS:
        raise KeyError(f"unknown sky dim: {sky_dim!r}")
    if sonic_dim not in SONIC_DIMS:
        raise KeyError(f"unknown sonic dim: {sonic_dim!r}")
    return TRANSFER_MATRIX[SKY_DIMS.index(sky_dim)][SONIC_DIMS.index(sonic_dim)]


def matrix_rows() -> list[dict[str, object]]:
    """The matrix as JSON-friendly rows, for the A2UI 'show your working' panel."""
    return [
        {
            "sky_dim": sky_dim,
            "coefficients": {
                sonic_dim: TRANSFER_MATRIX[i][j] for j, sonic_dim in enumerate(SONIC_DIMS)
            },
            "notes": {
                sonic_dim: COEFFICIENT_NOTES[(sky_dim, sonic_dim)]
                for sonic_dim in SONIC_DIMS
                if (sky_dim, sonic_dim) in COEFFICIENT_NOTES
            },
        }
        for i, sky_dim in enumerate(SKY_DIMS)
    ]


def _effective_matrix(
    nudge: Sequence[Sequence[float]] | None,
) -> tuple[tuple[float, ...], ...]:
    """``TRANSFER_MATRIX + nudge``, validated.

    The nudge is additive by construction. A user who has skipped every slow
    track we ever served them can flatten the tempo coefficients toward zero,
    or even past it, but they are always arguing with the model rather than
    replacing it -- which keeps the explanation honest and keeps a cold-start
    user and a power user on the same axes.
    """
    if nudge is None:
        return TRANSFER_MATRIX
    rows = list(nudge)
    if len(rows) != len(SKY_DIMS):
        raise ValueError(f"nudge needs {len(SKY_DIMS)} rows, got {len(rows)}")
    out: list[tuple[float, ...]] = []
    for base_row, delta_row in zip(TRANSFER_MATRIX, rows):
        delta = list(delta_row)
        if len(delta) != len(SONIC_DIMS):
            raise ValueError(f"nudge rows need {len(SONIC_DIMS)} values, got {len(delta)}")
        out.append(tuple(b + float(d) for b, d in zip(base_row, delta)))
    return tuple(out)


def apply_transfer(
    sky: SkyVector,
    *,
    nudge: Sequence[Sequence[float]] | None = None,
) -> SonicVector:
    """Turn a sky into a target feeling.

    ``sonic[j] = squash( BASE_SONIC[j] + sum_i sky[i] * (M[i][j] + nudge[i][j]) )``

    Nine multiply-accumulates per output dim, seven output dims. Sixty-three
    multiplications is not a reason to take a numpy dependency, and staying in
    pure Python means this function is readable by the same person who has to
    defend the coefficients.
    """
    matrix = _effective_matrix(nudge)
    sky_values = sky.as_array()
    base = BASE_SONIC.as_array()

    out: list[float] = []
    for j in range(len(SONIC_DIMS)):
        total = base[j]
        for i, sky_value in enumerate(sky_values):
            total += sky_value * matrix[i][j]
        out.append(clamp(_squash(total)))
    return SonicVector.from_array(out)


def explain_transfer(
    sky: SkyVector,
    sonic: SonicVector,
    *,
    top_n: int = 4,
    nudge: Sequence[Sequence[float]] | None = None,
) -> list[tuple[str, str, float]]:
    """The largest ``(sky_dim, sonic_dim, contribution)`` terms behind ``sonic``.

    This is the mechanism that makes BAROGROOVE explainable rather than
    mystical. Because the model is linear, each term is an exact additive
    contribution -- not a saliency heuristic, not a plausible story told after
    the fact. "Pressure trend moved valence by -0.19" is arithmetic.

    One refinement worth the extra few lines: if a dim hit the squash and came
    back compressed, the raw terms would over-claim. So every contribution is
    scaled by the ratio of *realised* deflection to *raw* deflection for its
    output dim, which means the reported terms for a dim sum exactly to the
    deflection you can actually see in ``sonic``. If the card says the numbers
    add up, they add up.

    Sorted by absolute contribution, descending. Ties break on dimension order,
    so the output is stable across runs, machines and Python versions.
    """
    matrix = _effective_matrix(nudge)
    sky_values = sky.as_array()
    base = BASE_SONIC.as_array()
    realised = sonic.as_array()

    terms: list[tuple[str, str, float]] = []
    for j, sonic_dim in enumerate(SONIC_DIMS):
        raw_deflection = sum(sky_values[i] * matrix[i][j] for i in range(len(SKY_DIMS)))
        realised_deflection = realised[j] - base[j]
        if abs(raw_deflection) > 1e-9:
            scale = clamp(realised_deflection / raw_deflection, 0.0, 1.0)
        else:
            scale = 1.0
        for i, sky_dim in enumerate(SKY_DIMS):
            contribution = sky_values[i] * matrix[i][j] * scale
            if abs(contribution) < 1e-6:
                continue
            terms.append((sky_dim, sonic_dim, round(contribution, 4)))

    terms.sort(
        key=lambda t: (-abs(t[2]), SKY_DIMS.index(t[0]), SONIC_DIMS.index(t[1])),
    )
    return terms[: max(0, top_n)]
