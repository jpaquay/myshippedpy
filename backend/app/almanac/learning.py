"""Per-user ridge regression from feedback to a 9x7 transfer-matrix nudge.

Pure Python. No numpy. Deterministic: identical inputs produce a byte-identical
document, including its timestamp.

------------------------------------------------------------------------------
THE DERIVATION: how a love becomes a matrix delta
------------------------------------------------------------------------------

The engine is, to the part we are allowed to touch, linear:

    sonic_target  t  =  M^T x                      (9 sky dims -> 7 sonic dims)

where ``x`` is the SkyVector and ``M`` is the base transfer matrix, indexed
``M[sky_dim][sonic_dim]``. ``apply_transfer`` wraps this in squashing and
clamping, so the relationship is only locally linear. That is fine, and it is
worth being precise about why: we are not re-fitting ``M``, we are fitting a
small additive ``ΔM``, and the error of linearising a smooth squash over a
perturbation bounded by 0.08 per cell is second-order. The nudge is small
enough that the linear model of it is accurate *because* the nudge is small.

Step 1 — what does one piece of feedback assert?
................................................

For a single feedback event we hold three things, all captured at the moment
the user acted (see ``models.FeedbackEvent`` on why we snapshot rather than
re-join):

    x  the sky reading the playlist was forged from        (9-vector)
    t  the sonic target the engine derived from x          (7-vector)
    s  the estimated sonic vector of the track acted on    (7-vector)

A LOVE on ``s`` is a statement about ``t``: *given this sky, you aimed here and
I wanted that*. It does not say the target should have been ``s`` — ``s`` is
one draw from the distribution the target defines, and a playlist that
collapses onto a single loved track is a worse playlist. It says the target
should have been *nearer* ``s``. So the asserted correction in output space is
a fractional step along the residual:

    d = +LOVE_STEP * (s - t)                                       [love]

A SKIP is the same statement with the sign flipped: the target should have been
*further* from ``s``.

    d = -SKIP_STEP * (s - t)                                       [skip]

Two asymmetries are deliberate.

  * ``SKIP_STEP < LOVE_STEP``. A love is an act; a skip is ambient. People skip
    tracks they like because they heard it yesterday, because the phone rang,
    because they are four tracks in and leaving. A love is comparatively hard
    to produce by accident. Weighting them equally lets noise outvote taste.
  * A love points somewhere; a skip only points away. ``-(s - t)`` is a valid
    first-order direction but it has no destination, so we take a shorter step
    and cap the per-example magnitude (``MAX_EXAMPLE_DELTA``) to stop one
    pathologically distant track from swinging the fit.

Step 2 — from a desired output change to a matrix change
........................................................

We now have a supervised set: for each event, input ``x`` (9 features) and
desired change in output ``d`` (7 targets). A perturbation ``ΔM`` changes the
output by

    Δt = ΔM^T x

so we want the ``ΔM`` that best explains the corrections the user has been
asking for:

    minimise   Σ_k w_k ‖ ΔM^T x_k − d_k ‖²  +  λ ‖ΔM‖²

Because ``ΔM^T x`` treats each output column independently, this decomposes
exactly into **seven independent 9-dimensional ridge regressions** — one per
sonic dimension — sharing the same design matrix. Stacking the seven solution
vectors as columns gives a 9x7 matrix, which is precisely the shape the nudge
must be. The shapes are not a coincidence; they are the same object.

In closed form, with ``X`` the (n x 9) design matrix and ``Y`` the (n x 7)
target matrix, both row-scaled by ``sqrt(w_k)``:

    ΔM = (Xᵀ X + λ I)⁻¹ Xᵀ Y

Step 3 — what we deliberately do not model
..........................................

*No intercept.* The nudge is structurally 9x7 and has nowhere to put a
constant. A user who simply likes everything darker regardless of sky cannot be
represented, and their preference will smear across whichever sky dimensions
are most reliably non-zero (the unsigned ones — ``cloud_depth``,
``precip_intensity`` — act as a partial pseudo-intercept). This is an accepted
limitation, not an oversight: a constant offset is a *taste*, and taste belongs
in the scorer's affinity term, not in the weather-to-music transfer. The nudge
is only ever allowed to say "when the sky does *this*, lean *that* way".

*No feature standardisation.* Ridge is scale-sensitive, but every sky dimension
already lives in [-1,1] or [0,1], so they are commensurate. Standardising would
make ``λ`` and the clamp bound harder to reason about for no accuracy gained.

*Null model is zero.* We are predicting a correction, so the honest baseline is
"no correction needed". R² is therefore reported uncentred, against
``Σ y²`` rather than ``Σ (y − ȳ)²``.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Sequence

from ..contracts import SKY_DIMS, SONIC_DIMS
from .models import (
    MATRIX_VERSION,
    SKY_N,
    SONIC_N,
    FeedbackEvent,
    ForgeRecord,
    NudgeDiagnostics,
    NudgeDocument,
)

# =============================================================================
# TUNABLES — every knob in the module lives here and nowhere else.
# =============================================================================

#: Fractional step toward a loved track's sonic vector. Not 1.0: a love says
#: "nearer", not "become this". A third of the way is enough to move the
#: aggregate over many events without any single love dictating a target.
LOVE_STEP: float = 0.35

#: Fractional step away from a skipped track. Roughly half a love, because a
#: skip is roughly half a signal — see the derivation above.
SKIP_STEP: float = 0.18

#: Relative weight of a skip row in the least-squares fit, on top of the
#: shorter step. The two compound intentionally: a skip is both a smaller
#: assertion and a less trusted one.
SKIP_WEIGHT: float = 0.55
LOVE_WEIGHT: float = 1.0

#: L2 cap on a single example's target delta. Sonic residuals can reach
#: sqrt(7) ≈ 2.65 in the worst case; capping at 0.6 keeps one freak track from
#: dominating a small training set. Applied by uniform scaling, so direction
#: survives.
MAX_EXAMPLE_DELTA: float = 0.6

#: Recency half-life in days, measured backwards from the newest event (never
#: from wall-clock — that would make refits non-deterministic). Taste drifts
#: with the season, which is the whole premise; a year-old skip should not
#: still be arguing.
HALF_LIFE_DAYS: float = 90.0

#: Ridge penalty. Interpretable as "λ pseudo-observations of zero effect per
#: feature". With features in [-1,1], the diagonal of XᵀX grows at roughly
#: 0.15n, so λ = 8 dominates completely at n ≈ 12 and becomes a mild lean at
#: n ≈ 300. Shrinkage that decays as evidence accumulates is exactly what we
#: want, and a fixed λ gives it for free.
DEFAULT_LAMBDA: float = 8.0

#: Fallback penalty used only if the normal equations resist factorisation.
DEGENERATE_LAMBDA_MULTIPLIER: float = 25.0

#: Below this many trainable events we emit nothing at all — ``fit_nudge``
#: returns None and the engine runs on the base matrix. Fewer than a dozen
#: signals cannot distinguish a taste from a Tuesday.
MIN_SAMPLES: int = 12

#: Confidence multiplier: conf(n) = n / (n + CONFIDENCE_HALF). Reaches 0.5 at
#: 120 signals and asymptotes to 1 without ever arriving. That asymptote is the
#: point — the base matrix keeps a controlling stake indefinitely.
CONFIDENCE_HALF: float = 120.0

#: Hard per-cell bound after confidence scaling. Base matrix couplings run to
#: order 0.6; 0.08 is roughly an eighth of a strong opinion. One sky dimension
#: at full deflection can therefore move one sonic dimension by at most 0.08 on
#: a [0,1] scale.
MAX_COEFFICIENT: float = 0.08

#: Per-output-column L1 budget: Σ_i |ΔM[i][j]| ≤ 0.20. This is the bound that
#: actually matters. Since |x_i| ≤ 1 for every sky dimension, it guarantees the
#: nudge can shift any single sonic dimension by at most 0.20 — a fifth of the
#: range — no matter how the sky is configured or how many cells conspire. The
#: per-cell clamp alone would permit 9 x 0.08 = 0.72, which is not a lean, it
#: is a coup. Enforced by uniform column scaling so signs and relative
#: structure survive.
COLUMN_L1_BUDGET: float = 0.20

#: Numerical floor for treating a pivot as zero.
PIVOT_EPSILON: float = 1e-12

# =============================================================================
# Linear algebra kernel
# =============================================================================
# Small, dense, and readable. Everything here is n <= 9, so clarity beats
# cleverness and there is no reason to reach for a dependency.

Vector = list[float]
Matrix = list[list[float]]


def zeros(rows: int, cols: int) -> Matrix:
    return [[0.0] * cols for _ in range(rows)]


def identity(n: int) -> Matrix:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def transpose(a: Sequence[Sequence[float]]) -> Matrix:
    if not a:
        return []
    return [[float(a[i][j]) for i in range(len(a))] for j in range(len(a[0]))]


def matmul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> Matrix:
    """Plain triple loop. Shapes are validated because a silent shape bug here
    produces plausible-looking garbage that survives every downstream check."""
    if not a or not b:
        return []
    n, k, m = len(a), len(b), len(b[0])
    if len(a[0]) != k:
        raise ValueError(f"cannot multiply {len(a)}x{len(a[0])} by {k}x{m}")
    out = zeros(n, m)
    for i in range(n):
        row_a = a[i]
        out_i = out[i]
        for p in range(k):
            aip = row_a[p]
            if aip == 0.0:
                continue
            row_b = b[p]
            for j in range(m):
                out_i[j] += aip * row_b[j]
    return out


def matvec(a: Sequence[Sequence[float]], v: Sequence[float]) -> Vector:
    return [sum(a[i][j] * v[j] for j in range(len(v))) for i in range(len(a))]


def cholesky(a: Sequence[Sequence[float]]) -> Matrix | None:
    """Cholesky factorisation A = L Lᵀ for symmetric positive-definite A.

    Returns the lower-triangular L, or ``None`` if A is not positive definite
    (a non-positive pivot appears). The normal-equations matrix XᵀX + λI is
    positive definite for any λ > 0 in exact arithmetic, so ``None`` here means
    numerical trouble, and the caller escalates rather than guessing.
    """
    n = len(a)
    lo = zeros(n, n)
    for i in range(n):
        for j in range(i + 1):
            acc = float(a[i][j])
            for k in range(j):
                acc -= lo[i][k] * lo[j][k]
            if i == j:
                if acc <= PIVOT_EPSILON:
                    return None
                lo[i][j] = math.sqrt(acc)
            else:
                lo[i][j] = acc / lo[j][j]
    return lo


def cholesky_solve(lo: Sequence[Sequence[float]], b: Sequence[float]) -> Vector:
    """Solve A z = b given A = L Lᵀ, by forward then back substitution."""
    n = len(lo)
    # Forward: L y = b
    y: Vector = [0.0] * n
    for i in range(n):
        acc = float(b[i])
        for k in range(i):
            acc -= lo[i][k] * y[k]
        y[i] = acc / lo[i][i]
    # Back: Lᵀ z = y
    z: Vector = [0.0] * n
    for i in range(n - 1, -1, -1):
        acc = y[i]
        for k in range(i + 1, n):
            acc -= lo[k][i] * z[k]
        z[i] = acc / lo[i][i]
    return z


def gauss_jordan_solve(
    a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]
) -> Matrix | None:
    """Solve A X = B for a general square A, using partial pivoting.

    The fallback path when Cholesky declines, and the general-purpose solver
    the tests exercise against a hand-checked system. Returns ``None`` if A is
    singular to within ``PIVOT_EPSILON`` — explicitly, rather than emitting
    infinities that would poison the nudge.
    """
    n = len(a)
    if any(len(row) != n for row in a) or len(b) != n:
        raise ValueError("gauss_jordan_solve: shape mismatch")
    m = len(b[0]) if b and b[0] else 0

    # Work on copies; the caller's matrices are not ours to shred.
    aug_a: Matrix = [[float(x) for x in row] for row in a]
    aug_b: Matrix = [[float(x) for x in row] for row in b]

    for col in range(n):
        # Partial pivot: largest magnitude in the remaining column. Without
        # this, a zero (or merely small) leading entry destroys accuracy.
        pivot_row = max(range(col, n), key=lambda r: abs(aug_a[r][col]))
        if abs(aug_a[pivot_row][col]) < PIVOT_EPSILON:
            return None
        if pivot_row != col:
            aug_a[col], aug_a[pivot_row] = aug_a[pivot_row], aug_a[col]
            aug_b[col], aug_b[pivot_row] = aug_b[pivot_row], aug_b[col]

        piv = aug_a[col][col]
        aug_a[col] = [x / piv for x in aug_a[col]]
        aug_b[col] = [x / piv for x in aug_b[col]]

        for r in range(n):
            if r == col:
                continue
            factor = aug_a[r][col]
            if factor == 0.0:
                continue
            row_a, row_b = aug_a[r], aug_b[r]
            pa, pb = aug_a[col], aug_b[col]
            for c in range(n):
                row_a[c] -= factor * pa[c]
            for c in range(m):
                row_b[c] -= factor * pb[c]

    return aug_b


def ridge_solve(
    x: Sequence[Sequence[float]], y: Sequence[Sequence[float]], lam: float
) -> tuple[Matrix, bool]:
    """Solve (XᵀX + λI) W = XᵀY. Returns ``(W, degenerate)``.

    W is (features x outputs) — here 9x7 — which is the nudge shape directly.
    ``degenerate`` is True when the primary factorisation failed and we had to
    fall back or, in the worst case, give up and return zeros. Giving up
    returns a zero matrix rather than raising: a user with pathological data
    should get the base matrix, not a 500.
    """
    n_features = len(x[0]) if x else 0
    n_outputs = len(y[0]) if y else 0
    xt = transpose(x)
    xtx = matmul(xt, x)
    xty = matmul(xt, y)

    for i in range(n_features):
        xtx[i][i] += lam

    lo = cholesky(xtx)
    if lo is not None:
        # One factorisation, seven cheap back-substitutions — the reason to
        # prefer Cholesky here at all.
        cols = transpose(xty)  # outputs x features
        solved = [cholesky_solve(lo, col) for col in cols]
        return transpose(solved), False

    # Cholesky refused. Try a general solve with pivoting on a more heavily
    # regularised system; extra λ is exactly the remedy for near-singularity.
    boosted = matmul(xt, x)
    for i in range(n_features):
        boosted[i][i] += lam * DEGENERATE_LAMBDA_MULTIPLIER
    w = gauss_jordan_solve(boosted, xty)
    if w is None:
        return zeros(n_features, n_outputs), True
    return w, True


# =============================================================================
# Training-set assembly
# =============================================================================


class _Example:
    """One row of the regression: sky features, target delta, and a weight."""

    __slots__ = ("features", "target", "weight")

    def __init__(self, features: Vector, target: Vector, weight: float) -> None:
        self.features = features
        self.target = target
        self.weight = weight


def _cap_delta(delta: Vector, cap: float = MAX_EXAMPLE_DELTA) -> Vector:
    """Scale a target delta down to ``cap`` in L2, preserving direction."""
    norm = math.sqrt(sum(v * v for v in delta))
    if norm <= cap or norm == 0.0:
        return delta
    scale = cap / norm
    return [v * scale for v in delta]


def _recency_weight(event_at: datetime, newest: datetime) -> float:
    """Exponential decay with ``HALF_LIFE_DAYS``, anchored to the newest event.

    Anchoring to the data rather than to ``now`` is what keeps refits
    deterministic; it also means a dormant user's nudge does not quietly
    evaporate while they are away.
    """
    age_days = max(0.0, (newest - event_at).total_seconds() / 86_400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def build_training_set(
    records: Sequence[ForgeRecord], events: Sequence[FeedbackEvent]
) -> list[_Example]:
    """Turn feedback into ``(x, d, w)`` rows. See the module docstring.

    ``records`` are used to backfill context on events that arrived without it
    — an older client, or a store that wrote the event before the snapshot
    convention existed. Events that still lack a track vector after backfill
    are dropped: they carry no direction in sonic space and would only add
    rows of zeros.
    """
    by_id = {r.playlist_id: r for r in records}

    # Deterministic ordering. Ridge is order-invariant in exact arithmetic but
    # floating-point summation is not, and "same inputs, same output" is a
    # requirement, not an aspiration.
    ordered = sorted(
        events, key=lambda e: (e.created_at, e.playlist_id, e.track_key, e.signal)
    )
    if not ordered:
        return []
    newest = max(e.created_at for e in ordered)

    examples: list[_Example] = []
    for event in ordered:
        record = by_id.get(event.playlist_id)

        sky = event.sky
        target = event.sonic_target
        track_sonic = event.track_sonic
        if record is not None:
            # Backfill only what is missing; the snapshot always wins.
            if track_sonic is None:
                stored = record.track(event.track_key)
                track_sonic = stored.sonic if stored else None
            if not any(sky.as_array()):
                sky = record.sky
                target = record.sonic
        if track_sonic is None:
            continue

        x = sky.as_array()
        if not any(x):
            # An all-zero sky row contributes nothing to XᵀX and nothing to
            # XᵀY. Dropping it keeps the sample count honest.
            continue

        residual = [s - t for s, t in zip(track_sonic.as_array(), target.as_array())]
        step = LOVE_STEP if event.is_love else -SKIP_STEP
        delta = _cap_delta([step * r for r in residual])

        weight = (LOVE_WEIGHT if event.is_love else SKIP_WEIGHT) * _recency_weight(
            event.created_at, newest
        )
        if weight <= 0.0:
            continue
        examples.append(_Example(x, delta, weight))

    return examples


# =============================================================================
# Regularisation, confidence, clamping
# =============================================================================


def confidence_for(samples: int) -> float:
    """conf(n) = n / (n + CONFIDENCE_HALF). Slow, saturating, never 1."""
    if samples <= 0:
        return 0.0
    return samples / (samples + CONFIDENCE_HALF)


def clamp_matrix(
    w: Sequence[Sequence[float]],
    *,
    cell_bound: float = MAX_COEFFICIENT,
    column_budget: float = COLUMN_L1_BUDGET,
) -> Matrix:
    """Two-stage containment: per-cell truncation, then a per-column L1 budget.

    Stage one stops a single coefficient running away. Stage two is the bound
    that actually constrains the product: because every sky dimension is
    bounded by 1 in magnitude, an L1 budget of 0.20 on a column caps the total
    shift the nudge can apply to that sonic dimension at 0.20, whatever the
    weather does. Stage two scales the whole column uniformly rather than
    truncating cells, so the *shape* of what the user taught us survives even
    when its magnitude does not.
    """
    out: Matrix = [
        [max(-cell_bound, min(cell_bound, float(v))) for v in row] for row in w
    ]
    n_cols = len(out[0]) if out else 0
    for j in range(n_cols):
        total = sum(abs(out[i][j]) for i in range(len(out)))
        if total > column_budget and total > 0.0:
            scale = column_budget / total
            for i in range(len(out)):
                out[i][j] *= scale
    return out


def _r2_uncentred(
    x: Sequence[Sequence[float]], y: Sequence[Sequence[float]], w: Sequence[Sequence[float]]
) -> list[float]:
    """R² per output against the null model "no correction needed" (ŷ = 0)."""
    preds = matmul(x, w)
    n_out = len(y[0]) if y and y[0] else 0
    out: list[float] = []
    for j in range(n_out):
        ss_res = sum((y[k][j] - preds[k][j]) ** 2 for k in range(len(y)))
        ss_tot = sum(y[k][j] ** 2 for k in range(len(y)))
        out.append(0.0 if ss_tot <= 0.0 else 1.0 - ss_res / ss_tot)
    return out


# =============================================================================
# Public entry point
# =============================================================================


def fit_nudge(
    records: Sequence[ForgeRecord],
    events: Sequence[FeedbackEvent],
    *,
    lam: float = DEFAULT_LAMBDA,
    min_samples: int = MIN_SAMPLES,
) -> NudgeDocument | None:
    """Fit the per-user 9x7 delta, or return ``None`` if there is not enough.

    ``None`` means "run the base matrix". It is the correct answer far more
    often than a nudge is, and returning a near-zero matrix instead would be a
    worse API: the caller could not distinguish "we looked and found nothing"
    from "we have not looked".
    """
    examples = build_training_set(records, events)
    samples = len(examples)
    if samples < min_samples:
        return None

    # Weighted least squares by row scaling: minimising ‖√w (Xw − y)‖² is the
    # same problem as minimising Σ w (x·w − y)², and lets the unweighted solver
    # stay simple.
    x_rows: Matrix = []
    y_rows: Matrix = []
    for ex in examples:
        rw = math.sqrt(ex.weight)
        x_rows.append([v * rw for v in ex.features])
        y_rows.append([v * rw for v in ex.target])

    raw, degenerate = ridge_solve(x_rows, y_rows, lam)

    # Confidence first, then clamps. Ordering matters: scaling a clamped matrix
    # would waste headroom, and clamping a scaled one is what actually bounds
    # what ships.
    confidence = confidence_for(samples)
    scaled = [[v * confidence for v in row] for row in raw]
    final = clamp_matrix(scaled)

    r2 = _r2_uncentred(x_rows, y_rows, raw)
    loved = sum(1 for e in events if e.signal == "loved")
    skipped = sum(1 for e in events if e.signal == "skipped")
    max_abs = max((abs(v) for row in final for v in row), default=0.0)

    # Stamped with the newest event rather than wall-clock, so an unchanged
    # feedback history refits to an identical document.
    updated_at = (
        max(e.created_at for e in events)
        if events
        else datetime.now(timezone.utc)
    )

    return NudgeDocument(
        matrix=final,
        samples=samples,
        updated_at=updated_at,
        matrix_version=MATRIX_VERSION,
        diagnostics=NudgeDiagnostics(
            r2=[round(v, 6) for v in r2],
            mean_r2=round(sum(r2) / len(r2), 6) if r2 else 0.0,
            lam=lam,
            confidence=round(confidence, 6),
            max_abs_coefficient=round(max_abs, 9),
            degenerate=degenerate,
            loved=loved,
            skipped=skipped,
        ),
    )


def explain_nudge(doc: NudgeDocument, *, top: int = 5) -> list[str]:
    """Human-readable summary of the strongest leans. Used by the retrospective
    and by anyone trying to work out what the model thinks it learned."""
    cells: list[tuple[float, str, str]] = []
    for i in range(SKY_N):
        for j in range(SONIC_N):
            v = doc.matrix[i][j]
            if v != 0.0:
                cells.append((abs(v), SKY_DIMS[i], SONIC_DIMS[j]))
    cells.sort(key=lambda c: (-c[0], c[1], c[2]))
    lines: list[str] = []
    for _, sky_dim, sonic_dim in cells[:top]:
        v = doc.cell(sky_dim, sonic_dim)
        direction = "up" if v > 0 else "down"
        lines.append(
            f"{sky_dim} rising pushes {sonic_dim} {direction} ({v:+.3f})"
        )
    return lines


__all__ = [
    # tunables
    "LOVE_STEP",
    "SKIP_STEP",
    "SKIP_WEIGHT",
    "LOVE_WEIGHT",
    "MAX_EXAMPLE_DELTA",
    "HALF_LIFE_DAYS",
    "DEFAULT_LAMBDA",
    "MIN_SAMPLES",
    "CONFIDENCE_HALF",
    "MAX_COEFFICIENT",
    "COLUMN_L1_BUDGET",
    # kernel
    "Vector",
    "Matrix",
    "zeros",
    "identity",
    "transpose",
    "matmul",
    "matvec",
    "cholesky",
    "cholesky_solve",
    "gauss_jordan_solve",
    "ridge_solve",
    # pipeline
    "build_training_set",
    "confidence_for",
    "clamp_matrix",
    "fit_nudge",
    "explain_nudge",
]
