"""Selection: turn a ranked list into a set of records that belong together.

A pure top-k of ``rerank`` output is always wrong, and predictably so. The
target is a single point in SonicVector space, the pool is large, and the
records nearest that point are near *each other* by construction. Top-k
therefore returns fourteen versions of the same song, all of them individually
excellent, collectively unlistenable.

The fix is Maximal Marginal Relevance: at each step pick the record that
maximises

    lambda * relevance  -  (1 - lambda) * (similarity to the closest record
                                           already selected)

so a candidate has to earn its place against the playlist as it stands, not
just against the target. This is a greedy approximation of a combinatorial
problem and that is fine; the exact solution is not worth the compute for
k <= 60.

Two hard constraints sit outside the MMR objective because they are rules
rather than preferences: no duplicate ``Track.key``, and no artist over
``settings.max_tracks_per_artist``.

Everything here is deterministic. Given the same pool and the same
``ForgeRequest.seed`` the output is byte-identical; the seed does not
introduce randomness, it only chooses among *ties*, of which there are many
because tag-derived vectors quantise hard.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, Mapping, Sequence

from ..contracts import ScoredTrack, SonicVector, Theme, clamp
from ..errors import DegradationLedger
from .candidates import Candidate
from .rerank import theme_dim_weights, weighted_distance

DIVERSITY_TUNING: dict[str, float] = {
    # THE TRADEOFF PARAMETER.
    # 1.0 = pure relevance (top-k, the failure mode described above).
    # 0.0 = pure dissimilarity (a playlist that is maximally spread out and
    #       has nothing to do with the weather).
    # 0.72 is where this lands after listening: relevance still clearly leads,
    # but a record that is a near-clone of one already picked has to be about
    # 0.10 better on score to displace a more distinct alternative. In practice
    # that swaps roughly a third of a top-k playlist, which is the amount of
    # variety a listener reads as "curated" rather than "random".
    "lambda": 0.72,
    # Hard floor on how close two selected records may sit in weighted sonic
    # space. Catches the pathological case MMR alone tolerates: two records
    # with identical tag sets, hence identical estimated vectors, hence
    # distance 0. Relaxed automatically if the pool cannot fill k.
    "min_separation": 0.045,
    # Only the top (k * horizon) reranked records are considered. Beyond that
    # the relevance term is so low that MMR would start selecting on
    # dissimilarity alone -- which is how you end up with a novelty track at
    # position 11. Also keeps selection O(k^2 * horizon) rather than O(k * n).
    "candidate_horizon": 8.0,
    # Absolute relevance floor. A record below this is not "diverse", it is
    # wrong, and no amount of distinctiveness redeems it.
    "relevance_floor": 0.18,
    # Magnitude of the seed-derived tie-break jitter. Four orders of magnitude
    # below a meaningful score difference, so it can only ever reorder records
    # that are genuinely indistinguishable.
    "tie_epsilon": 0.0001,
}


def vector_index(
    candidates: Iterable[Candidate],
) -> dict[str, SonicVector]:
    """Map ``Track.key`` -> estimated vector.

    ``ScoredTrack`` carries scalars, not the vector it was scored from, and
    most tag-derived estimates never make it onto ``Track.estimated``. Rather
    than widen a frozen contract, selection takes the index alongside.
    """
    return {c.key: c.estimated for c in candidates}


def _vector_for(
    st: ScoredTrack, index: Mapping[str, SonicVector]
) -> SonicVector:
    vec = index.get(st.track.key)
    if vec is not None:
        return vec
    if st.track.estimated is not None:
        return st.track.estimated
    return SonicVector.neutral()


def _jitter(key: str, seed: int | None) -> float:
    """Deterministic sub-noise tie-break in [0, tie_epsilon)."""
    if seed is None:
        return 0.0
    digest = hashlib.sha1(f"{seed}:{key}".encode("utf-8")).digest()
    unit = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return unit * DIVERSITY_TUNING["tie_epsilon"]


def _artist_key(st: ScoredTrack) -> str:
    return st.track.artist.strip().lower()


def _greedy_pass(
    pool: Sequence[ScoredTrack],
    *,
    k: int,
    index: Mapping[str, SonicVector],
    dim_weights: dict[str, float],
    max_per_artist: int,
    min_separation: float,
    relevance_floor: float,
    seed: int | None,
    preselected: Sequence[ScoredTrack] = (),
) -> list[ScoredTrack]:
    lam = DIVERSITY_TUNING["lambda"]

    chosen: list[ScoredTrack] = list(preselected)
    chosen_keys = {s.track.key for s in chosen}
    artist_counts: dict[str, int] = {}
    for s in chosen:
        artist_counts[_artist_key(s)] = artist_counts.get(_artist_key(s), 0) + 1
    chosen_vecs = [_vector_for(s, index) for s in chosen]

    remaining = [
        s
        for s in pool
        if s.track.key not in chosen_keys and s.score >= relevance_floor
    ]

    while len(chosen) < k and remaining:
        best: ScoredTrack | None = None
        best_val = float("-inf")
        best_i = -1

        for i, cand in enumerate(remaining):
            artist = _artist_key(cand)
            if artist_counts.get(artist, 0) >= max_per_artist:
                continue

            vec = _vector_for(cand, index)
            if chosen_vecs:
                nearest = min(
                    weighted_distance(vec, v, dim_weights) for v in chosen_vecs
                )
            else:
                nearest = 1.0

            if nearest < min_separation:
                continue

            similarity = 1.0 - nearest
            value = lam * cand.score - (1.0 - lam) * similarity
            value += _jitter(cand.track.key, seed)

            if value > best_val:
                best_val, best, best_i = value, cand, i

        if best is None:
            break

        chosen.append(best)
        chosen_keys.add(best.track.key)
        chosen_vecs.append(_vector_for(best, index))
        artist_counts[_artist_key(best)] = artist_counts.get(_artist_key(best), 0) + 1
        remaining.pop(best_i)

    return chosen


def select(
    scored: Sequence[ScoredTrack],
    *,
    k: int,
    index: Mapping[str, SonicVector] | None = None,
    theme: Theme | None = None,
    max_per_artist: int = 2,
    seed: int | None = None,
    ledger: DegradationLedger | None = None,
) -> list[ScoredTrack]:
    """Pick ``k`` records: relevant, distinct, deduped, artist-capped.

    Constraints are relaxed in a fixed order when the pool cannot fill ``k``,
    worst-first, each relaxation noted. Returning fewer tracks than asked is
    the last resort, not the first.
    """
    k = max(0, int(k))
    if k == 0 or not scored:
        return []

    index = index or {}
    dim_weights = theme_dim_weights(theme)
    max_per_artist = max(1, int(max_per_artist))

    # Dedupe by Track.key up front, keeping the best-scoring instance. rerank
    # already sorts best-first, so first-seen wins.
    seen: set[str] = set()
    deduped: list[ScoredTrack] = []
    for st in scored:
        if st.track.key in seen:
            continue
        seen.add(st.track.key)
        deduped.append(st)

    horizon = max(k * int(DIVERSITY_TUNING["candidate_horizon"]), k)
    pool = deduped[:horizon]

    chosen = _greedy_pass(
        pool,
        k=k,
        index=index,
        dim_weights=dim_weights,
        max_per_artist=max_per_artist,
        min_separation=DIVERSITY_TUNING["min_separation"],
        relevance_floor=DIVERSITY_TUNING["relevance_floor"],
        seed=seed,
    )

    # --- relaxation ladder ------------------------------------------------
    # 1. Widen the horizon before touching any constraint: the tail of the
    #    reranked list is a better source of tracks than a broken rule.
    if len(chosen) < k and len(deduped) > len(pool):
        chosen = _greedy_pass(
            deduped,
            k=k,
            index=index,
            dim_weights=dim_weights,
            max_per_artist=max_per_artist,
            min_separation=DIVERSITY_TUNING["min_separation"],
            relevance_floor=DIVERSITY_TUNING["relevance_floor"],
            seed=seed,
            preselected=chosen,
        )

    # 2. Drop the relevance floor. Mediocre beats absent.
    if len(chosen) < k:
        chosen = _greedy_pass(
            deduped,
            k=k,
            index=index,
            dim_weights=dim_weights,
            max_per_artist=max_per_artist,
            min_separation=DIVERSITY_TUNING["min_separation"],
            relevance_floor=0.0,
            seed=seed,
            preselected=chosen,
        )
        if len(chosen) >= k and ledger is not None:
            ledger.note("diversity", "relevance floor relaxed to fill the playlist")

    # 3. Drop the separation floor. The playlist gets repetitive but complete.
    if len(chosen) < k:
        before = len(chosen)
        chosen = _greedy_pass(
            deduped,
            k=k,
            index=index,
            dim_weights=dim_weights,
            max_per_artist=max_per_artist,
            min_separation=0.0,
            relevance_floor=0.0,
            seed=seed,
            preselected=chosen,
        )
        if len(chosen) > before and ledger is not None:
            ledger.note("diversity", "sonic separation floor relaxed; pool too narrow")

    # 4. Last: the artist cap. Loosened by one, never removed -- an eighteen
    #    track playlist by one artist is not a playlist, it is an album.
    if len(chosen) < k:
        before = len(chosen)
        chosen = _greedy_pass(
            deduped,
            k=k,
            index=index,
            dim_weights=dim_weights,
            max_per_artist=max_per_artist + 1,
            min_separation=0.0,
            relevance_floor=0.0,
            seed=seed,
            preselected=chosen,
        )
        if len(chosen) > before and ledger is not None:
            ledger.note(
                "diversity", f"artist cap raised to {max_per_artist + 1}; pool too narrow"
            )

    if len(chosen) < k and ledger is not None:
        ledger.note(
            "diversity", f"only {len(chosen)} of {k} requested tracks available"
        )

    return chosen


def spread_report(
    chosen: Sequence[ScoredTrack],
    *,
    index: Mapping[str, SonicVector] | None = None,
    theme: Theme | None = None,
) -> dict[str, float]:
    """Diagnostics: how spread out did we actually end up?

    Useful in tests and in the demo footer. ``mean_nearest`` below roughly
    0.05 means the lambda above is too high for this pool.
    """
    index = index or {}
    weights = theme_dim_weights(theme)
    vecs = [_vector_for(s, index) for s in chosen]
    if len(vecs) < 2:
        return {"mean_nearest": 0.0, "min_nearest": 0.0, "artists": float(len(chosen))}

    nearest: list[float] = []
    for i, v in enumerate(vecs):
        others = [weighted_distance(v, w, weights) for j, w in enumerate(vecs) if j != i]
        nearest.append(min(others))

    return {
        "mean_nearest": sum(nearest) / len(nearest),
        "min_nearest": min(nearest),
        "artists": float(len({_artist_key(s) for s in chosen})),
    }
