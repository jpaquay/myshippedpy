"""Arc shaping. A playlist is a shape, not a bag.

Selection gives us the right eighteen records. It says nothing about the order,
and order is most of what a listener experiences. Eighteen correct records in
descending-score order is a playlist that peaks at track one and dies.

So the sequence gets an *intensity curve*, and -- this is the conceit of the
whole product -- the curve is chosen by the sky. The same eighteen records
ordered for a collapsing barometer and ordered for a building ridge are two
different listening experiences, which is the honest musical consequence of
the claim that weather's signal lives in the derivative.

SHAPES IMPLEMENTED
------------------
Each is a set of control points over (position fraction, intensity),
piecewise-linearly interpolated. Data, not code, so a new shape is four
numbers rather than a new function.

``collapse``  Falling glass. Peak at 24% and then a long, unhurried descent to
              the quietest close of any shape. This is what a dropping
              barometer feels like: the energy is spent early and the rest of
              the afternoon is a slow leak. The mandated falling-glass shape.
``ridge``     Rising glass. A near-monotone climb to a peak at 80%, closing
              only slightly below it. High pressure builds; so does the
              playlist. The mandated rising shape.
``plateau``   Flat glass, unchanging overcast. A wide mid-level body with one
              deliberate lift at 62% and a gentle settle. The mandated
              flat-grey shape: nothing happens, once.
``gloaming``  Golden hour. A patient rise whose peak is placed *on* the light
              rather than on the middle of the playlist, then a short warm
              descent into an unusually long, quiet tail. Sunset does not
              fade symmetrically and neither does this.
``squall``    Wind and incoming weather. Two peaks (38% and 79%) with a real
              trough between them. Turbulence is not one loud passage, it is
              a front arriving twice.

HOW THE SKY CHOOSES
-------------------
Each shape scores itself against the SkyVector; the best score wins. The
dominant terms are ``pressure_trend_6h`` (which separates collapse / plateau /
ridge) and ``golden_hour_proximity`` (which lets ``gloaming`` override a mild
trend, because forty minutes before sunset is a stronger signal than a 2 hPa
drift). ``wind_energy`` and ``precipitation`` gate ``squall``, which needs a
genuinely disturbed sky to beat the pressure-driven shapes.

Golden hour also *modulates* whichever shape wins: the peak slides toward the
position in the playlist where the light will be. A collapsing barometer close
to sunset still gets its early peak, just a little later than it otherwise
would.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from ..contracts import ScoredTrack, SkyVector, SonicVector, TrackRole, clamp

# ---------------------------------------------------------------------------
# TUNING
# ---------------------------------------------------------------------------
ARC_TUNING: dict[str, float] = {
    # |pressure_trend_6h| below this reads as "the glass is not moving".
    # 0.18 rather than 0.05: barometers wobble, and a 2 hPa drift over six
    # hours is noise, not a front.
    "flat_band": 0.18,
    # golden_hour_proximity above this lets `gloaming` outrank a pressure
    # shape outright.
    "golden_override": 0.62,
    # How far golden hour may slide a non-gloaming shape's peak, as a fraction
    # of the playlist. Small: this is a nudge, not a takeover.
    "golden_peak_pull": 0.16,
    # Disturbance (wind, precip) needed before `squall` is competitive.
    "squall_gate": 0.58,
    # Curve deltas smaller than this are "flat", and the slots involved are
    # labelled `body` rather than build/descent. Without it a plateau reads as
    # sixteen consecutive `build` tracks, which is a lie about the shape.
    "flat_eps": 0.035,
    # Intensity tolerance for the opener/closer quality swap. A swap must stay
    # within this much intensity of what the curve asked for.
    "endpoint_tolerance": 0.10,
    # Score improvement required to justify such a swap.
    "endpoint_score_gain": 0.03,
}

# What "intensity" means when ranking a record against the curve.
# Valence is deliberately absent: a devastating slow song is not a low point in
# a playlist, it is often the peak. Intensity is about physical weight --
# loudness, motion, how much air the record moves -- not about mood.
INTENSITY_MIX: dict[str, float] = {
    "energy": 0.46,   # the definition, more or less
    "tempo": 0.28,    # the second-order driver of perceived drive
    "density": 0.16,  # how much is happening at once
    "grit": 0.10,     # texture reads as weight, but faintly
}


class ArcShape(BaseModel):
    """A named intensity curve over normalised playlist position."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str
    #: (position_fraction, intensity) control points, ascending by position.
    #: Must span 0.0 and 1.0.
    control_points: tuple[tuple[float, float], ...]

    @property
    def peak_at(self) -> float:
        return max(self.control_points, key=lambda p: p[1])[0]


ARC_SHAPES: dict[str, ArcShape] = {
    "collapse": ArcShape(
        id="collapse",
        name="Collapse",
        description="Early peak, then a long unhurried descent. Falling glass.",
        control_points=((0.0, 0.46), (0.24, 0.86), (0.55, 0.52), (0.82, 0.30), (1.0, 0.16)),
    ),
    "ridge": ArcShape(
        id="ridge",
        name="Ridge",
        description="A near-monotone climb, closing just under the peak. Rising glass.",
        control_points=((0.0, 0.24), (0.35, 0.48), (0.62, 0.70), (0.80, 0.92), (1.0, 0.78)),
    ),
    "plateau": ArcShape(
        id="plateau",
        name="Plateau",
        description="A wide mid-level body with one lift, then a settle. Flat glass.",
        control_points=((0.0, 0.40), (0.22, 0.50), (0.50, 0.52), (0.62, 0.80), (0.80, 0.55), (1.0, 0.38)),
    ),
    "gloaming": ArcShape(
        id="gloaming",
        name="Gloaming",
        description="Patient rise to a peak on the light, then a long quiet tail.",
        control_points=((0.0, 0.30), (0.30, 0.48), (0.58, 0.72), (0.70, 0.84), (0.86, 0.42), (1.0, 0.20)),
    ),
    "squall": ArcShape(
        id="squall",
        name="Squall",
        description="Two fronts: a peak, a real trough, a second higher peak.",
        control_points=((0.0, 0.44), (0.38, 0.84), (0.58, 0.40), (0.79, 0.90), (1.0, 0.46)),
    ),
}


# ---------------------------------------------------------------------------
# curve machinery
# ---------------------------------------------------------------------------


def _sky(sky: SkyVector, dim: str, default: float) -> float:
    """Read a sky dim defensively.

    ``pressure_trend_6h`` and ``golden_hour_proximity`` are load-bearing and
    guaranteed by the contract; the rest of the nine are read through here so
    that a change in the extractor's dim set degrades the arc rather than
    crashing the forge.
    """
    value = getattr(sky, dim, None)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def sample_curve(shape: ArcShape, n: int, *, peak_shift: float = 0.0) -> list[float]:
    """Sample the shape at ``n`` evenly spaced positions.

    ``peak_shift`` slides every interior control point by that fraction,
    keeping the endpoints pinned. That is how golden hour bends a shape it did
    not win.
    """
    if n <= 0:
        return []
    if n == 1:
        return [shape.control_points[0][1]]

    points = list(shape.control_points)
    if peak_shift:
        shifted: list[tuple[float, float]] = []
        for pos, val in points:
            if 0.0 < pos < 1.0:
                pos = clamp(pos + peak_shift, 0.02, 0.98)
            shifted.append((pos, val))
        points = sorted(shifted, key=lambda p: p[0])

    out: list[float] = []
    for i in range(n):
        t = i / (n - 1)
        if t <= points[0][0]:
            out.append(points[0][1])
            continue
        if t >= points[-1][0]:
            out.append(points[-1][1])
            continue
        for (p0, v0), (p1, v1) in zip(points, points[1:]):
            if p0 <= t <= p1:
                span = p1 - p0
                frac = 0.0 if span <= 0 else (t - p0) / span
                out.append(v0 + (v1 - v0) * frac)
                break
        else:  # pragma: no cover - control points always span [0,1]
            out.append(points[-1][1])
    return out


# ---------------------------------------------------------------------------
# shape selection
# ---------------------------------------------------------------------------


def score_shapes(sky: SkyVector) -> dict[str, float]:
    """Score every shape against the sky. Exposed for tests and the demo."""
    trend = _sky(sky, "pressure_trend_6h", 0.0)
    golden = _sky(sky, "golden_hour_proximity", 0.0)
    wind = _sky(sky, "wind_energy", 0.3)
    precip = _sky(sky, "precipitation", 0.0)
    flat_band = ARC_TUNING["flat_band"]

    disturbance = clamp(0.65 * wind + 0.35 * precip)

    return {
        # Falling glass. Linear in how hard it is falling.
        "collapse": clamp(-trend),
        # Rising glass, symmetric.
        "ridge": clamp(trend),
        # Steady glass. Full marks at dead flat, zero once past the band.
        "plateau": clamp(1.0 - abs(trend) / max(1e-6, flat_band)) * 0.92,
        # Golden hour. Scaled so it needs to be genuinely close to sunset to
        # beat a moving barometer, but wins outright when it is.
        "gloaming": clamp(golden / max(1e-6, ARC_TUNING["golden_override"])) * 0.98,
        # Disturbance, gated: below the gate it contributes nothing at all,
        # above it it ramps fast.
        "squall": clamp(
            (disturbance - ARC_TUNING["squall_gate"]) / max(1e-6, 1.0 - ARC_TUNING["squall_gate"])
        ),
    }


def choose_shape(sky: SkyVector) -> tuple[ArcShape, str]:
    """Pick the arc shape and say, in one sentence, why."""
    scores = score_shapes(sky)
    # Sorted by score then id: ties resolve identically on every run.
    best_id = min(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    shape = ARC_SHAPES[best_id]

    trend = _sky(sky, "pressure_trend_6h", 0.0)
    golden = _sky(sky, "golden_hour_proximity", 0.0)
    hpa = trend * 12.0  # the extractor normalises roughly +/-12 hPa onto +/-1

    reasons = {
        "collapse": f"Glass down {abs(hpa):.0f} hPa: peak early, then let it fall away.",
        "ridge": f"Glass up {abs(hpa):.0f} hPa: build the whole way, peak late.",
        "plateau": "Glass unmoving: hold a level and lift once.",
        "gloaming": f"Golden hour at {golden:.2f}: put the peak on the light.",
        "squall": "Wind and weather incoming: two fronts, not one.",
    }
    return shape, reasons[best_id]


def peak_shift_for(sky: SkyVector, shape: ArcShape) -> float:
    """How far golden hour drags a shape's peak.

    ``gloaming`` already puts its peak on the light, so it is exempt. For the
    others: the closer to sunset, the later the peak should land, because the
    listener's own attention is being pulled to a moment that has not happened
    yet.
    """
    if shape.id == "gloaming":
        return 0.0
    golden = _sky(sky, "golden_hour_proximity", 0.0)
    if golden <= 0.25:
        return 0.0
    return ARC_TUNING["golden_peak_pull"] * clamp((golden - 0.25) / 0.75)


# ---------------------------------------------------------------------------
# intensity + assignment
# ---------------------------------------------------------------------------


def _vector_for(st: ScoredTrack, index: Mapping[str, SonicVector] | None) -> SonicVector:
    if index:
        vec = index.get(st.track.key)
        if vec is not None:
            return vec
    if st.track.estimated is not None:
        return st.track.estimated
    return SonicVector.neutral()


def track_intensity(st: ScoredTrack, index: Mapping[str, SonicVector] | None = None) -> float:
    vec = _vector_for(st, index)
    total = sum(INTENSITY_MIX.values())
    acc = sum(w * getattr(vec, dim, 0.5) for dim, w in INTENSITY_MIX.items())
    return clamp(acc / total)


def replace_scored(st: ScoredTrack, **updates: Any) -> ScoredTrack:
    """Rebuild a frozen ScoredTrack with new fields.

    ``model_copy`` on pydantic v2; the fallback keeps this working if the
    contract ever ships ScoredTrack as a frozen dataclass instead.
    """
    copier = getattr(st, "model_copy", None)
    if callable(copier):
        return copier(update=updates)
    import dataclasses  # pragma: no cover - dataclass fallback

    return dataclasses.replace(st, **updates)  # pragma: no cover


def _assign_roles(curve: Sequence[float]) -> list[TrackRole]:
    """Label each slot from the curve alone.

    Guarantees exactly one ``opener`` (slot 0), exactly one ``closer`` (last
    slot) and exactly one ``peak`` (the highest interior slot, earliest on a
    tie -- a double-peaked squall gets one nominal peak and the second reads
    as a build, which is the correct description of what a listener hears).
    """
    n = len(curve)
    if n == 0:
        return []
    if n == 1:
        return ["opener"]
    if n == 2:
        return ["opener", "closer"]

    interior = range(1, n - 1)
    peak_i = min(interior, key=lambda i: (-curve[i], i))

    eps = ARC_TUNING["flat_eps"]
    roles: list[TrackRole] = []
    for i in range(n):
        if i == 0:
            roles.append("opener")
        elif i == n - 1:
            roles.append("closer")
        elif i == peak_i:
            roles.append("peak")
        else:
            delta = curve[i] - curve[i - 1]
            if abs(delta) < eps:
                roles.append("body")
            elif i < peak_i:
                roles.append("build")
            else:
                roles.append("descent")
    return roles


def _endpoint_polish(
    ordered: list[ScoredTrack],
    intensities: list[float],
    curve: Sequence[float],
) -> list[ScoredTrack]:
    """Let the opener and closer be the best record that still fits the curve.

    Sort-matching optimises the whole sequence and is indifferent about which
    of two near-identical records lands at slot 0. A listener is not: the first
    and last tracks are the two a playlist is judged on. So for those two slots
    only, swap in a materially better-scoring record if it stays within
    tolerance of the intensity the curve asked for.
    """
    n = len(ordered)
    if n < 3:
        return ordered

    tol = ARC_TUNING["endpoint_tolerance"]
    gain = ARC_TUNING["endpoint_score_gain"]

    for slot in (0, n - 1):
        want = curve[slot]
        current = ordered[slot]
        best_i = slot
        best_score = current.score
        for i in range(1, n - 1):
            if i == slot:
                continue
            if abs(intensities[i] - want) > tol:
                continue
            if ordered[i].score > best_score + gain:
                best_i, best_score = i, ordered[i].score
        if best_i != slot:
            ordered[slot], ordered[best_i] = ordered[best_i], ordered[slot]
            intensities[slot], intensities[best_i] = intensities[best_i], intensities[slot]
    return ordered


def shape_playlist(
    chosen: Sequence[ScoredTrack],
    *,
    sky: SkyVector,
    index: Mapping[str, SonicVector] | None = None,
) -> tuple[list[ScoredTrack], ArcShape, str]:
    """Order and label the selected tracks. Returns (tracks, shape, reason)."""
    tracks = list(chosen)
    shape, reason = choose_shape(sky)
    if not tracks:
        return [], shape, reason

    n = len(tracks)
    curve = sample_curve(shape, n, peak_shift=peak_shift_for(sky, shape))

    # ASSIGNMENT.
    # Sorting both sides and pairing them in order is not a heuristic: for a
    # one-dimensional cost like sum|desired - actual| it is the optimal
    # assignment (any crossing pair can be uncrossed without increasing the
    # cost -- the rearrangement inequality). So no search is needed.
    order = sorted(
        range(n),
        key=lambda i: (track_intensity(tracks[i], index), tracks[i].track.key),
    )
    slots = sorted(range(n), key=lambda i: (curve[i], i))

    placed: list[ScoredTrack | None] = [None] * n
    for rank, slot in enumerate(slots):
        placed[slot] = tracks[order[rank]]
    ordered = [t for t in placed if t is not None]

    intensities = [track_intensity(t, index) for t in ordered]
    ordered = _endpoint_polish(ordered, intensities, curve)

    roles = _assign_roles(curve)
    return (
        [
            replace_scored(t, role=roles[i], position=i)
            for i, t in enumerate(ordered)
        ],
        shape,
        reason,
    )


def describe_arc(shape: ArcShape, tracks: Sequence[ScoredTrack]) -> list[str]:
    """Human-readable arc notes, for the rationale and the demo footer."""
    if not tracks:
        return []
    n = len(tracks)
    curve = sample_curve(shape, n)
    peak_i = max(range(n), key=lambda i: curve[i])
    return [
        f"Arc: {shape.name.lower()} \u2014 {shape.description}",
        f"Peak at track {peak_i + 1} of {n}.",
    ]
