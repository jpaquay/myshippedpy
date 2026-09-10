"""Candidate pool assembly for THE FORGE.

Spotify's recommender is gone. There is no endpoint that will hand us "tracks
near this vector", so the pool has to come from somewhere with an actual graph
of taste -- Last.fm -- and every ranking decision has to happen on our side of
the wire. This module is the retrieval half of that arrangement. It is
deliberately dumb about quality: its only jobs are

  1. get *enough* plausible records into memory,
  2. make sure every single one of them carries a SonicVector so the reranker
     never has to special-case a missing estimate, and
  3. remember *where each record came from*, because the per-track ``why``
     is only convincing when it can say "two hops from Talk Talk" instead of
     "we thought you'd like it".

Retrieval runs in two phases and both are optional:

  PHASE 1 -- TASTE.  ``oracle.candidates(taste=...)`` expands the user's own
    listening through the similar-artist / similar-track graph. Skipped
    entirely when there is no usable taste profile.

  PHASE 2 -- THEME.  ``oracle.candidates(taste=empty, seed_tags=...)`` pulls
    tag charts for theme seed tags crossed with corridor tags. This phase runs
    *always*, not just as a fallback: a pool made only of the user's own
    neighbourhood produces a playlist with no weather in it, which is the one
    thing this product cannot ship.

THEME-ONLY MODE is therefore not a separate code path, it is simply what
happens when phase 1 contributes nothing -- no Last.fm user, an empty taste
vector, or an oracle that raised. A forge must never fail because Last.fm is
down; it degrades to "the sky and the theme know what they want" and says so
in the ledger.
"""

from __future__ import annotations

import inspect
from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import (
    AcousticOracle,
    GenreCorridor,
    SonicVector,
    TasteVector,
    Theme,
    Track,
)
from ..errors import DegradationLedger, OracleUnavailable

# --------------------------------------------------------------------------
# Tuning. One dict, all of it, commented. Nothing below reaches for a literal.
# --------------------------------------------------------------------------
POOL_TUNING: dict[str, float] = {
    # Fraction of the requested pool spent on the user's own taste graph.
    # 0.6 rather than 0.8: the taste graph is a comfortable rut, and a
    # weather engine that only ever returns your own neighbourhood is just a
    # shuffle button with a barometer glued to it.
    "taste_share": 0.60,
    # Fraction spent on theme/corridor tag charts. The two shares sum past 1.0
    # on purpose -- we over-fetch, then dedupe, and a bigger overlap between
    # the phases is a *signal* (that record is both on-theme and on-taste),
    # not waste.
    "theme_share": 0.55,
    # Theme seeds are issued in small chunks rather than one giant tag list,
    # because tag-chart endpoints collapse to their most popular tag when you
    # hand them fifteen at once. Three tags per call keeps the charts distinct.
    "seed_chunk": 3.0,
    # Hard ceiling on chunked calls so a wide theme x wide corridor cross does
    # not turn into forty round trips.
    "max_seed_calls": 6.0,
    # Below this many usable candidates we stop being fussy and keep records
    # we would otherwise drop (see `estimate_quality` floor below).
    "starvation_floor": 40.0,
    # Confidence in a track-level SonicVector supplied by the oracle.
    "quality_estimated": 1.00,
    # Confidence in a vector we derived ourselves from tags. Lower, honestly:
    # "post-punk" tells you a lot about grit and very little about valence.
    "quality_from_tags": 0.62,
    # Confidence in a neutral vector assigned to a record with nothing at all.
    # These are only admitted when the pool is starving, and the reranker
    # multiplies this straight into the score, so they sink.
    "quality_neutral": 0.15,
    # Tags below this many characters are junk ("uk", "00s"); they poison the
    # cross and the corridor fit alike.
    "min_tag_len": 3.0,
}

Provenance = Literal[
    "similar-artist",  # a record by an artist already in the user's top list
    "similar-track",   # graph-adjacent: shares tag ground with the taste profile
    "tag-chart",       # pulled from a theme/corridor tag chart
    "unknown",         # oracle gave us no way to tell
]

# Ordered best-to-worst. Used when the same record arrives from both phases:
# the taste-graph story is the more interesting one to tell in the `why`.
_PROVENANCE_RANK: dict[str, int] = {
    "similar-artist": 0,
    "similar-track": 1,
    "tag-chart": 2,
    "unknown": 3,
}


class Candidate(BaseModel):
    """A track plus everything retrieval learned about it on the way in.

    ``Track`` is frozen and has no provenance field, so provenance lives out
    here rather than being smuggled into ``tags``. The reranker consumes
    ``Candidate`` and emits ``ScoredTrack``; nothing downstream sees a raw
    dict.
    """

    model_config = ConfigDict(frozen=True)

    track: Track
    estimated: SonicVector
    provenance: Provenance = "unknown"
    provenance_detail: str = ""
    #: How much to trust ``estimated`` -- see POOL_TUNING quality_* entries.
    estimate_quality: float = POOL_TUNING["quality_from_tags"]
    #: Which of the requested seed tags this record actually matched.
    seed_tags_hit: tuple[str, ...] = ()
    #: Number of retrieval phases that surfaced this record. Two phases
    #: agreeing is weak but real evidence, and the reranker uses it.
    phases: int = 1

    @property
    def key(self) -> str:
        return self.track.key

    @property
    def tags(self) -> list[str]:
        return list(self.track.tags or ())


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


async def _maybe_await(value: Any) -> Any:
    """Tolerate an oracle that made a nominally-sync hook async."""
    if inspect.isawaitable(value):
        return await value
    return value


def _clean_tags(tags: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    floor = int(POOL_TUNING["min_tag_len"])
    for raw in tags or ():
        t = str(raw).strip().lower()
        if len(t) < floor or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def cross_seed_tags(theme: Theme, corridor: GenreCorridor) -> list[str]:
    """Interleave theme seeds with corridor tags.

    Interleave rather than concatenate: the chunker takes the first N, and a
    concatenated list would spend every call on the theme and never reach the
    corridor. Interleaving means chunk 1 is already a theme x corridor cross,
    which is exactly the intersection we want the chart to be about.
    """
    theme_tags = _clean_tags(theme.seed_tags)
    corridor_tags = _clean_tags(corridor.tags)
    woven: list[str] = []
    seen: set[str] = set()
    for i in range(max(len(theme_tags), len(corridor_tags))):
        for source in (theme_tags, corridor_tags):
            if i < len(source) and source[i] not in seen:
                seen.add(source[i])
                woven.append(source[i])
    return woven


def _chunks(items: Sequence[str], size: int) -> list[list[str]]:
    size = max(1, size)
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _taste_is_usable(taste: TasteVector | None) -> bool:
    if taste is None:
        return False
    if taste.confidence <= 0.0:
        return False
    return bool(taste.top_tags or taste.top_artists)


def _strongest_shared_tag(track_tags: Sequence[str], top_tags: dict[str, float]) -> tuple[str, float]:
    best, best_w = "", 0.0
    for t in track_tags:
        w = float(top_tags.get(t, 0.0))
        if w > best_w:
            best, best_w = t, w
    return best, best_w


def _classify_taste_provenance(
    track: Track, taste: TasteVector
) -> tuple[Provenance, str]:
    """Work out how a taste-phase record relates to the user, and say it plainly.

    The oracle hands back a flat ``list[Track]`` with no provenance channel, so
    we reconstruct it. This is honest rather than decorative: everything in the
    taste phase was seeded from the user's own top artists, so a record by an
    artist we already know is one hop, and a record that merely shares tag
    ground is two. That is a true statement about the retrieval graph, not a
    guess about the music.
    """
    tags = _clean_tags(track.tags)
    artists = {a.lower() for a in taste.top_artists}
    if track.artist.lower() in artists:
        return "similar-artist", f"straight out of your {track.artist} listening"

    tag, weight = _strongest_shared_tag(tags, taste.top_tags)
    if tag and weight > 0.0:
        anchor = taste.top_artists[0] if taste.top_artists else ""
        if anchor:
            return "similar-track", f"two hops from {anchor} via {tag}"
        return "similar-track", f"adjacent to your {tag} listening"

    if taste.top_artists:
        return "similar-track", f"two hops from {taste.top_artists[0]}"
    return "unknown", "in the neighbourhood"


def _tag_chart_detail(hit: Sequence[str], theme: Theme) -> str:
    if hit:
        return f"off the {hit[0]} chart"
    return f"seeded by {theme.name}"


# --------------------------------------------------------------------------
# estimate backfill
# --------------------------------------------------------------------------


async def ensure_estimate(
    oracle: AcousticOracle,
    track: Track,
    *,
    allow_neutral: bool = False,
) -> tuple[SonicVector, float] | None:
    """Guarantee a vector for one track, or report that there is nothing to work with.

    Order of preference: the oracle's own track-level estimate, then a vector
    derived purely from tags, then -- only under starvation -- neutral.

    Note what is *not* here: ``oracle.estimate(track)``. That hook exists and
    is async because it costs a network round trip per track, and a 400-record
    pool would mean 400 of them. Retrieval stays offline-shaped by design; the
    engine can enrich a handful of finalists later if it wants to.
    """
    if track.estimated is not None:
        return track.estimated, POOL_TUNING["quality_estimated"]

    tags = _clean_tags(track.tags)
    if tags:
        try:
            vec = await _maybe_await(oracle.estimate_from_tags(tags))
        except Exception:  # noqa: BLE001 - a bad tag must not kill the pool
            vec = None
        if isinstance(vec, SonicVector):
            return vec, POOL_TUNING["quality_from_tags"]

    if allow_neutral:
        return SonicVector.neutral(), POOL_TUNING["quality_neutral"]
    return None


# --------------------------------------------------------------------------
# the pool
# --------------------------------------------------------------------------


def _merge(existing: Candidate, incoming: Candidate) -> Candidate:
    """Fold a duplicate into the record we already hold.

    Keep the better estimate, the better provenance story, the union of seed
    hits, and bump the phase count -- a record both phases found is genuinely
    more interesting than one either found alone.
    """
    better_estimate = incoming.estimate_quality > existing.estimate_quality
    better_prov = _PROVENANCE_RANK[incoming.provenance] < _PROVENANCE_RANK[existing.provenance]
    return Candidate(
        track=incoming.track if better_estimate else existing.track,
        estimated=incoming.estimated if better_estimate else existing.estimated,
        estimate_quality=max(existing.estimate_quality, incoming.estimate_quality),
        provenance=incoming.provenance if better_prov else existing.provenance,
        provenance_detail=incoming.provenance_detail if better_prov else existing.provenance_detail,
        seed_tags_hit=tuple(dict.fromkeys(existing.seed_tags_hit + incoming.seed_tags_hit)),
        phases=existing.phases + 1,
    )


async def _call_oracle(
    oracle: AcousticOracle,
    *,
    taste: TasteVector,
    seed_tags: Sequence[str],
    corridor: GenreCorridor,
    limit: int,
) -> list[Track]:
    tracks = await oracle.candidates(
        taste=taste, seed_tags=list(seed_tags), corridor=corridor, limit=limit
    )
    return [t for t in (tracks or []) if isinstance(t, Track)]


async def gather_candidates(
    *,
    oracle: AcousticOracle,
    theme: Theme,
    corridor: GenreCorridor,
    taste: TasteVector | None = None,
    limit: int = 400,
    ledger: DegradationLedger | None = None,
) -> list[Candidate]:
    """Assemble the candidate pool. Never raises; degrades and notes instead."""

    limit = max(20, int(limit))
    pool: dict[str, Candidate] = {}
    taste_vec = taste if taste is not None else TasteVector.empty()

    # ---- PHASE 1: the taste graph -------------------------------------
    taste_tracks: list[Track] = []
    if _taste_is_usable(taste_vec):
        want = max(10, int(limit * POOL_TUNING["taste_share"]))
        try:
            taste_tracks = await _call_oracle(
                oracle,
                taste=taste_vec,
                seed_tags=_clean_tags(theme.seed_tags),
                corridor=corridor,
                limit=want,
            )
        except (OracleUnavailable, Exception) as exc:  # noqa: BLE001
            if ledger is not None:
                ledger.note("candidates", f"taste-graph retrieval failed ({exc}); theme-only")
            taste_tracks = []
    elif ledger is not None and taste is not None and taste.source != "empty":
        ledger.note("candidates", "taste profile too thin to seed retrieval; theme-only")

    for track in taste_tracks:
        prov, detail = _classify_taste_provenance(track, taste_vec)
        filled = await ensure_estimate(oracle, track)
        if filled is None:
            continue
        vec, quality = filled
        cand = Candidate(
            track=track,
            estimated=vec,
            estimate_quality=quality,
            provenance=prov,
            provenance_detail=detail,
        )
        pool[cand.key] = _merge(pool[cand.key], cand) if cand.key in pool else cand

    # ---- PHASE 2: theme x corridor tag charts --------------------------
    woven = cross_seed_tags(theme, corridor)
    if not woven:
        # A theme with no seeds and the "any" corridor. Ask for the theme name
        # itself rather than nothing -- some tag graphs will actually resolve it.
        woven = _clean_tags([theme.id.replace("-", " "), theme.name])

    chunks = _chunks(woven, int(POOL_TUNING["seed_chunk"]))[: int(POOL_TUNING["max_seed_calls"])]
    per_call = max(8, int(limit * POOL_TUNING["theme_share"] / max(1, len(chunks))))

    theme_failures = 0
    for chunk in chunks:
        try:
            tracks = await _call_oracle(
                oracle,
                taste=TasteVector.empty(),
                seed_tags=chunk,
                corridor=corridor,
                limit=per_call,
            )
        except Exception as exc:  # noqa: BLE001 - one bad chart is not fatal
            theme_failures += 1
            if theme_failures == 1 and ledger is not None:
                ledger.note("candidates", f"tag-chart retrieval failed ({exc})")
            continue

        chunk_set = set(chunk)
        for track in tracks:
            tags = _clean_tags(track.tags)
            hit = tuple(t for t in tags if t in chunk_set)
            filled = await ensure_estimate(oracle, track)
            if filled is None:
                continue
            vec, quality = filled
            cand = Candidate(
                track=track,
                estimated=vec,
                estimate_quality=quality,
                provenance="tag-chart",
                provenance_detail=_tag_chart_detail(hit or chunk, theme),
                seed_tags_hit=hit or tuple(chunk[:1]),
            )
            pool[cand.key] = _merge(pool[cand.key], cand) if cand.key in pool else cand

    # ---- starvation pass ------------------------------------------------
    # Only now, with both phases counted, do we decide whether to admit the
    # records we dropped for having neither an estimate nor a usable tag.
    if len(pool) < POOL_TUNING["starvation_floor"]:
        rescued = 0
        for track in taste_tracks:
            if track.key in pool:
                continue
            filled = await ensure_estimate(oracle, track, allow_neutral=True)
            if filled is None:
                continue
            vec, quality = filled
            prov, detail = _classify_taste_provenance(track, taste_vec)
            pool[track.key] = Candidate(
                track=track,
                estimated=vec,
                estimate_quality=quality,
                provenance=prov,
                provenance_detail=detail,
            )
            rescued += 1
        if ledger is not None:
            if rescued:
                ledger.note(
                    "candidates",
                    f"pool thin ({len(pool)}); admitted {rescued} records on neutral estimates",
                )
            elif len(pool) < POOL_TUNING["starvation_floor"]:
                ledger.note("candidates", f"thin candidate pool ({len(pool)} records)")

    if not pool and ledger is not None:
        ledger.note("candidates", "candidate pool empty; oracle returned nothing usable")

    # Deterministic order out. The reranker sorts by score, but ties are
    # common with tag-derived vectors and an unstable pool order would make
    # seeded runs non-reproducible.
    return sorted(pool.values(), key=lambda c: c.key)
