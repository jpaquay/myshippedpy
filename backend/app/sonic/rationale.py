"""The hero card: turning nine floats back into a sentence somebody wants to read.

Explainability is the product, not the footnote. A weather playlist that cannot
say *why* is indistinguishable from shuffle with a nice background image, and
the user will work that out in about four days.

So this module has one job, and a high bar for it. The target register:

    "Pressure fell 9.2 hPa since noon and the sun is 38 minutes off the
    horizon. Tempo pulled down to 94, valence to 0.31, reverb up. Your
    scrobbles say you reach for Talk Talk in exactly this weather."

Three rules, all of them load-bearing:

**Real numbers, always.** Every sentence that can carry a digit carries one.
"Pressure is falling" is a horoscope. "Pressure has given up 9.2 hPa in six
hours" is a fact the user can check against their own window, and being
checkable is the entire source of the card's authority. The ``SkyVector`` is
normalised, so this module owns the inverse scales that turn -0.77 back into
-9.2 hPa. Those constants are documented and match the extractor's own ranges.

**Deterministic, but not identical.** The same sky must always explain itself
the same way -- tests depend on it and users notice churn. But two different
days must not read from the same stencil, or by Thursday the card is wallpaper.
So every phrasing slot picks from a handful of alternatives, indexed by a hash
of the sky vector itself. No RNG anywhere. Same weather, same words; different
weather, different words. Note the hash uses blake2b rather than ``hash()``,
because Python's string hashing is salted per process and would make the output
vary between runs of the same test.

**Never hide a fallback.** If Last.fm was down we say so, in words, on the card,
and we drop the confidence to match. A product that quietly degrades is a
product that is lying, and this one has a ledger specifically so it does not
have to.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable, Sequence

from ..contracts import (
    GenreCorridor,
    Rationale,
    SkyVector,
    SonicVector,
    TasteVector,
    Theme,
    clamp,
)
from .matrix import BASE_SONIC, COEFFICIENT_NOTES, explain_transfer

__all__ = ["build_rationale", "short_headline", "sky_sentences"]


# ---------------------------------------------------------------------------
# Inverse scales: normalised dim -> the physical quantity a human recognises.
#
# These mirror the ranges the extractor used on the way in (and the ranges
# documented on the SkyVector fields). If the extractor ever retunes a span,
# it has to be changed here too or the card starts confidently misquoting the
# weather -- which is worse than saying nothing.
# ---------------------------------------------------------------------------

PRESSURE_TREND_SPAN_HPA: float = 12.0  # |1.0| ~ 12 hPa over six hours
PRESSURE_DEV_SPAN_HPA: float = 18.0  # |1.0| ~ 18 hPa off the local 7-day mean
TEMP_NORM_SPAN_C: float = 8.0  # |1.0| ~ 8 degC off the local 7-day mean
GOLDEN_HOUR_WINDOW_MIN: float = 90.0  # proximity decays over +/-90 min
GUST_SPAN_KMH: float = 35.0  # 1.0 ~ a 35 km/h spread between lull and gust
SUN_ELEVATION_SPAN_DEG: float = 60.0  # |1.0| ~ 60 degrees from the horizon
DAYLIGHT_DELTA_SPAN_S: float = 240.0  # |1.0| ~ 4 minutes of day length vs yesterday


def _precip_mm_per_hour(intensity: float) -> float:
    """Undo the extractor's log compression. 0.5 -> ~3.8 mm/h, 1.0 -> ~21 mm/h."""
    return round((math.exp(3.0 * clamp(intensity)) - 1.0) * 1.1, 1)


# ---------------------------------------------------------------------------
# Deterministic phrase selection
# ---------------------------------------------------------------------------


def _seed(sky: SkyVector, *extra: str) -> int:
    """A stable integer for this sky.

    Rounded to two decimals before hashing, so a sky that differs only in
    floating-point noise -- the same reading re-derived on a different machine,
    or after a harmless refactor of the extractor -- still tells its story with
    the same words. Two decimals is roughly 0.24 hPa of pressure trend, which is
    below the resolution at which anybody could tell the difference anyway.
    """
    digest = hashlib.blake2b(digest_size=8)
    for value in sky.as_array():
        digest.update(f"{value:+.2f}".encode())
    for item in extra:
        digest.update(item.encode())
    return int.from_bytes(digest.digest(), "big")


def _pick(options: Sequence[str], seed: int, salt: str) -> str:
    """Choose one phrasing for one slot, stably.

    The salt keeps slots independent: without it the headline and the body
    would select in lockstep and every card would use the same "voice" for both,
    which reads like a mail merge.
    """
    if not options:
        return ""
    mix = int.from_bytes(hashlib.blake2b(salt.encode(), digest_size=8).digest(), "big")
    return options[(seed ^ mix) % len(options)]


# ---------------------------------------------------------------------------
# Sky -> sentences
# ---------------------------------------------------------------------------


def _sky_facts(sky: SkyVector, seed: int) -> list[tuple[float, str]]:
    """Every sky dim worth mentioning, as ``(salience, sentence)``.

    Salience is the absolute normalised magnitude, so the sort order matches
    the matrix's own sense of what mattered -- the card leads with the fact that
    actually moved the music, not with whichever fact is easiest to phrase.
    """
    facts: list[tuple[float, str]] = []

    # -- pressure trend: the lead fact on most interesting days ---------------
    trend = sky.pressure_trend_6h
    if abs(trend) >= 0.10:
        hpa = abs(trend) * PRESSURE_TREND_SPAN_HPA
        if trend < 0:
            options = (
                f"pressure has given up {hpa:.1f} hPa in six hours",
                f"the barometer is down {hpa:.1f} hPa since this morning",
                f"{hpa:.1f} hPa has come off the glass in six hours",
            )
        else:
            options = (
                f"pressure is up {hpa:.1f} hPa over six hours",
                f"the barometer has put on {hpa:.1f} hPa since this morning",
                f"{hpa:.1f} hPa of build in the last six hours",
            )
        facts.append((abs(trend) * 1.15, _pick(options, seed, "trend")))

    # -- golden hour: the fact that makes the app feel psychic ----------------
    proximity = sky.golden_hour_proximity
    if proximity >= 0.20:
        minutes = round((1.0 - proximity) * GOLDEN_HOUR_WINDOW_MIN)
        if minutes <= 2:
            options = (
                "the sun is sitting on the horizon",
                "the sun is right on the line",
                "we are at the horizon, more or less exactly",
            )
        else:
            options = (
                f"the sun is {minutes} minutes off the horizon",
                f"there are {minutes} minutes of this light left",
                f"{minutes} minutes to the horizon and closing",
            )
        facts.append((proximity, _pick(options, seed, "golden")))

    # -- temperature, measured against here rather than against a thermometer -
    temp = sky.temp_norm_deviation
    if abs(temp) >= 0.12:
        degrees = abs(temp) * TEMP_NORM_SPAN_C
        if temp < 0:
            options = (
                f"it is running {degrees:.1f} degC below what this week has averaged here",
                f"{degrees:.1f} degC colder than this place has been all week",
                f"the air is {degrees:.1f} degC under the local norm",
            )
        else:
            options = (
                f"it is {degrees:.1f} degC above the local norm for this week",
                f"{degrees:.1f} degC warmer than this place has been all week",
                f"the air is {degrees:.1f} degC over what this week has averaged here",
            )
        facts.append((abs(temp), _pick(options, seed, "temp")))

    # -- gusts: the spread, not the speed -------------------------------------
    gusts = sky.gust_variance
    if gusts >= 0.15:
        spread = gusts * GUST_SPAN_KMH
        options = (
            f"gusts are swinging across {spread:.0f} km/h",
            f"there is a {spread:.0f} km/h spread between the lulls and the gusts",
            f"the wind will not hold a number -- {spread:.0f} km/h between lull and gust",
        )
        facts.append((gusts * 0.95, _pick(options, seed, "gust")))

    # -- cloud ----------------------------------------------------------------
    cloud = sky.cloud_depth
    if cloud >= 0.20:
        percent = cloud * 100.0
        if cloud >= 0.65:
            options = (
                f"the cloud is a lid rather than a haze, {percent:.0f}% deep",
                f"{percent:.0f}% cloud depth, and it is a ceiling",
                f"a {percent:.0f}% deck with the humidity to back it up",
            )
        else:
            options = (
                f"cloud depth is sitting at {percent:.0f}%",
                f"{percent:.0f}% cloud, thin enough to see through",
                f"there is {percent:.0f}% of cloud up there and no weight to it",
            )
        facts.append((cloud * 0.9, _pick(options, seed, "cloud")))

    # -- precipitation --------------------------------------------------------
    precip = sky.precip_intensity
    if precip >= 0.05:
        mm = _precip_mm_per_hour(precip)
        options = (
            f"rain at {mm:.1f} mm an hour",
            f"{mm:.1f} mm/h is falling",
            f"there is {mm:.1f} mm an hour coming down",
        )
        facts.append((precip * 0.85, _pick(options, seed, "precip")))

    # -- sun elevation --------------------------------------------------------
    elevation = sky.sun_elevation
    if abs(elevation) >= 0.15:
        degrees = abs(elevation) * SUN_ELEVATION_SPAN_DEG
        if elevation < 0:
            options = (
                f"the sun is {degrees:.0f} degrees below the horizon",
                f"we are {degrees:.0f} degrees into the dark",
                f"the sun cleared out {degrees:.0f} degrees ago",
            )
        else:
            options = (
                f"the sun is {degrees:.0f} degrees up",
                f"solar elevation {degrees:.0f} degrees",
                f"there are {degrees:.0f} degrees of sun above the horizon",
            )
        facts.append((abs(elevation) * 0.8, _pick(options, seed, "sun")))

    # -- pressure level, as distinct from pressure trend ----------------------
    deviation = sky.pressure_norm_deviation
    if abs(deviation) >= 0.25:
        hpa = abs(deviation) * PRESSURE_DEV_SPAN_HPA
        if deviation < 0:
            options = (
                f"and it is a deep low for here -- {hpa:.0f} hPa under the weekly mean",
                f"sitting {hpa:.0f} hPa below the local mean",
            )
        else:
            options = (
                f"and there is a solid high on it, {hpa:.0f} hPa over the weekly mean",
                f"sitting {hpa:.0f} hPa above the local mean",
            )
        facts.append((abs(deviation) * 0.6, _pick(options, seed, "pdev")))

    # -- the slowest derivative in the set ------------------------------------
    daylight = sky.daylight_delta
    if abs(daylight) >= 0.20:
        seconds = abs(daylight) * DAYLIGHT_DELTA_SPAN_S
        if daylight < 0:
            options = (
                f"the day is {seconds:.0f} seconds shorter than yesterday",
                f"we lost {seconds:.0f} seconds of daylight overnight",
                f"the year is closing at {seconds:.0f} seconds a day",
            )
        else:
            options = (
                f"the day is {seconds:.0f} seconds longer than yesterday",
                f"we picked up {seconds:.0f} seconds of daylight overnight",
                f"the year is opening at {seconds:.0f} seconds a day",
            )
        facts.append((abs(daylight) * 0.55, _pick(options, seed, "daylight")))

    facts.sort(key=lambda pair: -pair[0])
    return facts


def sky_sentences(sky: SkyVector, *, limit: int = 5) -> list[str]:
    """Bullet-ready observations about a sky, most salient first.

    The extractor's own ``notes`` come first and verbatim -- they are
    breadcrumbs written at the point where the raw Open-Meteo rows were still
    in scope, so they carry detail this module cannot reconstruct from nine
    normalised floats. Derived sentences fill in behind them, and a stale
    reading gets flagged at the top where nobody can miss it.
    """
    seed = _seed(sky)
    lines: list[str] = []
    if sky.stale:
        lines.append("Working from the last sky we managed to fetch, not a live one.")
    lines.extend(note.strip() for note in sky.notes if note and note.strip())
    for _, fact in _sky_facts(sky, seed):
        sentence = _sentence(fact) + "."
        if sentence not in lines:
            lines.append(sentence)
    return lines[:limit]


# ---------------------------------------------------------------------------
# Sonic -> sentences
# ---------------------------------------------------------------------------

_LANDING_LABEL: dict[str, str] = {
    "valence": "valence",
    "energy": "energy",
    "tempo": "tempo",
    "acousticness": "acousticness",
    "density": "density",
    "grit": "grit",
    "spatiality": "reverb",
}

#: Sky dim names as a person would say them out loud. ``pressure_trend_6h`` is
#: a variable name; "the six-hour pressure trend" is English, and the card is
#: written in English.
_SKY_LABEL: dict[str, str] = {
    "pressure_trend_6h": "the six-hour pressure trend",
    "pressure_norm_deviation": "pressure against the local norm",
    "temp_norm_deviation": "temperature against the local norm",
    "sun_elevation": "the sun's elevation",
    "golden_hour_proximity": "how close we are to golden hour",
    "gust_variance": "the spread in the gusts",
    "cloud_depth": "the depth of the cloud",
    "precip_intensity": "the rain",
    "daylight_delta": "the change in day length",
}


def _sentence(text: str) -> str:
    """Capitalise the first letter and nothing else.

    ``str.capitalize`` lowercases the remainder, which turns "9.2 hPa" into
    "9.2 hpa" and "4.1 degC" into "4.1 degc". Units are not negotiable.
    """
    return text[0].upper() + text[1:] if text else text


def _landing(sonic: SonicVector, seed: int) -> str:
    """Where the dials ended up, phrased as movement away from a blank sky.

    Reported against ``BASE_SONIC`` rather than against 0.5, because "pulled
    down" only means anything relative to where a featureless sky would have
    left it. Tempo is always quoted in BPM.
    """
    base = BASE_SONIC.as_dict()
    now = sonic.as_dict()
    moved = sorted(
        ((dim, now[dim] - base[dim]) for dim in now),
        key=lambda pair: -abs(pair[1]),
    )

    clauses: list[str] = []
    for dim, delta in moved[:3]:
        if abs(delta) < 0.02:
            continue
        direction = "up" if delta > 0 else "down"
        if dim == "tempo":
            clauses.append(f"tempo pulled {direction} to {sonic.tempo_bpm:.0f}")
        elif abs(delta) >= 0.14:
            clauses.append(f"{_LANDING_LABEL[dim]} {direction} hard to {now[dim]:.2f}")
        else:
            clauses.append(f"{_LANDING_LABEL[dim]} {direction} to {now[dim]:.2f}")

    if not clauses:
        return _pick(
            (
                "Nothing in the sky argued strongly enough to move the dials far from centre.",
                "The dials barely moved -- this is about as neutral as weather gets.",
            ),
            seed,
            "landing-null",
        )
    if len(clauses) == 1:
        body = clauses[0]
    else:
        body = ", ".join(clauses[:-1]) + ", " + clauses[-1]
    return body[0].upper() + body[1:] + "."


def _mechanism(sky: SkyVector, sonic: SonicVector, seed: int) -> str:
    """One sentence naming the strongest sky->sonic term, and why it is a claim.

    This is where :func:`~.matrix.explain_transfer` earns its keep: rather than
    asserting a vibe, the card cites the single largest term in an additive
    model and the one-clause argument behind that coefficient.
    """
    terms = explain_transfer(sky, sonic, top_n=1)
    if not terms:
        return ""
    sky_dim, sonic_dim, contribution = terms[0]
    note = COEFFICIENT_NOTES.get((sky_dim, sonic_dim))
    if not note:
        return ""
    label = _LANDING_LABEL.get(sonic_dim, sonic_dim)
    sky_label = _SKY_LABEL.get(sky_dim, sky_dim.replace("_", " "))
    direction = "up" if contribution > 0 else "down"
    # Framing matters here. The note explains why the dial is *wired* that way,
    # not what happened today. The same coefficient runs in both directions --
    # "low pressure carries sound further" is precisely why a building barometer
    # takes reverb away -- and a sentence that only parsed for falling pressure
    # would be wrong half the time.
    options = (
        f"Most of that is {sky_label} on its own, worth {abs(contribution):.2f} of "
        f"{label} {direction}. That dial is wired that way because {note}.",
        f"It comes down largely to one coefficient — {sky_label} into {label}, "
        f"{abs(contribution):.2f} {direction} today. It is there because {note}.",
        f"{abs(contribution):.2f} of that {label} is {sky_label} alone, on the "
        f"argument that {note}.",
    )
    return _pick(options, seed, "mechanism")


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------

#: A closing clause per theme voice. Small, cheap, and the thing that stops
#: eight themes from sounding like one narrator wearing eight hats.
_VOICE_TAILS: dict[str, tuple[str, ...]] = {
    "hushed": ("Keep it low.", "Nothing loud until it breaks.", "Play it quietly and wait."),
    "warm": ("Let it run.", "No need to hurry this one.", "Put it on and leave it alone."),
    "spare": ("That is the whole reading.", "Not much else to say about it.", "Leave the rest."),
    "clipped": ("Loud, then.", "Do not be delicate about it.", "Straight in."),
    "loose": ("Windows down.", "No plan required.", "Let it ride."),
    "cool": ("Lights off, curtains open.", "Best on headphones.", "Take the long way home."),
    "dry": ("That is what the numbers say.", "Make of it what you like.", "Draw your own conclusions."),
    "wry": ("Blame the wind.", "Not our fault.", "You did ask."),
}


def _voice_tail(theme: Theme, seed: int) -> str:
    return _pick(_VOICE_TAILS.get(theme.voice, _VOICE_TAILS["dry"]), seed, f"tail:{theme.voice}")


# ---------------------------------------------------------------------------
# Degradation, in plain language
# ---------------------------------------------------------------------------

#: Ledger entries arrive as ``"subsystem: detail"``. Users do not care about
#: subsystems; they care what they are missing and whether it is their fault.
_DEGRADED_PHRASING: dict[str, str] = {
    "lastfm": "Last.fm is unpaired, so this is running theme-only -- no listening history in the mix.",
    "last.fm": "Last.fm is unpaired, so this is running theme-only -- no listening history in the mix.",
    "weather": "The weather feed was unreachable. This is the last sky we managed to read.",
    "open-meteo": "The weather feed was unreachable. This is the last sky we managed to read.",
    "oracle": "The track oracle is degraded, so matches are tag-only and a bit blunter than usual.",
    "spotify": "Spotify is not connected, so you are getting an M3U instead of a saved playlist.",
    "almanac": "Your almanac history is unavailable, so no personal correction was applied.",
    "taste": "We could not build a taste profile this time, so the sky and the theme did all the work.",
}


def _plain_degraded(entries: Iterable[str] | None) -> list[str]:
    """Ledger lines -> sentences a user can act on. Never silently dropped."""
    out: list[str] = []
    for entry in entries or ():
        text = str(entry).strip()
        if not text:
            continue
        subsystem = text.split(":", 1)[0].strip().lower()
        phrased = _DEGRADED_PHRASING.get(subsystem)
        if phrased is None:
            detail = text.split(":", 1)[1].strip() if ":" in text else text
            phrased = f"{subsystem.capitalize()} degraded: {detail}"
        if phrased not in out:
            out.append(phrased)
    return out


# ---------------------------------------------------------------------------
# Taste
# ---------------------------------------------------------------------------


def _taste_note(taste: TasteVector | None, theme: Theme, seed: int) -> str:
    """Name a real artist, or say plainly that we cannot.

    Naming somebody from ``top_artists`` is the moment the card stops being a
    weather report and starts being about the person reading it, so it is worth
    the branch. If the profile is too thin to name anybody we say that instead
    of manufacturing a flattering guess.
    """
    if taste is None:
        return _pick(
            (
                "No listening history paired, so this is theme-only. Pair Last.fm and it starts arguing back.",
                "Running without your scrobbles. Pair Last.fm and this card gets a lot more specific.",
            ),
            seed,
            "taste-none",
        )

    if not taste.top_artists or taste.confidence < 0.15 or taste.scrobble_count < 25:
        return _pick(
            (
                f"Not enough history yet to say who you reach for in this weather -- "
                f"{taste.scrobble_count} scrobbles so far. Give it a fortnight.",
                f"Your profile is still thin ({taste.scrobble_count} scrobbles), so the theme "
                f"is doing the steering for now.",
            ),
            seed,
            "taste-thin",
        )

    artist = taste.top_artists[0]
    second = taste.top_artists[1] if len(taste.top_artists) > 1 else None
    top_tag = max(taste.top_tags, key=lambda t: taste.top_tags[t]) if taste.top_tags else None

    options: list[str] = [
        f"Your scrobbles say you reach for {artist} in exactly this weather.",
        f"{taste.scrobble_count:,} scrobbles deep, and {artist} is where this sky usually sends you.",
    ]
    if second:
        options.append(f"On this kind of day your history points at {artist}, then {second}.")
    if top_tag:
        options.append(
            f"You have played enough {top_tag} for it to count, and {artist} sits right in "
            f"the middle of it."
        )
    return _pick(tuple(options), seed, f"taste:{theme.id}")


# ---------------------------------------------------------------------------
# Tracks (optional garnish)
# ---------------------------------------------------------------------------


def _track_label(item: Any) -> str | None:
    """Best-effort display string for a Track or ScoredTrack.

    Deliberately tolerant. The rationale is built at the end of a forge and must
    never be the thing that breaks it, so an unexpected track shape costs us one
    optional sentence rather than the whole card.
    """
    track = getattr(item, "track", item)
    display = getattr(track, "display", None)
    if isinstance(display, str) and display:
        return display
    title = getattr(track, "title", None) or getattr(track, "name", None)
    artist = getattr(track, "artist", None)
    artist_name = getattr(artist, "name", artist)
    if title and artist_name:
        return f"{artist_name} - {title}"
    return title if isinstance(title, str) else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def short_headline(sky: SkyVector, theme: Theme) -> str:
    """A compact headline for the small card. Theme name plus the loudest fact."""
    seed = _seed(sky, theme.id)
    facts = _sky_facts(sky, seed)
    if not facts:
        return f"{theme.name} — {theme.tagline}"
    lead = facts[0][1]
    return f"{theme.name} — {lead}"


def build_rationale(
    *,
    sky: SkyVector,
    sonic: SonicVector,
    theme: Theme,
    corridor: GenreCorridor,
    taste: TasteVector | None = None,
    moves: Sequence[str] | None = None,
    tracks: Sequence[Any] | None = None,
    degraded: Iterable[str] | None = None,
) -> Rationale:
    """Assemble the hero card.

    ``moves`` should be the list :func:`~.target.build_target` returned; if it
    is absent we reconstruct a serviceable version from
    :func:`~.matrix.explain_transfer` so the card is never empty, only thinner.

    Confidence is a real estimate, not decoration. It starts at 0.74 -- honest
    about a linear model of a chaotic system -- rises with a solid taste profile,
    and falls for every degradation and for a stale sky. A card claiming 0.9
    while Last.fm is down would be the most damaging sentence in the app.
    """
    seed = _seed(sky, theme.id, corridor.id)

    # ---- sky ---------------------------------------------------------------
    reading = sky_sentences(sky, limit=5)
    facts = _sky_facts(sky, seed)

    if len(facts) >= 2:
        lead = _pick(
            (
                f"{_sentence(facts[0][1])} and {facts[1][1]}.",
                f"{_sentence(facts[0][1])}; {facts[1][1]}.",
                f"{_sentence(facts[0][1])}, and on top of that {facts[1][1]}.",
            ),
            seed,
            "lead",
        )
    elif facts:
        lead = f"{_sentence(facts[0][1])}."
    else:
        lead = _pick(
            (
                "The sky is doing almost nothing measurable today.",
                "Nine dimensions of weather and not one of them has an opinion.",
            ),
            seed,
            "lead-null",
        )

    # ---- what moved --------------------------------------------------------
    landing = _landing(sonic, seed)
    mechanism = _mechanism(sky, sonic, seed)

    # ---- corridor ----------------------------------------------------------
    if corridor.anchor is None or corridor.id == "any":
        corridor_clause = ""
    else:
        corridor_clause = _pick(
            (
                f"Held inside the {corridor.name.lower()} corridor.",
                f"All of it filtered through {corridor.name.lower()}.",
                f"Shopping that target on the {corridor.name.lower()} shelf.",
            ),
            seed,
            "corridor",
        )

    # ---- taste -------------------------------------------------------------
    taste_note = _taste_note(taste, theme, seed)

    # ---- body --------------------------------------------------------------
    body_parts = [lead, landing]
    if mechanism:
        body_parts.append(mechanism)
    if corridor_clause:
        body_parts.append(corridor_clause)

    opener = _track_label(tracks[0]) if tracks else None
    if opener:
        body_parts.append(
            _pick(
                (f"It opens on {opener}.", f"First up: {opener}.", f"Starts with {opener}."),
                seed,
                "opener",
            )
        )
    body_parts.append(_voice_tail(theme, seed))
    body = " ".join(part for part in body_parts if part)

    # ---- headline (Spotify Daylist style: weather + time-of-day + micro-genres) ----
    if sky.pressure_trend_6h <= -0.10:
        glass = "a falling barometer"
    elif sky.pressure_trend_6h >= 0.10:
        glass = "a building barometer"
    else:
        glass = "a steady barometer"

    utc_dt = getattr(sky, "observed_at", None)
    utc_hour = getattr(utc_dt, "hour", 14)
    coords = getattr(sky, "coordinates", None)
    tz_offset = 1.0
    if coords is not None:
        try:
            from ..sky.geocaches import find_nearest_geocache

            gc = find_nearest_geocache(coords.latitude, coords.longitude)
            if gc is not None:
                tz_offset = gc.tz_offset_hours
            else:
                tz_offset = round(coords.longitude / 15.0)
        except Exception:  # noqa: BLE001
            tz_offset = round(coords.longitude / 15.0)
    obs_hour = int((utc_hour + tz_offset) % 24)
    if getattr(sky, "golden_hour_proximity", 0.0) > 0.55:
        tod = "golden hour"
    elif obs_hour < 6:
        tod = "late night"
    elif obs_hour < 11:
        tod = "morning"
    elif obs_hour < 14:
        tod = "midday"
    elif obs_hour < 18:
        tod = "afternoon"
    elif obs_hour < 21:
        tod = "twilight"
    else:
        tod = "night"

    seen_tags: list[str] = []
    for item in tracks or ():
        tr = getattr(item, "track", item)
        for tag in getattr(tr, "tags", None) or ():
            clean = str(tag).strip().lower()
            if clean and not clean.startswith("via:") and clean not in seen_tags:
                seen_tags.append(clean)
            if len(seen_tags) >= 2:
                break
        if len(seen_tags) >= 2:
            break
    if len(seen_tags) >= 2:
        genres_str = f"{seen_tags[0]} & {seen_tags[1]}"
    elif len(seen_tags) == 1:
        genres_str = f"{seen_tags[0]} & atmospheric drift"
    elif corridor.id != "any":
        genres_str = f"{corridor.name.lower()} & atmospheric drift"
    else:
        genres_str = "misty synthwave & atmospheric indie"

    headline_options = (
        f"{theme.name.lower()} {tod} daylist — {genres_str} for {glass} ({sonic.tempo_bpm:.0f} BPM)",
        f"{tod} {theme.name.lower()} drift • {genres_str} under {glass} ({sonic.tempo_bpm:.0f} BPM)",
        f"{genres_str} {tod} — {theme.name.lower()} daylist at {sonic.tempo_bpm:.0f} BPM under {glass}",
    )
    headline = _pick(headline_options, seed, "headline")

    # ---- sonic moves -------------------------------------------------------
    if moves:
        sonic_moves = [str(move) for move in moves]
    else:
        sonic_moves = []
        for sky_dim, sonic_dim, contribution in explain_transfer(sky, sonic, top_n=4):
            note = COEFFICIENT_NOTES.get((sky_dim, sonic_dim), "")
            arrow = "up" if contribution > 0 else "down"
            label = _LANDING_LABEL.get(sonic_dim, sonic_dim)
            sky_label = _SKY_LABEL.get(sky_dim, sky_dim.replace("_", " "))
            # "wired because", not "because" -- see the note in _mechanism.
            suffix = f" (wired that way because {note})" if note else ""
            sonic_moves.append(
                f"{_sentence(sky_label)} moved {label} {arrow} by "
                f"{abs(contribution):.2f}{suffix}"
            )

    # ---- degradation and confidence ----------------------------------------
    degraded_lines = _plain_degraded(degraded)
    if taste is None and not any("Last.fm" in line for line in degraded_lines):
        degraded_lines.append(
            "No listening history in this one — theme-only, which is a fallback and not a feature."
        )

    confidence = 0.74
    if taste is not None:
        confidence += 0.12 * taste.confidence
    confidence -= 0.07 * len(degraded_lines)
    if sky.stale:
        confidence -= 0.16
    if not facts:
        # Nothing in the sky to point at. The playlist is fine; the *explanation*
        # is weak, and confidence is a claim about the explanation.
        confidence -= 0.10
    confidence = round(clamp(confidence, 0.05, 0.97), 3)

    return Rationale(
        headline=headline,
        body=body,
        sky_reading=reading,
        sonic_moves=sonic_moves,
        taste_note=taste_note,
        confidence=confidence,
        degraded=degraded_lines,
    )
