"""Retrospectives: what the Almanac tells you about yourself.

This is the part of the Almanac the user meets. Everything else exists so that
this module can say something true and slightly uncomfortable, like *your rain
sound is wider and sadder than you think it is*, and be right.

Method
------
1. **Assign every forge to a named sky region.** Not clustering in the k-means
   sense — an explainable nearest-prototype assignment over a handful of
   hand-named regions, each defined by the *derivative* dimensions that make
   it what it is. ``collapsing_barometer`` is defined by
   ``pressure_trend_6h``, not by rain; ``first_frost`` is cold *and* clear
   *and* high-pressure, because cold on a falling glass is a different record.
   The regions are legible, so a card can always answer "why did you put this
   forge in that bucket".

2. **Characterise each region by its loved tracks.** The mean SonicVector of
   what you kept, not of what you were served. Where you have not loved
   anything yet, we fall back to what the engine aimed at and we say so —
   that is a weaker claim and it gets phrased as one.

3. **Write it down in the product's voice.** Dry, specific, no horoscopes.

Cold start
----------
With two or three forges there is nothing to say, so we say that. A
retrospective that invents a personality out of three data points is worse
than no retrospective, because the user will believe it.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import SKY_DIMS, SONIC_DIMS, SkyVector, SonicVector, clamp
from .models import FeedbackEvent, ForgeRecord, NudgeDocument

# =============================================================================
# TUNABLES — every knob in the module, in one place.
# =============================================================================

#: Below this many forges we refuse to characterise anyone. Three points and a
#: confident tone is astrology.
COLD_START_FORGES: int = 5

#: A region card needs at least this many forges assigned to it before it will
#: render at all.
MIN_REGION_FORGES: int = 3

#: ...and at least this many loves before we claim the signature is *yours*
#: rather than the engine's. Below it, the card is phrased as an observation
#: about what you were served.
MIN_REGION_LOVES: int = 2

#: A forge further than this (weighted RMS over the region's defining dims)
#: from every prototype falls through to ``slack_water``. Keeps a merely damp
#: afternoon out of ``deluge``. Calibrated against the neutral sky: an all-zero
#: SkyVector sits ~0.54 from its nearest prototype, so the cut must fall below
#: that or "nothing is happening" gets read as a cold snap. 0.45 leaves ample
#: room for genuine mid-strength readings (a -0.5 pressure trend lands at 0.23)
#: while excluding the null sky.
REGION_MAX_DISTANCE: float = 0.45

#: Card confidence: n / (n + CARD_CONFIDENCE_HALF). Half-confidence at four
#: supporting forges; deliberately quick to rise, because these are
#: descriptive claims, not model weights.
CARD_CONFIDENCE_HALF: float = 4.0

#: How far a sonic dimension must sit from the 0.5 midpoint before it earns an
#: adjective. Below this the dimension is unremarkable and stays quiet.
ADJECTIVE_THRESHOLD: float = 0.09

#: Adjectives per signature. Three is a description; six is a spec sheet.
MAX_ADJECTIVES: int = 3

#: Artists listed in the most-loved card.
TOP_ARTISTS: int = 5

#: Minimum forges before the seasonal-drift card will attempt a comparison; it
#: splits history in half and needs both halves to mean something.
MIN_STREAK_FORGES: int = 8

#: A sonic dimension has to move by at least this much between the two halves
#: of your history before we call it drift rather than noise.
STREAK_MIN_DELTA: float = 0.05


# =============================================================================
# Sky regions — hand-named, derivative-first, explainable by construction
# =============================================================================


class SkyRegion(BaseModel):
    """A named corner of sky space.

    ``prototype`` gives target values only for the dimensions that *define* the
    region; ``weights`` gives their relative importance. Dimensions absent from
    ``prototype`` are ignored entirely in the distance, which is what makes
    assignment explainable: ``collapsing_barometer`` genuinely does not care
    about cloud depth, and the arithmetic reflects that.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    blurb: str
    prototype: dict[str, float]
    weights: dict[str, float] = Field(default_factory=dict)

    def distance(self, sky: SkyVector) -> float:
        """Weighted RMS distance over the defining dimensions only."""
        values = sky.as_dict()
        num = 0.0
        den = 0.0
        for dim, target in self.prototype.items():
            w = self.weights.get(dim, 1.0)
            num += w * (values.get(dim, 0.0) - target) ** 2
            den += w
        return math.sqrt(num / den) if den else 1.0

    def why(self, sky: SkyVector) -> list[str]:
        """Per-dimension justification for an assignment. Debuggable UI."""
        values = sky.as_dict()
        return [
            f"{dim}={values.get(dim, 0.0):+.2f} (wants {target:+.2f})"
            for dim, target in sorted(self.prototype.items())
        ]


#: The regions. Note how many of them are keyed on a rate of change or a
#: relative deviation rather than an absolute reading — that is the product's
#: whole thesis, expressed as a data structure.
SKY_REGIONS: tuple[SkyRegion, ...] = (
    SkyRegion(
        id="collapsing_barometer",
        name="the falling glass",
        blurb="pressure dropping out from under the afternoon",
        prototype={"pressure_trend_6h": -0.75, "pressure_norm_deviation": -0.35},
        weights={"pressure_trend_6h": 3.0, "pressure_norm_deviation": 1.0},
    ),
    SkyRegion(
        id="rising_barometer",
        name="the glass climbing",
        blurb="pressure building, weather clearing out ahead of you",
        prototype={"pressure_trend_6h": 0.75, "pressure_norm_deviation": 0.35},
        weights={"pressure_trend_6h": 3.0, "pressure_norm_deviation": 1.0},
    ),
    SkyRegion(
        id="deluge",
        name="rain, actually falling",
        blurb="precipitation with real intensity behind it",
        prototype={"precip_intensity": 0.85, "cloud_depth": 0.8},
        weights={"precip_intensity": 3.0, "cloud_depth": 1.0},
    ),
    SkyRegion(
        id="first_frost",
        name="cold, clear, and high",
        blurb="a hard cold snap under a settled sky",
        prototype={
            "temp_norm_deviation": -0.7,
            "cloud_depth": 0.1,
            "pressure_norm_deviation": 0.6,
            "precip_intensity": 0.0,
        },
        weights={
            "temp_norm_deviation": 3.0,
            "cloud_depth": 1.5,
            "pressure_norm_deviation": 2.0,
            "precip_intensity": 1.0,
        },
    ),
    SkyRegion(
        id="golden_hour",
        name="golden hour",
        blurb="the sun low and about to go",
        prototype={"golden_hour_proximity": 0.9, "sun_elevation": 0.12},
        weights={"golden_hour_proximity": 3.0, "sun_elevation": 1.0},
    ),
    SkyRegion(
        id="gale",
        name="the wind getting ideas",
        blurb="gusts all over the place",
        prototype={"gust_variance": 0.85},
        weights={"gust_variance": 3.0},
    ),
    SkyRegion(
        id="flat_grey",
        name="flat grey",
        blurb="thick cloud, no rain, no opinion",
        prototype={"cloud_depth": 0.85, "precip_intensity": 0.05, "pressure_trend_6h": 0.0},
        weights={"cloud_depth": 2.0, "precip_intensity": 1.5, "pressure_trend_6h": 1.0},
    ),
    SkyRegion(
        id="long_light",
        name="the light coming back",
        blurb="days lengthening, sun high",
        prototype={"daylight_delta": 0.7, "sun_elevation": 0.6},
        weights={"daylight_delta": 2.5, "sun_elevation": 1.0},
    ),
    SkyRegion(
        id="closing_in",
        name="the light going",
        blurb="days shortening, sun low",
        prototype={"daylight_delta": -0.7, "sun_elevation": 0.1},
        weights={"daylight_delta": 2.5, "sun_elevation": 1.0},
    ),
)

#: Catch-all for forges that resemble nothing in particular. Every history has
#: some, and pretending otherwise is how you get a card about a user's
#: relationship with mild Tuesdays.
SLACK_WATER = SkyRegion(
    id="slack_water",
    name="slack water",
    blurb="nothing the sky is doing is worth a card",
    prototype={},
)

REGIONS_BY_ID: dict[str, SkyRegion] = {r.id: r for r in SKY_REGIONS}
REGIONS_BY_ID[SLACK_WATER.id] = SLACK_WATER


def assign_region(sky: SkyVector) -> tuple[SkyRegion, float]:
    """Nearest prototype, or ``slack_water`` if nothing is close enough.

    Ties break on region id so the assignment is deterministic.
    """
    ranked = sorted(
        ((region.distance(sky), region.id, region) for region in SKY_REGIONS),
        key=lambda t: (t[0], t[1]),
    )
    if not ranked:
        return SLACK_WATER, float("inf")
    best_d, _, best = ranked[0]
    if best_d > REGION_MAX_DISTANCE:
        return SLACK_WATER, best_d
    return best, best_d


# =============================================================================
# Vocabulary — turning a SonicVector into English
# =============================================================================

#: (low adjective, high adjective) per sonic dimension. Kept deliberately
#: concrete: "cavernous" tells you something, "spatial" does not.
_SONIC_WORDS: dict[str, tuple[str, str]] = {
    "valence": ("downcast", "bright"),
    "energy": ("still", "driven"),
    "tempo": ("slow", "quick"),
    "acousticness": ("electric", "acoustic"),
    "density": ("sparse", "dense"),
    "grit": ("clean", "gritty"),
    "spatiality": ("close", "cavernous"),
}


def describe_sonic(vec: SonicVector, *, limit: int = MAX_ADJECTIVES) -> list[str]:
    """The dimensions furthest from the midpoint, as adjectives.

    A vector sitting near 0.5 on everything gets an empty list, and the callers
    are expected to notice and say something honest instead of padding.
    """
    values = vec.as_dict()
    ranked = sorted(
        (
            (abs(v - 0.5), dim, v)
            for dim, v in values.items()
            if abs(v - 0.5) >= ADJECTIVE_THRESHOLD
        ),
        key=lambda t: (-t[0], t[1]),
    )
    out: list[str] = []
    for _, dim, v in ranked[:limit]:
        low, high = _SONIC_WORDS[dim]
        out.append(high if v > 0.5 else low)
    return out


def _phrase(adjectives: Sequence[str]) -> str:
    """Oxford-free comma list. 'slow, wide and largely acoustic'."""
    items = list(adjectives)
    if not items:
        return "resolutely middling"
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


# =============================================================================
# Card models
# =============================================================================


class TrackHighlight(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    artist: str
    loves: int = 0
    skips: int = 0
    appearances: int = 0

    @property
    def display(self) -> str:
        return f"{self.artist} — {self.title}"


class RetrospectiveCard(BaseModel):
    """One finding. ``kind`` is stable; everything else is prose."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    headline: str
    body: str
    #: Sample size behind the claim. Rendered in the UI; a card without it is a
    #: card the user cannot calibrate against.
    sample_size: int = 0
    confidence: float = 0.0
    region_id: str | None = None
    signature: SonicVector | None = None
    sky_reading: list[str] = Field(default_factory=list)
    tracks: list[TrackHighlight] = Field(default_factory=list)
    artists: list[str] = Field(default_factory=list)
    stats: dict[str, float] = Field(default_factory=dict)
    #: True when the card describes what the engine served rather than what the
    #: user demonstrably kept. A weaker claim, flagged as one.
    inferred_from_targets: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Retrospective(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    generated_at: datetime
    forges: int
    signals: int
    span_days: float
    cold_start: bool
    headline: str
    body: str
    cards: list[RetrospectiveCard] = Field(default_factory=list)
    #: Region id -> forge count. Useful on its own and the raw material behind
    #: several of the cards.
    region_counts: dict[str, int] = Field(default_factory=dict)
    #: Honest notes about what could not be computed and why.
    notes: list[str] = Field(default_factory=list)

    def card(self, kind: str) -> RetrospectiveCard | None:
        for c in self.cards:
            if c.kind == kind:
                return c
        return None

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# =============================================================================
# Aggregation helpers
# =============================================================================


def _confidence(n: int) -> float:
    return clamp(n / (n + CARD_CONFIDENCE_HALF)) if n > 0 else 0.0


def _mean_sonic(vectors: Sequence[SonicVector]) -> SonicVector | None:
    if not vectors:
        return None
    n = float(len(vectors))
    acc = [0.0] * len(SONIC_DIMS)
    for v in vectors:
        for i, x in enumerate(v.as_array()):
            acc[i] += x
    return SonicVector.from_array([x / n for x in acc])


def _mean_sky(vectors: Sequence[SkyVector]) -> dict[str, float]:
    if not vectors:
        return {}
    n = float(len(vectors))
    acc = {d: 0.0 for d in SKY_DIMS}
    for v in vectors:
        for d, x in v.as_dict().items():
            acc[d] += x
    return {d: x / n for d, x in acc.items()}


class _Bucket:
    """Everything we know about one sky region for one user."""

    __slots__ = ("region", "records", "loves", "skips")

    def __init__(self, region: SkyRegion) -> None:
        self.region = region
        self.records: list[ForgeRecord] = []
        self.loves: list[FeedbackEvent] = []
        self.skips: list[FeedbackEvent] = []

    @property
    def n(self) -> int:
        return len(self.records)

    def loved_sonics(self) -> list[SonicVector]:
        return [e.track_sonic for e in self.loves if e.track_sonic is not None]

    def target_sonics(self) -> list[SonicVector]:
        return [r.sonic for r in self.records]

    def signature(self) -> tuple[SonicVector | None, bool]:
        """(signature, inferred_from_targets).

        Prefer the mean of what was loved. Fall back to the mean of what was
        aimed at, and tell the caller, because those are different claims:
        one is taste, the other is only exposure.
        """
        loved = self.loved_sonics()
        if len(loved) >= MIN_REGION_LOVES:
            return _mean_sonic(loved), False
        return _mean_sonic(self.target_sonics()), True

    def highlights(self, limit: int = 3) -> list[TrackHighlight]:
        loves = Counter(e.track_key for e in self.loves)
        skips = Counter(e.track_key for e in self.skips)
        appearances: Counter[str] = Counter()
        names: dict[str, tuple[str, str]] = {}
        for record in self.records:
            for t in record.tracks:
                appearances[t.key] += 1
                names.setdefault(t.key, (t.title, t.artist))
        for e in self.loves + self.skips:
            names.setdefault(e.track_key, (e.track_title, e.track_artist))

        keys = sorted(
            set(loves) | set(appearances),
            key=lambda k: (-loves[k], skips[k], -appearances[k], k),
        )
        out: list[TrackHighlight] = []
        for k in keys[:limit]:
            title, artist = names.get(k, (k, ""))
            out.append(
                TrackHighlight(
                    key=k,
                    title=title,
                    artist=artist,
                    loves=loves[k],
                    skips=skips[k],
                    appearances=appearances[k],
                )
            )
        return out

    def top_artists(self, limit: int = 3) -> list[str]:
        counts: Counter[str] = Counter()
        for e in self.loves:
            if e.track_artist:
                counts[e.track_artist] += 1
        if not counts:
            for r in self.records:
                for t in r.tracks:
                    if t.artist:
                        counts[t.artist] += 1
        return [a for a, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def bucket_history(
    records: Sequence[ForgeRecord], events: Sequence[FeedbackEvent]
) -> dict[str, _Bucket]:
    """Assign every forge to a region and attach its feedback."""
    buckets: dict[str, _Bucket] = {}
    region_of: dict[str, str] = {}

    for record in sorted(records, key=lambda r: (r.created_at, r.playlist_id)):
        region, _ = assign_region(record.sky)
        region_of[record.playlist_id] = region.id
        buckets.setdefault(region.id, _Bucket(region)).records.append(record)

    for event in sorted(events, key=lambda e: (e.created_at, e.playlist_id, e.track_key)):
        rid = region_of.get(event.playlist_id)
        if rid is None:
            # Feedback whose forge we no longer hold: place it by its own
            # captured sky. This is exactly why the context is snapshotted.
            region, _ = assign_region(event.sky)
            rid = region.id
            buckets.setdefault(rid, _Bucket(region))
        bucket = buckets[rid]
        (bucket.loves if event.is_love else bucket.skips).append(event)

    return buckets


# =============================================================================
# Card builders
# =============================================================================
# Each returns a card or None. None means "not enough to say", and the caller
# turns that into an honest note rather than a padded card.


def _region_card(
    bucket: _Bucket | None,
    *,
    card_id: str,
    kind: str,
    headline_for: Any,
    opening: str,
) -> RetrospectiveCard | None:
    """Shared skeleton for the four region-signature cards.

    ``headline_for(phrase, bucket, inferred)`` writes the one-liner; the body
    is assembled here because the structure — signature, sample size, the
    sky reading that defines the region — is the same for all of them and
    should read the same too.
    """
    if bucket is None or bucket.n < MIN_REGION_FORGES:
        return None
    signature, inferred = bucket.signature()
    if signature is None:
        return None

    adjectives = describe_sonic(signature)
    phrase = _phrase(adjectives)
    loves = len(bucket.loves)
    skips = len(bucket.skips)

    detail_dims = sorted(
        signature.as_dict().items(), key=lambda kv: (-abs(kv[1] - 0.5), kv[0])
    )[:3]
    detail = ", ".join(f"{d} {v:.2f}" for d, v in detail_dims)

    if inferred:
        provenance = (
            f"That is what the engine aimed at across {bucket.n} forges — you "
            f"have not loved enough of it yet for us to call it yours."
        )
    else:
        provenance = (
            f"Measured off the {loves} track{'s' if loves != 1 else ''} you kept "
            f"across {bucket.n} forges"
            + (f", against {skips} you did not." if skips else ".")
        )

    mean_sky = _mean_sky([r.sky for r in bucket.records])
    reading = [
        f"{dim} {mean_sky[dim]:+.2f}"
        for dim in sorted(bucket.region.prototype, key=lambda d: -abs(mean_sky.get(d, 0.0)))
    ]

    body = f"{opening} {provenance} Centre of mass: {detail}."

    return RetrospectiveCard(
        id=card_id,
        kind=kind,
        headline=headline_for(phrase, bucket, inferred),
        body=body,
        sample_size=bucket.n,
        confidence=round(_confidence(bucket.n + loves), 4),
        region_id=bucket.region.id,
        signature=signature,
        sky_reading=reading,
        tracks=bucket.highlights(),
        artists=bucket.top_artists(),
        stats={
            "forges": float(bucket.n),
            "loves": float(loves),
            "skips": float(skips),
        },
        inferred_from_targets=inferred,
    )


def rain_sound_card(buckets: Mapping[str, _Bucket]) -> RetrospectiveCard | None:
    """Your rain sound: the signature you converge on when it is actually
    raining, as opposed to when it merely looks like it might."""
    return _region_card(
        buckets.get("deluge"),
        card_id="rain-sound",
        kind="rain_sound",
        headline_for=lambda phrase, b, inf: f"Your rain sound is {phrase}.",
        opening="When the precipitation is real rather than threatened, you go here.",
    )


def falling_barometer_card(buckets: Mapping[str, _Bucket]) -> RetrospectiveCard | None:
    """The most on-thesis card in the set.

    A falling barometer is not weather you can see. It is a rate of change, and
    it reliably predicts a different record than the same temperature under a
    rising glass. If this card is good, the product's central claim is true.
    """
    return _region_card(
        buckets.get("collapsing_barometer"),
        card_id="falling-barometer",
        kind="falling_barometer",
        headline_for=lambda phrase, b, inf: (
            f"On a falling barometer you reach for something {phrase}."
        ),
        opening=(
            "Pressure on its way down, before it has turned into anything you "
            "could point at out of the window."
        ),
    )


def golden_hour_card(buckets: Mapping[str, _Bucket]) -> RetrospectiveCard | None:
    return _region_card(
        buckets.get("golden_hour"),
        card_id="golden-hour",
        kind="golden_hour",
        headline_for=lambda phrase, b, inf: f"Your golden hour is {phrase}.",
        opening="The forty minutes before the sun goes, repeatedly.",
    )


def first_frost_card(buckets: Mapping[str, _Bucket]) -> RetrospectiveCard | None:
    """The standout track from cold, clear, high-pressure forges.

    Unlike the other region cards this one leads with a *record*, not a
    signature. Cold and clear and settled is a rarer situation than rain, so
    the honest unit of analysis is the single track you kept coming back to
    rather than a centre of mass over a thin sample.
    """
    bucket = buckets.get("first_frost")
    if bucket is None or bucket.n < MIN_REGION_FORGES:
        return None
    highlights = bucket.highlights(limit=3)
    if not highlights:
        return None
    top = highlights[0]
    signature, inferred = bucket.signature()

    if top.loves > 0:
        headline = f"Your first-frost record is {top.display}."
        body = (
            f"Cold, clear and high — {bucket.n} forges under a settled sky with "
            f"the temperature well under its norm. You kept {top.display} "
            f"{top.loves} time{'s' if top.loves != 1 else ''} out of "
            f"{top.appearances} appearance{'s' if top.appearances != 1 else ''}. "
            "Nothing else in that weather comes close."
        )
    else:
        headline = f"Cold and clear, the engine keeps handing you {top.display}."
        body = (
            f"{bucket.n} forges in cold, settled, high-pressure air. You have not "
            "told us what you think of any of it yet, so this is the engine's "
            "opinion rather than yours."
        )

    return RetrospectiveCard(
        id="first-frost",
        kind="first_frost",
        headline=headline,
        body=body,
        sample_size=bucket.n,
        confidence=round(_confidence(bucket.n + len(bucket.loves)), 4),
        region_id=bucket.region.id,
        signature=signature,
        sky_reading=bucket.region.why(bucket.records[0].sky),
        tracks=highlights,
        artists=bucket.top_artists(),
        stats={"forges": float(bucket.n), "loves": float(len(bucket.loves))},
        inferred_from_targets=inferred or top.loves == 0,
    )


def most_loved_artists_card(
    events: Sequence[FeedbackEvent],
) -> RetrospectiveCard | None:
    """Who you actually keep. Skips are subtracted, at half weight, for the
    same reason the learner discounts them: a skip is ambient, a love is an
    act. An artist you love four times and skip twice is still an artist you
    love."""
    loves: Counter[str] = Counter()
    skips: Counter[str] = Counter()
    for e in events:
        if not e.track_artist:
            continue
        (loves if e.is_love else skips)[e.track_artist] += 1
    if not loves:
        return None

    scored = sorted(
        ((a, loves[a] - 0.5 * skips.get(a, 0)) for a in loves),
        key=lambda kv: (-kv[1], kv[0]),
    )
    top = [a for a, s in scored if s > 0][:TOP_ARTISTS]
    if not top:
        return None

    lead = top[0]
    rest = top[1:]
    headline = f"You keep coming back to {lead}."
    if rest:
        body = (
            f"{loves[lead]} loves, across every sky we have on file. "
            f"Then {_phrase(rest)}. "
            "This is the part of your taste that does not care what the weather "
            "is doing."
        )
    else:
        body = (
            f"{loves[lead]} loves and nobody else in contention. "
            "A narrow file, so far."
        )

    return RetrospectiveCard(
        id="most-loved-artists",
        kind="most_loved_artists",
        headline=headline,
        body=body,
        sample_size=sum(loves.values()),
        confidence=round(_confidence(sum(loves.values())), 4),
        artists=top,
        stats={a: float(loves[a]) for a in top},
    )


def theme_signature_card(
    records: Sequence[ForgeRecord], events: Sequence[FeedbackEvent]
) -> RetrospectiveCard | None:
    """The artist most associated with each theme you use.

    Association means loves-within-theme where we have them, and appearances
    otherwise. Themes with no loves are reported as exposure, not taste.
    """
    theme_of = {r.playlist_id: r.theme_id for r in records}
    per_theme: dict[str, Counter[str]] = defaultdict(Counter)
    theme_forges: Counter[str] = Counter(r.theme_id for r in records)

    for e in events:
        if not e.is_love or not e.track_artist:
            continue
        theme = theme_of.get(e.playlist_id, e.theme_id)
        per_theme[theme][e.track_artist] += 1

    if not per_theme:
        for r in records:
            for t in r.tracks:
                if t.artist:
                    per_theme[r.theme_id][t.artist] += 1
        inferred = True
    else:
        inferred = False

    pairs: list[tuple[str, str, int]] = []
    for theme in sorted(per_theme):
        counts = per_theme[theme]
        if not counts:
            continue
        artist, n = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        pairs.append((theme, artist, n))
    if not pairs:
        return None

    lines = [f"{theme}: {artist}" for theme, artist, _ in pairs]
    headline = (
        f"{pairs[0][1]} is what {pairs[0][0]} means to you."
        if not inferred
        else f"{pairs[0][0]} keeps returning {pairs[0][1]}."
    )
    body = (
        "One artist per theme, ranked by what you kept: "
        + "; ".join(lines)
        + "."
        + ("" if not inferred else " Exposure, not preference — no loves on file yet.")
    )

    return RetrospectiveCard(
        id="theme-signatures",
        kind="theme_signatures",
        headline=headline,
        body=body,
        sample_size=sum(theme_forges.values()),
        confidence=round(_confidence(sum(n for _, _, n in pairs)), 4),
        artists=[a for _, a, _ in pairs],
        stats={theme: float(n) for theme, _, n in pairs},
        inferred_from_targets=inferred,
    )


def sky_streak_card(
    records: Sequence[ForgeRecord], buckets: Mapping[str, _Bucket]
) -> RetrospectiveCard | None:
    """How your listening has drifted across the season.

    Split the history in half by time, take the mean sonic target of each half,
    and report the dimensions that actually moved. We compare targets rather
    than loves here on purpose: this card is about the arc of the *whole*
    listening season, and loves are too sparse early on to make the two halves
    comparable.
    """
    ordered = sorted(records, key=lambda r: (r.created_at, r.playlist_id))
    if len(ordered) < MIN_STREAK_FORGES:
        return None

    mid = len(ordered) // 2
    early, late = ordered[:mid], ordered[mid:]
    a = _mean_sonic([r.sonic for r in early])
    b = _mean_sonic([r.sonic for r in late])
    if a is None or b is None:
        return None

    deltas = sorted(
        (
            (b_v - a_v, dim)
            for dim, a_v, b_v in zip(SONIC_DIMS, a.as_array(), b.as_array())
        ),
        key=lambda t: (-abs(t[0]), t[1]),
    )
    movers = [(d, dim) for d, dim in deltas if abs(d) >= STREAK_MIN_DELTA]

    span_days = (ordered[-1].created_at - ordered[0].created_at).total_seconds() / 86_400.0
    dominant = sorted(
        ((bk.n, rid) for rid, bk in buckets.items() if rid != SLACK_WATER.id),
        key=lambda t: (-t[0], t[1]),
    )
    dominant_name = REGIONS_BY_ID[dominant[0][1]].name if dominant else "nothing in particular"

    if not movers:
        headline = "You have not moved."
        body = (
            f"{len(ordered)} forges over {span_days:.0f} days and your centre of "
            f"mass has not shifted by more than {STREAK_MIN_DELTA:.2f} on any "
            f"axis. Mostly {dominant_name}. Consistency is a result."
        )
    else:
        d, dim = movers[0]
        low, high = _SONIC_WORDS[dim]
        direction = high if d > 0 else low
        headline = f"You have drifted {direction}."
        others = ", ".join(
            f"{dim2} {d2:+.2f}" for d2, dim2 in movers[1:3]
        )
        body = (
            f"Across {len(ordered)} forges and {span_days:.0f} days, {dim} has "
            f"moved {d:+.2f} between the first half of your history and the "
            f"second"
            + (f" ({others})." if others else ".")
            + f" The sky you forge under most is {dominant_name}."
        )

    return RetrospectiveCard(
        id="sky-streak",
        kind="sky_streak",
        headline=headline,
        body=body,
        sample_size=len(ordered),
        confidence=round(_confidence(len(ordered)), 4),
        signature=b,
        stats={dim: round(d, 4) for d, dim in deltas},
    )


def nudge_card(doc: NudgeDocument | None) -> RetrospectiveCard | None:
    """What the learner thinks it has learned. Optional, and only shown once
    the fit exists at all — a nudge of None is the common case and not a
    finding."""
    if doc is None or doc.is_empty:
        return None
    from .learning import explain_nudge  # local import: avoids a cycle at import time

    lines = explain_nudge(doc)
    if not lines:
        return None
    return RetrospectiveCard(
        id="the-lean",
        kind="learned_lean",
        headline="The Almanac has started bending toward you.",
        body=(
            f"Fitted on {doc.samples} signals. "
            + "; ".join(lines)
            + ". These are deltas on the house matrix, not replacements for it."
        ),
        sample_size=doc.samples,
        confidence=round(float(doc.diagnostics.confidence), 4),
        stats={"max_abs_coefficient": float(doc.diagnostics.max_abs_coefficient)},
    )


# =============================================================================
# Entry point
# =============================================================================


def build_retrospective(
    user_id: str,
    records: Sequence[ForgeRecord],
    events: Sequence[FeedbackEvent] = (),
    *,
    nudge: NudgeDocument | None = None,
    generated_at: datetime | None = None,
) -> Retrospective:
    """Assemble the user's retrospective.

    Deterministic given the same inputs and an explicit ``generated_at``.
    """
    stamp = generated_at or (
        max((r.created_at for r in records), default=None)
        or datetime.now(timezone.utc)
    )
    ordered = sorted(records, key=lambda r: (r.created_at, r.playlist_id))
    span = (
        (ordered[-1].created_at - ordered[0].created_at).total_seconds() / 86_400.0
        if len(ordered) > 1
        else 0.0
    )
    buckets = bucket_history(ordered, events)
    region_counts = {rid: b.n for rid, b in sorted(buckets.items()) if b.n}

    # ---- cold start ------------------------------------------------------
    # Say the small true thing. Do not extrapolate a personality; the user will
    # believe whatever we print, which is precisely the reason not to print it.
    if len(ordered) < COLD_START_FORGES:
        loves = sum(1 for e in events if e.is_love)
        if not ordered:
            headline = "Nothing on file yet."
            body = "Forge something. The Almanac starts paying attention immediately."
        else:
            named = [
                REGIONS_BY_ID[rid].name
                for rid in region_counts
                if rid != SLACK_WATER.id
            ]
            weather = _phrase(named) if named else "not much weather at all"
            headline = f"{len(ordered)} forges in. Too early to call it a taste."
            body = (
                f"So far: {weather}, and {loves} track{'s' if loves != 1 else ''} "
                f"you have kept. We need about {COLD_START_FORGES} forges before "
                "any of this means anything, and considerably more before we will "
                "tell you what your rain sound is. Ask again after some weather."
            )
        return Retrospective(
            user_id=user_id,
            generated_at=stamp,
            forges=len(ordered),
            signals=len(events),
            span_days=round(span, 2),
            cold_start=True,
            headline=headline,
            body=body,
            cards=[],
            region_counts=region_counts,
            notes=["cold start: fewer than %d forges on file" % COLD_START_FORGES],
        )

    # ---- the real thing --------------------------------------------------
    candidates: list[tuple[str, RetrospectiveCard | None]] = [
        ("rain_sound", rain_sound_card(buckets)),
        ("falling_barometer", falling_barometer_card(buckets)),
        ("first_frost", first_frost_card(buckets)),
        ("golden_hour", golden_hour_card(buckets)),
        ("most_loved_artists", most_loved_artists_card(events)),
        ("theme_signatures", theme_signature_card(ordered, events)),
        ("sky_streak", sky_streak_card(ordered, buckets)),
        ("learned_lean", nudge_card(nudge)),
    ]
    cards = [c for _, c in candidates if c is not None]
    notes = [
        f"no {kind} card: not enough forges in that sky yet"
        for kind, c in candidates
        if c is None and kind not in {"learned_lean"}
    ]
    if nudge is None:
        notes.append("no fitted lean yet: the learner wants more signals")

    loves = sum(1 for e in events if e.is_love)
    dominant = sorted(
        ((n, rid) for rid, n in region_counts.items() if rid != SLACK_WATER.id),
        key=lambda t: (-t[0], t[1]),
    )
    if dominant:
        dominant_name = REGIONS_BY_ID[dominant[0][1]].name
        top_n = dominant[0][0]
        # Only claim a dominant sky when one actually dominates. A four-way tie
        # reported as "mostly under the falling glass" is a small lie, and the
        # headline is the one line the user is guaranteed to read.
        contested = sum(1 for n, _ in dominant if n == top_n) > 1
        if contested:
            headline = (
                f"{len(ordered)} forges, spread evenly across {len(dominant)} skies."
            )
        else:
            headline = f"{len(ordered)} forges, mostly under {dominant_name}."
    else:
        headline = f"{len(ordered)} forges, and remarkably uneventful skies."

    body = (
        f"{len(ordered)} playlists over {span:.0f} days, {loves} tracks kept, "
        f"{len(events) - loves} let go. "
        + (
            f"{len(cards)} findings below."
            if cards
            else "Nothing yet rises to the level of a finding."
        )
    )

    return Retrospective(
        user_id=user_id,
        generated_at=stamp,
        forges=len(ordered),
        signals=len(events),
        span_days=round(span, 2),
        cold_start=False,
        headline=headline,
        body=body,
        cards=cards,
        region_counts=region_counts,
        notes=notes,
    )


async def retrospective_for(store: Any, user_id: str) -> Retrospective:
    """Convenience wrapper for a store that exposes ``records``/``feedback``.

    Typed loosely on purpose: the ``AlmanacStore`` protocol does not require
    these accessors, so this degrades to a history-only retrospective against
    any conforming store rather than demanding a richer one.
    """
    records: list[ForgeRecord]
    events: list[FeedbackEvent] = []
    if hasattr(store, "records"):
        records = list(await store.records(user_id))
    else:
        history = await store.history(user_id, limit=200)
        records = [ForgeRecord.from_playlist(p) for p in history]
    if hasattr(store, "feedback"):
        events = list(await store.feedback(user_id))

    doc: NudgeDocument | None = None
    if hasattr(store, "nudge_document"):
        doc = await store.nudge_document(user_id)

    return build_retrospective(user_id, records, events, nudge=doc)


__all__ = [
    "COLD_START_FORGES",
    "MIN_REGION_FORGES",
    "MIN_REGION_LOVES",
    "SkyRegion",
    "SKY_REGIONS",
    "SLACK_WATER",
    "REGIONS_BY_ID",
    "assign_region",
    "describe_sonic",
    "TrackHighlight",
    "RetrospectiveCard",
    "Retrospective",
    "bucket_history",
    "build_retrospective",
    "retrospective_for",
]
