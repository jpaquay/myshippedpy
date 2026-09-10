"""Scoring. This module *is* the recommendation engine.

Since 27 Nov 2024 there is no ``/recommendations`` and no ``/audio-features``
to lean on, so nothing upstream of here has ranked anything. The pool that
arrives from ``candidates.py`` is a bag of plausible records; the ordering
they leave in is entirely ours, computed in SonicVector space against a target
the sky produced.

Design rule for this file: a reader who disagrees with the taste on display
should be able to fix it by editing one dict and nothing else. Every number
that expresses an opinion lives in ``SCORE_WEIGHTS``, ``DIM_WEIGHTS``,
``PENALTIES`` or ``NOVELTY`` at the top, with the reasoning next to it.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

from ..contracts import (
    SONIC_DIMS,
    GenreCorridor,
    ScoredTrack,
    SonicVector,
    TasteVector,
    Theme,
    clamp,
    lerp,
)
from .candidates import Candidate

# ---------------------------------------------------------------------------
# TOP-LEVEL SCORE MIX
# ---------------------------------------------------------------------------
# The five components are computed independently in [0,1] and mixed here. They
# sum to 1.0 so `score` stays interpretable as "fraction of a perfect track".
SCORE_WEIGHTS: dict[str, float] = {
    # Distance to the sky-derived target. This is the product. If weather does
    # not dominate the ordering then BAROGROOVE is a mood-board with a
    # thermometer, so it gets the plurality -- but not the majority, because a
    # tag-derived vector is an *estimate* and betting everything on an
    # estimate is how you end up with fourteen songs at 94 BPM.
    "sonic": 0.44,
    # Overlap with the listener's own tag/artist profile. Second-largest, and
    # it is already internally scaled by taste.confidence, so a cold-start user
    # effectively redistributes this weight to the other four.
    "taste": 0.22,
    # Genre corridor. Deliberately below taste: the corridor is a constraint
    # the user chose, and constraints are better enforced as a soft floor than
    # as the main axis of ranking.
    "corridor": 0.18,
    # Discovery value. Small but non-zero -- see the NOVELTY block for the
    # shape, which matters far more than this weight does.
    "novelty": 0.10,
    # How much we trust our own numbers: a track-level vector beats a
    # tag-derived one, and a record both retrieval phases found beats one only
    # a single chart coughed up. Small, but it reliably breaks ties in favour
    # of the record we actually know something about.
    "evidence": 0.06,
}

# ---------------------------------------------------------------------------
# PER-DIMENSION DISTANCE WEIGHTS
# ---------------------------------------------------------------------------
# Not all seven dims are equally audible, and not all are equally well
# estimated from tags. These weights encode both.
DIM_WEIGHTS: dict[str, float] = {
    # Valence is the axis a listener notices in four seconds, and it is the
    # axis the barometer moves hardest. Top weight.
    "valence": 1.00,
    # Energy is nearly as audible and much better estimated from tags than
    # valence is ("hardcore" is unambiguous about energy, ambiguous about mood).
    "energy": 0.95,
    # Tempo matters, but a 6 BPM miss is inaudible while a 0.06 valence miss is
    # not, and tag-derived tempo is noisy. Weighted below the two majors.
    "tempo": 0.70,
    # Acousticness is a strong genre signal, so the corridor term is already
    # policing much of it. Avoid double-counting.
    "acousticness": 0.55,
    # Density (how much is going on) is real but secondary; listeners tolerate
    # a wide range within one sitting.
    "density": 0.45,
    # Grit is the most poorly estimated dim from tags -- production texture is
    # exactly what tags do not describe -- so it is discounted for humility,
    # not for irrelevance.
    "grit": 0.40,
    # Spatiality (reverb, room, width) is the quietest axis by default and the
    # one most likely to be a theme's entire point, which is why the theme is
    # allowed to raise it below. Base weight is low.
    "spatiality": 0.35,
}

# How hard a theme is allowed to bend DIM_WEIGHTS. A theme that stakes out an
# extreme position on a dim (Glass Barometer at spatiality 0.82) is telling you
# that dim carries its identity; missing it is a worse error than usual.
# 0.9 lets an extreme, fully-committed theme roughly double a dim's weight and
# no more -- enough to change the ordering, not enough to make the other six
# dims decorative.
THEME_DIM_SENSITIVITY: float = 0.9

# ---------------------------------------------------------------------------
# PENALTIES (subtracted from the mixed score, after mixing)
# ---------------------------------------------------------------------------
PENALTIES: dict[str, float] = {
    # First avoid_tag hit. Large: avoid_tags are a theme saying "this breaks
    # the spell", and one Happy Hardcore record in Glass Barometer ruins the
    # whole playlist in a way one merely mediocre record does not.
    "avoid_tag": 0.30,
    # Each further avoid_tag. Diminishing -- the damage is already done.
    "avoid_tag_extra": 0.08,
    # No tags at all. Not fatal, but such a record can only ever have been
    # scored on a neutral vector, so it is a coin flip wearing a suit.
    "untagged": 0.06,
    # Absurd durations: sub-45s interludes and 20-minute drones both wreck an
    # arc. Applied only when duration is actually known.
    "duration_outlier": 0.10,
}

# Applied to `duration_outlier`.
_MIN_SANE_MS = 45_000
_MAX_SANE_MS = 12 * 60_000

# ---------------------------------------------------------------------------
# NOVELTY SHAPE
# ---------------------------------------------------------------------------
# We do not get per-user track playcounts from the taste vector, so "already
# scrobbled to death" is approximated from two observable things: whether the
# artist is in the user's top artists, and how globally huge the record is.
#
# The shape is the argument, not the weight. A playlist of nothing but
# strangers is a bad playlist -- it has no gravity, nothing to recognise, and
# the listener bails at track three. A playlist of nothing but your own top
# artists is a shuffle button. So novelty is a *hump*: it peaks not at
# "unknown" but at ADJACENT -- a record from a neighbourhood you recognise but
# a track you have not worn out. That is the "two hops from Talk Talk" zone,
# and it is where this product lives.
NOVELTY: dict[str, float] = {
    # Familiarity value that scores a perfect 1.0. Below the midpoint, so the
    # bias is toward discovery.
    "sweet_spot": 0.42,
    # What a total stranger scores. High on purpose: unknown records are the
    # point, they just should not out-rank adjacent ones.
    "stranger_floor": 0.55,
    # How fast the score falls off past the sweet spot. 0.78 puts a
    # top-artist mega-hit near 0.22 -- it can still make the cut on sonic fit
    # alone, which is correct, because sometimes the obvious record is right.
    "overplay_slope": 0.78,
    # Familiarity contributed by "this artist is in your top artists".
    "artist_weight": 0.62,
    # Familiarity contributed by global popularity (log listeners).
    "popularity_weight": 0.38,
    # Listener count treated as "everyone knows this". log-scaled.
    "popularity_ceiling": 1_500_000.0,
}

# Taste affinity internals.
TASTE: dict[str, float] = {
    # How many of the user's top tags form the normalisation horizon. Using the
    # whole dict would let a long thin tail dilute a genuinely strong match.
    "tag_horizon": 8.0,
    # Share of raw affinity that comes from tag overlap vs. the artist bonus.
    "tag_share": 0.72,
    # Flat bonus for a track by an artist already in the top list.
    "artist_bonus": 0.34,
}

# Corridor internals.
CORRIDOR: dict[str, float] = {
    # Hitting this many corridor tags counts as a full tag match. Requiring all
    # of them would mean nothing ever fits, since Last.fm tagging is sparse.
    "tags_for_full_credit": 2.0,
    # How much of corridor_fit comes from the anchor vector rather than tags,
    # when the corridor has an anchor. Tags are the more reliable genre signal;
    # the anchor is a sanity check.
    "anchor_share": 0.35,
}


# ---------------------------------------------------------------------------
# distance
# ---------------------------------------------------------------------------


def theme_dim_weights(theme: Theme | None) -> dict[str, float]:
    """DIM_WEIGHTS, bent by the theme's own priorities.

    Two channels, both optional:

    * ``theme.affinity`` -- any key that names a sonic dim is read as a direct
      multiplier. This is the explicit channel: a theme author who knows their
      theme lives or dies on grit can just say so.
    * ``theme.bias`` extremity -- the implicit channel. Distance from 0.5 on a
      dim, scaled by ``bias_weight``, means the theme has committed to that dim
      and we should punish misses there harder.
    """
    weights = dict(DIM_WEIGHTS)
    if theme is None:
        return weights

    affinity = theme.affinity or {}
    bias = theme.bias
    commitment = clamp(theme.bias_weight, 0.0, 1.0)

    for dim in SONIC_DIMS:
        w = weights[dim]
        explicit = affinity.get(dim)
        if isinstance(explicit, (int, float)) and explicit > 0:
            w *= float(explicit)
        # |bias - 0.5| * 2 maps a dim's extremity onto [0,1].
        extremity = abs(getattr(bias, dim, 0.5) - 0.5) * 2.0
        w *= 1.0 + THEME_DIM_SENSITIVITY * extremity * commitment
        weights[dim] = w
    return weights


def weighted_distance(
    a: SonicVector, b: SonicVector, weights: dict[str, float] | None = None
) -> float:
    """Normalised weighted Euclidean distance in [0,1].

    Normalising by the weight total keeps the result comparable across themes,
    which matters because ``theme_dim_weights`` changes the weight total. Two
    themes must not produce scores on different scales.
    """
    w = weights or DIM_WEIGHTS
    total = sum(w.get(d, 0.0) for d in SONIC_DIMS)
    if total <= 0:
        return 0.0
    acc = 0.0
    for d in SONIC_DIMS:
        acc += w.get(d, 0.0) * (getattr(a, d) - getattr(b, d)) ** 2
    return clamp(math.sqrt(acc / total))


def per_dim_gaps(a: SonicVector, b: SonicVector) -> dict[str, float]:
    """Signed gap per dim, candidate minus target. Used to write the ``why``."""
    return {d: getattr(a, d) - getattr(b, d) for d in SONIC_DIMS}


# ---------------------------------------------------------------------------
# components
# ---------------------------------------------------------------------------


def taste_affinity(cand: Candidate, taste: TasteVector | None) -> float:
    """Tag overlap plus an artist bonus, scaled by how much profile there is."""
    if taste is None or taste.confidence <= 0.0 or not (taste.top_tags or taste.top_artists):
        return 0.0

    top = taste.top_tags or {}
    horizon = int(TASTE["tag_horizon"])
    norm = sum(sorted(top.values(), reverse=True)[:horizon]) or 1.0

    hit = sum(float(top.get(t, 0.0)) for t in cand.tags)
    tag_score = clamp(hit / norm)

    artists = {a.lower() for a in taste.top_artists}
    bonus = TASTE["artist_bonus"] if cand.track.artist.lower() in artists else 0.0

    raw = clamp(TASTE["tag_share"] * tag_score + bonus)
    # Scaling by confidence is what stops a fifty-scrobble account from
    # steering the whole playlist toward the three bands it has heard.
    return clamp(raw * clamp(taste.confidence))


def corridor_fit(cand: Candidate, corridor: GenreCorridor) -> float:
    """How comfortably the record sits inside the requested genre corridor."""
    tags = set(cand.tags)
    corridor_tags = {t.lower() for t in (corridor.tags or ())}

    if not corridor_tags:
        # The "any" corridor is not a constraint, and pretending it is one
        # would make every score in unconstrained mode identically mediocre.
        tag_fit = 1.0
    else:
        hits = len(tags & corridor_tags)
        tag_fit = clamp(hits / max(1.0, min(CORRIDOR["tags_for_full_credit"], len(corridor_tags))))
        # Width forgives misses: a wide corridor is a suggestion, a narrow one
        # is a rule. width=1.0 -> everything fits; width=0.0 -> tags only.
        tag_fit = clamp(tag_fit + clamp(corridor.width) * (1.0 - tag_fit))

    if corridor.anchor is None:
        return tag_fit

    anchor_fit = 1.0 - weighted_distance(cand.estimated, corridor.anchor)
    return clamp(lerp(tag_fit, anchor_fit, CORRIDOR["anchor_share"]))


def _familiarity(cand: Candidate, taste: TasteVector | None) -> float:
    artist_known = 0.0
    if taste is not None and taste.top_artists:
        if cand.track.artist.lower() in {a.lower() for a in taste.top_artists}:
            artist_known = 1.0

    listeners = float(cand.track.listeners or 0)
    if listeners > 0:
        popularity = clamp(
            math.log10(1.0 + listeners) / math.log10(1.0 + NOVELTY["popularity_ceiling"])
        )
    else:
        # Unknown listener count is treated as mid-obscure rather than zero:
        # absence of data is not evidence of obscurity, and scoring it as a
        # perfect stranger would reward records the oracle simply failed to
        # annotate.
        popularity = 0.35

    return clamp(
        NOVELTY["artist_weight"] * artist_known + NOVELTY["popularity_weight"] * popularity
    )


def novelty(cand: Candidate, taste: TasteVector | None) -> float:
    """Discovery value: a hump peaked on *adjacent*, not on *unknown*."""
    f = _familiarity(cand, taste)
    sweet = NOVELTY["sweet_spot"]
    if f <= sweet:
        floor = NOVELTY["stranger_floor"]
        return clamp(floor + (1.0 - floor) * (f / sweet if sweet > 0 else 1.0))
    return clamp(1.0 - NOVELTY["overplay_slope"] * ((f - sweet) / max(1e-6, 1.0 - sweet)))


def evidence(cand: Candidate) -> float:
    """Confidence in our own numbers for this record."""
    agreement = clamp((cand.phases - 1) / 1.0)  # 1 phase -> 0.0, 2+ -> 1.0
    return clamp(0.75 * cand.estimate_quality + 0.25 * agreement)


def penalty(cand: Candidate, theme: Theme | None) -> tuple[float, list[str]]:
    total = 0.0
    reasons: list[str] = []

    avoid = {t.lower() for t in (theme.avoid_tags if theme else ())}
    hits = [t for t in cand.tags if t in avoid]
    if hits:
        total += PENALTIES["avoid_tag"]
        total += PENALTIES["avoid_tag_extra"] * (len(hits) - 1)
        reasons.append(f"avoid:{hits[0]}")

    if not cand.tags:
        total += PENALTIES["untagged"]
        reasons.append("untagged")

    dur = cand.track.duration_ms
    if dur is not None and (dur < _MIN_SANE_MS or dur > _MAX_SANE_MS):
        total += PENALTIES["duration_outlier"]
        reasons.append("duration")

    return total, reasons


# ---------------------------------------------------------------------------
# the `why`
# ---------------------------------------------------------------------------

WHY: dict[str, float] = {
    # A gap this small or smaller counts as "we hit it", so a heavily-weighted
    # dim gets named ahead of a lightly-weighted one we happened to hit dead on.
    "headline_tolerance": 0.06,
    # Below this the gap is rounding noise and quoting "0.00" looks like a bug
    # rather than a boast.
    "exact_epsilon": 0.005,
    # Tempo is called out as a second clause when it is this close, even if
    # another dim won the numeric slot: BPM is the number people can feel.
    "tempo_callout": 0.05,
    # Above this, no dim is close enough to be worth quoting as a match.
    "loose_threshold": 0.15,
}

_LEAD_TAG_BLOCKLIST = {"seen live", "favourites", "favorites", "awesome", "music", "rock", "pop"}


def _lead_tag(cand: Candidate, corridor: GenreCorridor) -> str:
    """The most descriptive tag we can find. Genre words beat mood words."""
    corridor_tags = [t.lower() for t in (corridor.tags or ())]
    for t in cand.seed_tags_hit:
        if t not in _LEAD_TAG_BLOCKLIST:
            return t
    for t in cand.tags:
        if t in corridor_tags and t not in _LEAD_TAG_BLOCKLIST:
            return t
    # Fall back to the first tag that is not a Last.fm folksonomy weed.
    # Multi-word tags ("dream pop") are more descriptive than single-word ones
    # ("uk"), so they win the tie.
    plain = [t for t in cand.tags if t not in _LEAD_TAG_BLOCKLIST]
    for t in plain:
        if " " in t:
            return t
    return plain[0] if plain else ""


def build_why(
    cand: Candidate,
    target: SonicVector,
    *,
    corridor: GenreCorridor,
    dim_weights: dict[str, float],
) -> str:
    """One concrete line per track. Two clauses, no filler, no adjectives we
    cannot defend.

    Clause 1 is provenance when the record came out of the taste graph (the
    most interesting thing we know about it) and the lead tag otherwise.
    Clause 2 is always a number, because a number is what makes the first
    clause credible.
    """
    gaps = per_dim_gaps(cand.estimated, target)

    # Pick the numeric clause. Preference order matters: a listener does not
    # care that we nailed grit, they care that we nailed valence. So look first
    # among the dims this theme weights most heavily and take the closest of
    # those; only if none of them landed do we fall back to whichever dim we
    # happened to get right.
    headline_dims = sorted(SONIC_DIMS, key=lambda d: -dim_weights.get(d, 0.0))[:3]
    near = [d for d in headline_dims if abs(gaps[d]) <= WHY["headline_tolerance"]]
    if near:
        best = min(near, key=lambda d: abs(gaps[d]))
    else:
        best = min(SONIC_DIMS, key=lambda d: abs(gaps[d]) / max(1e-6, dim_weights.get(d, 1.0)))
        # Nothing landed anywhere near. A record can still legitimately be here
        # on corridor fit, taste or arc position, and quoting a 0.38 miss as
        # though it were a virtue is worse than saying nothing. Fall back to
        # the BPM pair: always meaningful, never a boast.
        if abs(gaps[best]) > WHY["loose_threshold"]:
            best = "tempo"

    if best == "tempo":
        numeric = f"{cand.estimated.tempo_bpm:.0f} BPM against a {target.tempo_bpm:.0f} target"
    elif abs(gaps[best]) < WHY["exact_epsilon"]:
        numeric = f"lands on target {best}"
    else:
        numeric = f"sits {abs(gaps[best]):.2f} from target {best}"

    if cand.provenance in ("similar-artist", "similar-track") and cand.provenance_detail:
        lead = cand.provenance_detail
    else:
        tag = _lead_tag(cand, corridor)
        lead = f"{tag}" if tag else (cand.provenance_detail or "on-corridor")

    # Tempo is worth naming outright when it is the theme's whole gesture, even
    # if another dim landed closer.
    tempo_gap = abs(gaps["tempo"])
    if best != "tempo" and tempo_gap < WHY["tempo_callout"]:
        numeric = f"{cand.estimated.tempo_bpm:.0f} BPM, {numeric}"

    why = f"{lead}, {numeric}"
    return why[:1].upper() + why[1:] if why else ""


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def score_candidate(
    cand: Candidate,
    *,
    target: SonicVector,
    theme: Theme | None,
    corridor: GenreCorridor,
    taste: TasteVector | None,
    dim_weights: dict[str, float] | None = None,
) -> ScoredTrack:
    """Score one candidate. Every sub-score on ScoredTrack is populated."""
    weights = dim_weights if dim_weights is not None else theme_dim_weights(theme)

    distance = weighted_distance(cand.estimated, target, weights)
    affinity = taste_affinity(cand, taste)
    fit = corridor_fit(cand, corridor)
    disc = novelty(cand, taste)
    ev = evidence(cand)

    mixed = (
        SCORE_WEIGHTS["sonic"] * (1.0 - distance)
        + SCORE_WEIGHTS["taste"] * affinity
        + SCORE_WEIGHTS["corridor"] * fit
        + SCORE_WEIGHTS["novelty"] * disc
        + SCORE_WEIGHTS["evidence"] * ev
    )
    pen, _reasons = penalty(cand, theme)
    score = clamp(mixed - pen)

    return ScoredTrack(
        track=cand.track,
        score=score,
        sonic_distance=distance,
        taste_affinity=affinity,
        corridor_fit=fit,
        novelty=disc,
        role="body",
        position=0,
        why=build_why(cand, target, corridor=corridor, dim_weights=weights),
    )


def rerank(
    candidates: Iterable[Candidate],
    *,
    target: SonicVector,
    theme: Theme | None,
    corridor: GenreCorridor,
    taste: TasteVector | None = None,
) -> list[ScoredTrack]:
    """Score the whole pool and return it best-first.

    Ties are broken on ``Track.key`` so that a seeded forge is reproducible
    even when two tag-derived vectors land on identical numbers, which with
    coarse tag estimates happens constantly.
    """
    weights = theme_dim_weights(theme)
    scored = [
        score_candidate(
            c, target=target, theme=theme, corridor=corridor, taste=taste, dim_weights=weights
        )
        for c in candidates
    ]
    scored.sort(key=lambda s: (-s.score, s.track.key))
    return scored


def explain_weights(theme: Theme | None = None) -> list[tuple[str, float]]:
    """The effective per-dim weights, for debugging and for the demo script."""
    return sorted(theme_dim_weights(theme).items(), key=lambda kv: -kv[1])
