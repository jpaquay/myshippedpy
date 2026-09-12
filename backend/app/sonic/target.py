"""The pipeline: sky -> transfer -> theme -> corridor -> taste -> target.

Four stages, applied in a fixed order, each one narrating what it did. The
order is not arbitrary and reversing any two of them changes the answer:

1. **Transfer.** The physics. Nine weather numbers become seven musical ones.
   This is the only stage that knows anything about the actual sky, so it goes
   first and everything after it is a modification of a real reading.
2. **Theme.** The narrative lens the user chose (or that we suggested). Pulls
   ``bias_weight`` of the way toward the theme's centre -- typically about a
   third, so today still outranks the story we are telling about today.
3. **Corridor.** The genre constraint. Applied *after* the theme so that a
   narrow corridor gets the last word on where in sonic space we are actually
   shopping. "Petrichor x drone" has to end up in drone territory or the
   crossing means nothing.
4. **Taste.** The user's own centroid, weighted by how much we actually know.
   Last, because it is a correction to a well-formed target rather than an
   input to one -- and because it is the stage most likely to be missing.

Every stage appends to a ``moves`` list in plain English with real numbers in
it. Those strings are not debug output; they go straight onto the hero card as
``Rationale.sonic_moves``, which is why they are written to be read by a person
who does not know what a transfer matrix is.
"""

from __future__ import annotations

import math
from typing import Sequence

from ..contracts import (
    SONIC_DIMS,
    GenreCorridor,
    SkyVector,
    SonicVector,
    TasteVector,
    Theme,
    clamp,
)
from .matrix import apply_transfer

__all__ = ["build_target", "TASTE_AUTHORITY", "TASTE_FULL_TRUST_SCROBBLES", "CORRIDOR_AUTHORITY"]


# ---------------------------------------------------------------------------
# Tuning constants, all in one place and all argued for
# ---------------------------------------------------------------------------

#: Hard ceiling on how far taste can drag the target, whatever the evidence.
#:
#: Capped at 0.45 because BAROGROOVE is a *weather* app. A user with 90,000
#: scrobbles and a tight centroid should absolutely bend the result toward
#: themselves -- but if taste were allowed past a half share, every sky would
#: converge on the same playlist and the product would quietly become "shuffle
#: with a barometer on the loading screen". The weather has to keep the casting
#: vote. This is a product decision expressed as a float.
TASTE_AUTHORITY: float = 0.45

#: Scrobbles required before we trust a centroid at full strength.
#:
#: Evidence ramps as ``sqrt(count / 500)``, not linearly and not logarithmically.
#: Linear is far too harsh (a real listener with 200 scrobbles gets 40% credit
#: when they deserve more); log is far too generous (50 scrobbles would buy 63%,
#: and 50 scrobbles is a fortnight of one album). The square root gives 200
#: scrobbles 63% and 50 scrobbles 32%, which matches how much those two samples
#: actually tell you about somebody.
TASTE_FULL_TRUST_SCROBBLES: int = 500

#: How hard a corridor pulls before the hard projection kicks in.
#:
#: The soft pull is ``(1 - width) * CORRIDOR_AUTHORITY``, so a narrow corridor
#: (drone, width 0.26) pulls at 0.44 and a broad one (indie rock, width 0.44)
#: pulls at 0.34. Deliberately gentle: the projection below is the mechanism
#: that actually *guarantees* the genre constraint, so this stage only has to
#: aim, not enforce.
CORRIDOR_AUTHORITY: float = 0.60


# ---------------------------------------------------------------------------
# Narration helpers
# ---------------------------------------------------------------------------

_HUMAN_DIM: dict[str, str] = {
    "valence": "valence",
    "energy": "energy",
    "tempo": "tempo",
    "acousticness": "acousticness",
    "density": "density",
    "grit": "grit",
    "spatiality": "reverb",
}


def _biggest_shifts(
    before: SonicVector, after: SonicVector, limit: int = 3, floor: float = 0.012
) -> list[str]:
    """The ``limit`` dims that moved most, phrased for a human.

    Tempo is reported in BPM because nobody has ever thought in normalised
    tempo, and a card that says "tempo 0.28" has failed at its only job.
    """
    a, b = before.as_dict(), after.as_dict()
    deltas = sorted(
        ((dim, b[dim] - a[dim]) for dim in SONIC_DIMS),
        key=lambda pair: (-abs(pair[1]), SONIC_DIMS.index(pair[0])),
    )
    out: list[str] = []
    for dim, delta in deltas[:limit]:
        if abs(delta) < floor:
            continue
        if dim == "tempo":
            out.append(f"tempo {before.tempo_bpm:.0f}->{after.tempo_bpm:.0f} BPM")
        else:
            out.append(f"{_HUMAN_DIM[dim]} {a[dim]:.2f}->{b[dim]:.2f}")
    return out


def _join(parts: list[str]) -> str:
    """Oxford-comma-free list join. Short, because these live on a card."""
    if not parts:
        return "nothing moved much"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _project_into_ball(point: SonicVector, anchor: SonicVector, radius: float) -> SonicVector:
    """Move ``point`` along the straight line to ``anchor`` until it is inside.

    :meth:`SonicVector.distance` is an RMS-normalised euclidean metric, so
    scaling every component of the offset by ``radius / distance`` scales the
    distance by exactly the same factor. One step, no iteration, no drift.
    """
    distance = point.distance(anchor)
    if distance <= radius or distance <= 1e-9:
        return point
    keep = radius / distance
    a, p = anchor.as_array(), point.as_array()
    return SonicVector.from_array([ai + (pi - ai) * keep for ai, pi in zip(a, p)])


def _taste_weight(taste: TasteVector) -> tuple[float, str]:
    """How much the user's centroid gets to move the target, and why.

    Three multiplicative gates, because thin taste data dragging the target to
    mush is the single most common way a personalisation feature makes a
    product worse:

    * **confidence** -- the oracle's own estimate of whether it built a
      meaningful centroid at all.
    * **evidence** -- ``sqrt(scrobbles / 500)``, capped at 1. Twelve scrobbles
      is not a taste profile, it is an accident.
    * **focus** -- ``1 - 0.4 * mean(spread)``. A user whose listening is spread
      evenly across the entire sonic space has a centroid that is arithmetically
      valid and semantically empty: it sits near 0.5 on every dim and pulling
      toward it is pulling toward beige. Wide spread costs up to 40% of the
      weight.

    Multiplied, then capped at :data:`TASTE_AUTHORITY`. A brand-new user comes
    out near zero and gets a pure theme-and-sky result, which is the right
    cold-start behaviour: it is a *good* playlist that simply is not about them
    yet, rather than a bad playlist that is.
    """
    evidence = min(1.0, math.sqrt(max(0, taste.scrobble_count) / TASTE_FULL_TRUST_SCROBBLES))
    spread_mean = sum(taste.spread.as_array()) / len(SONIC_DIMS)
    focus = clamp(1.0 - 0.4 * spread_mean, 0.0, 1.0)
    weight = clamp(TASTE_AUTHORITY * taste.confidence * evidence * focus, 0.0, TASTE_AUTHORITY)
    detail = (
        f"{taste.scrobble_count} scrobbles, confidence {taste.confidence:.2f}, "
        f"spread {spread_mean:.2f}"
    )
    return weight, detail


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def build_target(
    sky: SkyVector,
    *,
    theme: Theme,
    corridor: GenreCorridor,
    taste: TasteVector | None = None,
    nudge: Sequence[Sequence[float]] | None = None,
) -> tuple[SonicVector, list[str]]:
    """Compose the full target vector and narrate every stage.

    Returns ``(target, moves)``. ``moves`` is ordered, human-readable, and
    destined for :attr:`Rationale.sonic_moves` -- one line per stage, each
    naming what changed and by how much.

    ``taste=None`` is a first-class mode, not an error path: it is what an
    unpaired user gets, and it produces a complete, defensible result from the
    sky and the theme alone.
    """
    moves: list[str] = []

    # -- 1. the sky itself ---------------------------------------------------
    target = apply_transfer(sky, nudge=nudge)
    moves.append(
        f"Sky alone asks for {target.tempo_bpm:.0f} BPM, valence {target.valence:.2f}, "
        f"energy {target.energy:.2f}, reverb {target.spatiality:.2f}."
    )
    if nudge is not None:
        moves.append(
            "Your almanac correction is folded into the matrix -- these coefficients "
            "have been re-weighted by what you have loved and skipped."
        )

    # -- 2. the theme --------------------------------------------------------
    before = target
    target = target.blend(theme.bias, theme.bias_weight)
    shifts = _biggest_shifts(before, target)
    moves.append(
        f"{theme.name} pulls {theme.bias_weight:.0%} of the way to its own centre: "
        f"{_join(shifts)}."
    )

    # -- 3. the corridor -----------------------------------------------------
    if corridor.anchor is None or corridor.id == "any":
        moves.append("No genre corridor set, so the sky and your scrobbles have the floor.")
    else:
        before = target
        pull = clamp((1.0 - corridor.width) * CORRIDOR_AUTHORITY)
        target = target.blend(corridor.anchor, pull)
        target = _project_into_ball(target, corridor.anchor, corridor.width)
        shifts = _biggest_shifts(before, target)
        if shifts:
            moves.append(
                f"{corridor.name} is a corridor of width {corridor.width:.2f}, so the target "
                f"moves inside it: {_join(shifts)}."
            )
        else:
            moves.append(
                f"{corridor.name} already contained the target -- no correction needed."
            )

    # -- 4. taste ------------------------------------------------------------
    if taste is None:
        moves.append("No listening history in play: this one is pure sky and theme.")
    else:
        weight, detail = _taste_weight(taste)
        if weight < 0.02:
            moves.append(
                f"Your profile is too thin to lean on yet ({detail}), so it sits this one out."
            )
        else:
            before = target
            target = target.blend(taste.centroid, weight)
            shifts = _biggest_shifts(before, target)
            moves.append(
                f"Your own centre of gravity gets {weight:.0%} of the vote ({detail}): "
                f"{_join(shifts)}."
            )

    moves.append(
        f"Final target: {target.tempo_bpm:.0f} BPM, valence {target.valence:.2f}, "
        f"energy {target.energy:.2f}, acousticness {target.acousticness:.2f}, "
        f"reverb {target.spatiality:.2f}."
    )
    return target, moves
