"""Tests for the Almanac: store, learner, and retrospective.

No network, no fixtures from other workers. All synthetic history is built
locally in this file so the suite runs against the Almanac alone.

Async tests drive the store through ``asyncio.run`` rather than
``pytest.mark.asyncio``. That is deliberate: it makes the suite indifferent to
whatever ``asyncio_mode`` the repo-wide pytest config eventually settles on,
and it exercises the store across genuinely separate event loops, which is a
real failure mode for a lock created at construction time.
"""

from __future__ import annotations

import asyncio
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Bootstrap: locate the directory containing the `backend` package. Harmless
# when the repo already puts it on the path.
_here = Path(__file__).resolve()
for _parent in _here.parents:
    if (_parent / "backend" / "app").is_dir():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break

from backend.app.contracts import (  # noqa: E402
    SKY_DIMS,
    SONIC_DIMS,
    AlmanacStore,
    Playlist,
    Rationale,
    ScoredTrack,
    SkyVector,
    SonicVector,
    Track,
)
from backend.app.almanac import learning  # noqa: E402
from backend.app.almanac.learning import (  # noqa: E402
    COLUMN_L1_BUDGET,
    MAX_COEFFICIENT,
    MIN_SAMPLES,
    build_training_set,
    cholesky,
    cholesky_solve,
    clamp_matrix,
    confidence_for,
    fit_nudge,
    gauss_jordan_solve,
    matmul,
    ridge_solve,
    transpose,
)
from backend.app.almanac.memory_store import MemoryAlmanac  # noqa: E402
from backend.app.almanac.models import (  # noqa: E402
    MATRIX_VERSION,
    FeedbackEvent,
    ForgeRecord,
    NudgeDocument,
    TrackRecord,
)
from backend.app.almanac.retrospective import (  # noqa: E402
    COLD_START_FORGES,
    assign_region,
    build_retrospective,
    describe_sonic,
)

EPOCH = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
USER = "jerome"


def run(coro):
    """Drive a coroutine to completion on a throwaway loop."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Deterministic pseudo-randomness
# ---------------------------------------------------------------------------


class Lcg:
    """A tiny linear congruential generator.

    ``random.Random`` would also be deterministic given a seed, but this makes
    the determinism obvious to a reader and immune to a stdlib implementation
    change.
    """

    def __init__(self, seed: int = 20260105) -> None:
        self.state = seed

    def next_unit(self) -> float:
        self.state = (self.state * 1103515245 + 12345) % (2**31)
        return self.state / float(2**31)

    def signed(self, scale: float = 1.0) -> float:
        return (self.next_unit() * 2.0 - 1.0) * scale

    def unit(self, low: float = 0.0, high: float = 1.0) -> float:
        return low + self.next_unit() * (high - low)


# ---------------------------------------------------------------------------
# Synthetic history builders
# ---------------------------------------------------------------------------


def make_track(title: str, artist: str, sonic: SonicVector, tags=()) -> Track:
    return Track(title=title, artist=artist, tags=list(tags), estimated=sonic)


def make_playlist(
    pid: str,
    *,
    sky: SkyVector,
    sonic: SonicVector,
    tracks: list[Track],
    created_at: datetime,
    user_id: str | None = USER,
    theme_id: str = "gale-warning",
    genre_id: str = "ambient",
) -> Playlist:
    return Playlist(
        id=pid,
        title=f"Forge {pid}",
        subtitle="",
        tracks=[
            ScoredTrack(track=t, score=1.0 - 0.01 * i, position=i)
            for i, t in enumerate(tracks)
        ],
        sky=sky,
        sonic_target=sonic,
        theme_id=theme_id,
        genre_id=genre_id,
        rationale=Rationale(headline="", body=""),
        created_at=created_at,
        user_id=user_id,
    )


def sonic(**kwargs: float) -> SonicVector:
    """A SonicVector centred at 0.5 with named overrides."""
    base = {d: 0.5 for d in SONIC_DIMS}
    base.update(kwargs)
    return SonicVector(**base)


def barometer_training_history(
    n: int = 48, *, user_id: str = USER
) -> tuple[list[ForgeRecord], list[FeedbackEvent]]:
    """The signal the learner must recover.

    Construction: the barometer swings between clearly falling and clearly
    rising, and the user's taste tracks it linearly —

        loved valence = 0.5 + 0.45 * pressure_trend_6h

    so a hard fall (-1.0) means they keep a valence-0.05 record and a hard rise
    (+1.0) means they keep a valence-0.95 one. Every other sky dimension is
    pseudo-random and uncorrelated with the target, and every sonic target the
    engine produced is dead neutral, so the only explanation available to the
    fit is a positive coefficient in
    ``nudge[pressure_trend_6h][valence]``.

    Both halves of the barometer are included on purpose. If the training set
    only ever fell, the target would have a non-zero mean, and the unsigned sky
    dimensions — which are always positive and thus act as a pseudo-intercept —
    could soak the signal up. Spanning the sign makes the coefficient
    identifiable rather than merely plausible.
    """
    rng = Lcg()
    records: list[ForgeRecord] = []
    events: list[FeedbackEvent] = []

    for i in range(n):
        falling = i % 2 == 0
        magnitude = 0.35 + 0.65 * rng.next_unit()
        trend = -magnitude if falling else magnitude

        sky = SkyVector(
            pressure_trend_6h=trend,
            pressure_norm_deviation=rng.signed(0.4),
            temp_norm_deviation=rng.signed(0.5),
            sun_elevation=rng.signed(0.6),
            golden_hour_proximity=rng.unit(0.0, 0.5),
            gust_variance=rng.unit(0.0, 0.6),
            cloud_depth=rng.unit(0.2, 0.8),
            precip_intensity=rng.unit(0.0, 0.4),
            daylight_delta=rng.signed(0.5),
            observed_at=EPOCH + timedelta(hours=6 * i),
        )
        target = sonic()  # neutral: the engine had no opinion to correct.

        loved_valence = 0.5 + 0.45 * trend
        loved = make_track(f"kept-{i}", "Held Note", sonic(valence=loved_valence))
        # The mirror image: a track the user rejects, on the wrong side.
        rejected = make_track(
            f"dropped-{i}", "Wrong Weather", sonic(valence=0.5 - 0.45 * trend)
        )

        created = EPOCH + timedelta(hours=6 * i)
        record = ForgeRecord(
            playlist_id=f"p{i:03d}",
            user_id=user_id,
            sky=sky,
            sonic=target,
            theme_id="gale-warning",
            genre_id="ambient",
            tracks=[
                TrackRecord(
                    key=loved.key,
                    title=loved.title,
                    artist=loved.artist,
                    sonic=loved.estimated,
                    position=0,
                ),
                TrackRecord(
                    key=rejected.key,
                    title=rejected.title,
                    artist=rejected.artist,
                    sonic=rejected.estimated,
                    position=1,
                ),
            ],
            created_at=created,
        )
        records.append(record)
        events.append(
            FeedbackEvent.from_forge(
                record,
                user_id=user_id,
                track_key=loved.key,
                signal="loved",
                created_at=created + timedelta(minutes=5),
            )
        )
        events.append(
            FeedbackEvent.from_forge(
                record,
                user_id=user_id,
                track_key=rejected.key,
                signal="skipped",
                created_at=created + timedelta(minutes=7),
            )
        )
    return records, events


#: Prototype skies for the retrospective fixture, one per region we want cards
#: for. Values are chosen to sit close to the region prototypes.
_REGION_SKIES = {
    "deluge": dict(precip_intensity=0.88, cloud_depth=0.82, pressure_trend_6h=-0.2),
    "collapsing_barometer": dict(pressure_trend_6h=-0.8, pressure_norm_deviation=-0.4),
    "first_frost": dict(
        temp_norm_deviation=-0.72,
        cloud_depth=0.08,
        pressure_norm_deviation=0.62,
        precip_intensity=0.0,
    ),
    "golden_hour": dict(golden_hour_proximity=0.9, sun_elevation=0.14),
}

#: The sonic signature the fixture user converges on in each region, and the
#: artist they keep there. Distinct enough that the cards must differ.
_REGION_TASTE = {
    "deluge": (sonic(valence=0.22, energy=0.28, spatiality=0.84, acousticness=0.72), "Låpsley"),
    "collapsing_barometer": (
        sonic(valence=0.18, energy=0.35, grit=0.78, density=0.7),
        "Godspeed",
    ),
    "first_frost": (sonic(valence=0.4, acousticness=0.9, density=0.2, tempo=0.25), "Arvo Pärt"),
    "golden_hour": (sonic(valence=0.78, energy=0.6, spatiality=0.7), "Khruangbin"),
}


def seeded_history(
    per_region: int = 4, *, user_id: str = USER
) -> tuple[list[Playlist], list[FeedbackEvent]]:
    """A believable multi-region history with loves attached."""
    playlists: list[Playlist] = []
    events: list[FeedbackEvent] = []
    i = 0
    for region_id, sky_kwargs in _REGION_SKIES.items():
        signature, artist = _REGION_TASTE[region_id]
        for k in range(per_region):
            created = EPOCH + timedelta(days=3 * i)
            sky = SkyVector(**sky_kwargs, observed_at=created)
            kept = make_track(f"{region_id}-anthem", artist, signature)
            filler = make_track(f"{region_id}-filler-{k}", "Session Band", sonic())
            # Playlist ids are globally unique in production; namespace them by
            # user here so two fixtures cannot collide.
            pl = make_playlist(
                f"{user_id}-{region_id}-{k}",
                sky=sky,
                sonic=signature,
                tracks=[kept, filler],
                created_at=created,
                user_id=user_id,
                theme_id=f"theme-{region_id}",
            )
            playlists.append(pl)
            record = ForgeRecord.from_playlist(pl)
            events.append(
                FeedbackEvent.from_forge(
                    record,
                    user_id=user_id,
                    track_key=kept.key,
                    signal="loved",
                    created_at=created + timedelta(minutes=3),
                )
            )
            if k % 2 == 0:
                events.append(
                    FeedbackEvent.from_forge(
                        record,
                        user_id=user_id,
                        track_key=filler.key,
                        signal="skipped",
                        created_at=created + timedelta(minutes=4),
                    )
                )
            i += 1
    return playlists, events


# ===========================================================================
# 1. MemoryAlmanac / AlmanacStore
# ===========================================================================


def test_memory_almanac_constructs_with_no_arguments():
    # container.py instantiates it bare when Firestore is unconfigured.
    store = MemoryAlmanac()
    assert len(store) == 0


def test_memory_almanac_satisfies_the_protocol():
    store = MemoryAlmanac()
    assert isinstance(store, AlmanacStore)
    for name in ("record_forge", "record_feedback", "history", "nudge"):
        assert asyncio.iscoroutinefunction(getattr(store, name))


def test_record_forge_returns_id_and_history_is_newest_first():
    playlists, _ = seeded_history(per_region=2)
    store = MemoryAlmanac()

    async def scenario():
        for pl in playlists:
            assert await store.record_forge(pl) == pl.id
        return await store.history(USER, limit=50)

    got = run(scenario())
    assert len(got) == len(playlists)
    stamps = [p.created_at for p in got]
    assert stamps == sorted(stamps, reverse=True), "history must be newest first"
    assert got[0].id == max(playlists, key=lambda p: p.created_at).id


def test_history_respects_limit_and_isolates_users():
    a, _ = seeded_history(per_region=2, user_id="alice")
    b, _ = seeded_history(per_region=1, user_id="bob")
    store = MemoryAlmanac()

    async def scenario():
        for pl in a + b:
            await store.record_forge(pl)
        return (
            await store.history("alice", limit=3),
            await store.history("bob", limit=50),
            await store.history("nobody", limit=50),
        )

    alice, bob, nobody = run(scenario())
    assert len(alice) == 3
    assert len(bob) == len(b)
    assert nobody == []
    assert {p.user_id for p in alice} == {"alice"}


def test_record_feedback_snapshots_the_sky_context():
    playlists, _ = seeded_history(per_region=1)
    pl = playlists[0]
    kept = pl.tracks[0].track
    store = MemoryAlmanac()

    async def scenario():
        await store.record_forge(pl)
        await store.record_feedback(
            user_id=USER, playlist_id=pl.id, track_key=kept.key, signal="loved"
        )
        await store.record_feedback(
            user_id=USER,
            playlist_id=pl.id,
            track_key=pl.tracks[1].track.key,
            signal="skipped",
        )
        return await store.feedback(USER)

    events = run(scenario())
    assert [e.signal for e in events] == ["loved", "skipped"]
    love = events[0]
    # The whole point of the snapshot: context travels with the signal.
    assert love.sky.as_array() == pl.sky.as_array()
    assert love.track_sonic == kept.estimated
    assert love.track_artist == kept.artist
    assert love.trainable()


def test_feedback_for_unknown_playlist_is_still_recorded_but_untrainable():
    store = MemoryAlmanac()

    async def scenario():
        await store.record_feedback(
            user_id=USER, playlist_id="ghost", track_key="a::b", signal="loved"
        )
        return await store.feedback(USER)

    events = run(scenario())
    assert len(events) == 1
    assert not events[0].trainable()


def test_reforging_an_id_under_a_new_owner_moves_it():
    # An anonymous forge claimed after sign-in. It must leave the anonymous
    # history and appear in the user's, not vanish from both.
    playlists, _ = seeded_history(per_region=1, user_id="alice")
    pl = playlists[0]
    store = MemoryAlmanac()

    async def scenario():
        await store.record_forge(pl.model_copy(update={"user_id": None}))
        anon_before = await store.history("anonymous")
        await store.record_forge(pl)  # same id, now owned by alice
        return anon_before, await store.history("anonymous"), await store.history("alice")

    anon_before, anon_after, alice = run(scenario())
    assert len(anon_before) == 1
    assert anon_after == []
    assert [p.id for p in alice] == [pl.id]


def test_store_survives_a_change_of_event_loop():
    # asyncio.run builds and tears down a loop each time; a lock bound at
    # construction would raise on the second call.
    playlists, _ = seeded_history(per_region=1)
    store = MemoryAlmanac()
    run(store.record_forge(playlists[0]))
    run(store.record_forge(playlists[1]))
    assert len(run(store.history(USER))) == 2


def test_seed_helper_populates_history_without_a_loop():
    playlists, events = seeded_history(per_region=2)
    store = MemoryAlmanac().seed(playlists).seed_feedback(events)
    got = run(store.history(USER, limit=100))
    assert len(got) == len(playlists)
    assert len(run(store.feedback(USER))) == len(events)


def test_nudge_is_none_without_evidence_and_a_matrix_with_it():
    store = MemoryAlmanac()
    assert run(store.nudge(USER)) is None

    records, events = barometer_training_history(n=48)
    store.seed_records(records).seed_feedback(events)
    matrix = run(store.nudge(USER))
    assert matrix is not None
    assert len(matrix) == len(SKY_DIMS)
    assert all(len(row) == len(SONIC_DIMS) for row in matrix)


# ===========================================================================
# 2. Linear algebra kernel — checked against systems solved by hand
# ===========================================================================


def test_transpose_and_matmul():
    a = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert transpose(a) == [[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]]
    b = [[7.0, 8.0], [9.0, 10.0], [11.0, 12.0]]
    # [[1*7+2*9+3*11, 1*8+2*10+3*12], [4*7+5*9+6*11, 4*8+5*10+6*12]]
    assert matmul(a, b) == [[58.0, 64.0], [139.0, 154.0]]
    with pytest.raises(ValueError):
        matmul(a, a)


def test_gauss_jordan_solves_a_hand_checked_system():
    #  2x +  y -  z =   8
    # -3x -  y + 2z = -11
    # -2x +  y + 2z =  -3
    # Solution, by elimination on paper: x = 2, y = 3, z = -1.
    a = [[2.0, 1.0, -1.0], [-3.0, -1.0, 2.0], [-2.0, 1.0, 2.0]]
    b = [[8.0], [-11.0], [-3.0]]
    x = gauss_jordan_solve(a, b)
    assert x is not None
    assert x[0][0] == pytest.approx(2.0, abs=1e-9)
    assert x[1][0] == pytest.approx(3.0, abs=1e-9)
    assert x[2][0] == pytest.approx(-1.0, abs=1e-9)


def test_gauss_jordan_handles_multiple_right_hand_sides():
    a = [[2.0, 0.0], [0.0, 4.0]]
    b = [[2.0, 6.0], [8.0, 4.0]]
    x = gauss_jordan_solve(a, b)
    assert x == [[1.0, 3.0], [2.0, 1.0]]


def test_gauss_jordan_needs_pivoting_and_does_it():
    # A zero in the leading position: naive elimination divides by zero.
    a = [[0.0, 1.0], [1.0, 0.0]]
    b = [[3.0], [5.0]]
    x = gauss_jordan_solve(a, b)
    assert x is not None
    assert x[0][0] == pytest.approx(5.0)
    assert x[1][0] == pytest.approx(3.0)


def test_gauss_jordan_reports_singularity_explicitly():
    # Second row is twice the first: rank 1, no unique solution.
    assert gauss_jordan_solve([[1.0, 2.0], [2.0, 4.0]], [[1.0], [2.0]]) is None


def test_cholesky_matches_the_textbook_factorisation():
    a = [[4.0, 12.0, -16.0], [12.0, 37.0, -43.0], [-16.0, -43.0, 98.0]]
    lo = cholesky(a)
    assert lo is not None
    assert lo == [[2.0, 0.0, 0.0], [6.0, 1.0, 0.0], [-8.0, 5.0, 3.0]]
    # ...and L Lᵀ really does reconstruct A.
    recon = matmul(lo, transpose(lo))
    for i in range(3):
        for j in range(3):
            assert recon[i][j] == pytest.approx(a[i][j], abs=1e-9)


def test_cholesky_solve_is_right():
    a = [[4.0, 12.0, -16.0], [12.0, 37.0, -43.0], [-16.0, -43.0, 98.0]]
    lo = cholesky(a)
    assert lo is not None
    x = cholesky_solve(lo, [1.0, 2.0, 3.0])
    # Verify by substitution rather than by quoting a number.
    residual = [sum(a[i][j] * x[j] for j in range(3)) for i in range(3)]
    assert residual == pytest.approx([1.0, 2.0, 3.0], abs=1e-9)


def test_cholesky_rejects_non_positive_definite_input():
    assert cholesky([[1.0, 2.0], [2.0, 1.0]]) is None  # eigenvalues 3 and -1
    assert cholesky([[0.0, 0.0], [0.0, 0.0]]) is None


def test_ridge_solve_matches_a_closed_form_case():
    # One feature, two observations both x = 1, y = 2 and y = 4.
    # XᵀX = 2, XᵀY = 6, λ = 1  =>  w = 6 / (2 + 1) = 2.
    w, degenerate = ridge_solve([[1.0], [1.0]], [[2.0], [4.0]], 1.0)
    assert not degenerate
    assert w[0][0] == pytest.approx(2.0, abs=1e-12)

    # Orthonormal design: (I + λI)⁻¹ I = 1/(1+λ) on the diagonal.
    w2, _ = ridge_solve([[1.0, 0.0], [0.0, 1.0]], [[1.0, 0.0], [0.0, 1.0]], 1.0)
    assert w2[0][0] == pytest.approx(0.5, abs=1e-12)
    assert w2[1][1] == pytest.approx(0.5, abs=1e-12)
    assert w2[0][1] == pytest.approx(0.0, abs=1e-12)


def test_ridge_solve_survives_perfectly_collinear_features():
    # Two identical columns. Without ridge this is singular; with it, finite.
    x = [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]
    y = [[1.0], [2.0], [3.0]]
    w, _ = ridge_solve(x, y, 4.0)
    assert all(math.isfinite(v) for row in w for v in row)
    # Symmetry of the design forces the two coefficients to be equal.
    assert w[0][0] == pytest.approx(w[1][0], abs=1e-9)


# ===========================================================================
# 3. fit_nudge — the learning loop
# ===========================================================================


def test_fit_nudge_returns_none_below_min_samples():
    records, events = barometer_training_history(n=48)
    # Two trainable events per forge, so trim to just under the threshold.
    few = events[: MIN_SAMPLES - 1]
    assert fit_nudge(records, few) is None
    assert len(build_training_set(records, few)) < MIN_SAMPLES


def test_fit_nudge_returns_none_with_no_evidence_at_all():
    assert fit_nudge([], []) is None


def test_fit_nudge_respects_an_explicit_min_samples():
    records, events = barometer_training_history(n=48)
    assert fit_nudge(records, events, min_samples=10_000) is None
    assert fit_nudge(records, events, min_samples=4) is not None


def test_falling_barometer_love_produces_the_right_sign():
    """The test that proves the learning loop works.

    The synthetic user keeps dark records when the glass falls and bright ones
    when it rises. The engine's target was neutral throughout, so every love is
    a correction. The correction the fit must discover is a POSITIVE
    coefficient at ``[pressure_trend_6h][valence]``: multiplied by a negative
    pressure trend it lowers valence, and by a positive one it raises it.
    """
    records, events = barometer_training_history(n=48)
    doc = fit_nudge(records, events)
    assert doc is not None
    assert doc.matrix_version == MATRIX_VERSION

    coefficient = doc.cell("pressure_trend_6h", "valence")
    assert coefficient > 0.0, f"expected a positive lean, got {coefficient:+.5f}"

    # ...and it must be the dominant term in the valence column, not a
    # coincidence hiding among noise.
    valence_col = [row[SONIC_DIMS.index("valence")] for row in doc.matrix]
    dominant = max(range(len(valence_col)), key=lambda i: abs(valence_col[i]))
    assert SKY_DIMS[dominant] == "pressure_trend_6h"

    # Sanity: the nudge actually moves valence the right way for real weather.
    idx = SKY_DIMS.index("pressure_trend_6h")
    falling = SkyVector(pressure_trend_6h=-0.9)
    delta = sum(
        doc.matrix[i][SONIC_DIMS.index("valence")] * v
        for i, v in enumerate(falling.as_array())
    )
    assert delta < 0.0, "a falling glass must pull valence down"
    assert doc.matrix[idx][SONIC_DIMS.index("valence")] > 0.0


def test_the_inverse_signal_produces_the_inverse_sign():
    """Flip the user's taste and the coefficient must flip with it.

    Guards against a fit that happens to produce a positive number regardless
    of the data.
    """
    records, events = barometer_training_history(n=48)
    flipped: list[FeedbackEvent] = []
    for e in events:
        assert e.track_sonic is not None
        mirrored = e.track_sonic.model_copy(
            update={"valence": 1.0 - e.track_sonic.valence}
        )
        flipped.append(e.model_copy(update={"track_sonic": mirrored}))

    doc = fit_nudge(records, flipped)
    assert doc is not None
    assert doc.cell("pressure_trend_6h", "valence") < 0.0


def test_skips_alone_still_train_but_more_gently():
    """A skip carries the same direction as the opposite love, at less volume."""
    records, events = barometer_training_history(n=48)
    loves = [e for e in events if e.is_love]
    skips = [e for e in events if not e.is_love]

    love_doc = fit_nudge(records, loves, min_samples=4)
    skip_doc = fit_nudge(records, skips, min_samples=4)
    assert love_doc is not None and skip_doc is not None

    # The construction mirrors the loved track around neutral for the skipped
    # one, so both should lean the same way.
    assert love_doc.cell("pressure_trend_6h", "valence") > 0.0
    assert skip_doc.cell("pressure_trend_6h", "valence") > 0.0
    # ...but a skip is worth less than a love, by design.
    assert abs(skip_doc.cell("pressure_trend_6h", "valence")) < abs(
        love_doc.cell("pressure_trend_6h", "valence")
    )


def test_every_coefficient_respects_the_clamp_bound():
    records, events = barometer_training_history(n=200)
    doc = fit_nudge(records, events)
    assert doc is not None
    for i, row in enumerate(doc.matrix):
        for j, v in enumerate(row):
            assert abs(v) <= MAX_COEFFICIENT + 1e-12, (
                f"{SKY_DIMS[i]}x{SONIC_DIMS[j]} = {v} exceeds the clamp"
            )
    assert doc.diagnostics.max_abs_coefficient <= MAX_COEFFICIENT + 1e-12


def test_every_column_respects_the_l1_budget():
    """The bound that actually constrains the product: with |sky| <= 1, an L1
    budget of 0.20 per column caps the achievable shift in any sonic dimension
    at 0.20, whatever the weather does."""
    records, events = barometer_training_history(n=200)
    doc = fit_nudge(records, events)
    assert doc is not None
    for j, dim in enumerate(SONIC_DIMS):
        total = sum(abs(row[j]) for row in doc.matrix)
        assert total <= COLUMN_L1_BUDGET + 1e-9, f"{dim} column L1 = {total}"


def test_clamp_matrix_scales_columns_uniformly_and_keeps_signs():
    raw = [[0.5 if i < 4 else -0.5 for _ in SONIC_DIMS] for i in range(len(SKY_DIMS))]
    out = clamp_matrix(raw)
    for j in range(len(SONIC_DIMS)):
        col_in = [raw[i][j] for i in range(len(SKY_DIMS))]
        col_out = [out[i][j] for i in range(len(SKY_DIMS))]
        assert sum(abs(v) for v in col_out) <= COLUMN_L1_BUDGET + 1e-12
        for a, b in zip(col_in, col_out):
            assert math.copysign(1.0, a) == math.copysign(1.0, b)
        # Uniform scaling preserves ratios between cells.
        assert abs(col_out[0]) == pytest.approx(abs(col_out[1]), abs=1e-12)


def test_confidence_grows_slowly_and_never_reaches_one():
    assert confidence_for(0) == 0.0
    assert confidence_for(12) < 0.15
    assert confidence_for(120) == pytest.approx(0.5)
    assert confidence_for(10_000) < 1.0
    # Monotone.
    values = [confidence_for(n) for n in (12, 40, 120, 500, 2000)]
    assert values == sorted(values)


def test_a_handful_of_signals_barely_moves_anything():
    """Regularise hard: 14 signals must not rewrite the soul of the app."""
    records, events = barometer_training_history(n=7)  # 14 events
    doc = fit_nudge(records, events)
    assert doc is not None
    assert doc.samples == 14
    assert doc.diagnostics.max_abs_coefficient < 0.02


def test_fit_nudge_is_deterministic():
    records, events = barometer_training_history(n=48)
    a = fit_nudge(records, events)
    b = fit_nudge(records, events)
    assert a is not None and b is not None
    assert a.matrix == b.matrix
    assert a.updated_at == b.updated_at
    assert a.to_json_dict() == b.to_json_dict()

    # ...and independent of the order the events arrive in.
    shuffled = list(reversed(events))
    c = fit_nudge(records, shuffled)
    assert c is not None
    for row_a, row_c in zip(a.matrix, c.matrix):
        assert row_a == pytest.approx(row_c, abs=1e-12)


def test_nudge_document_round_trips_through_json():
    records, events = barometer_training_history(n=48)
    doc = fit_nudge(records, events)
    assert doc is not None
    payload = doc.to_json_dict()
    assert payload["matrixVersion"] == MATRIX_VERSION
    assert len(payload["matrix"]) == 9 and len(payload["matrix"][0]) == 7
    assert isinstance(payload["updated_at"], str)
    again = NudgeDocument.from_json_dict(payload)
    assert again.matrix == doc.matrix
    assert again.samples == doc.samples


def test_untrainable_events_are_dropped_from_the_training_set():
    records, events = barometer_training_history(n=48)
    blinded = [e.model_copy(update={"track_sonic": None}) for e in events]
    # No forge records to backfill from, so nothing is trainable.
    assert build_training_set([], blinded) == []
    # With the records present, backfill rescues them.
    assert len(build_training_set(records, blinded)) == len(events)


# ===========================================================================
# 4. Retrospective
# ===========================================================================


def test_region_assignment_is_explainable_and_derivative_first():
    falling, d = assign_region(SkyVector(pressure_trend_6h=-0.8, pressure_norm_deviation=-0.4))
    assert falling.id == "collapsing_barometer"
    assert d < 0.2
    rising, _ = assign_region(SkyVector(pressure_trend_6h=0.8, pressure_norm_deviation=0.4))
    assert rising.id == "rising_barometer"
    # Same temperature, opposite derivative, different region. The thesis.
    cold_falling, _ = assign_region(
        SkyVector(temp_norm_deviation=-0.72, pressure_trend_6h=-0.85, pressure_norm_deviation=-0.45)
    )
    cold_settled, _ = assign_region(SkyVector(**_REGION_SKIES["first_frost"]))
    assert cold_falling.id != cold_settled.id
    assert cold_settled.id == "first_frost"
    # A sky doing nothing gets no card.
    assert assign_region(SkyVector())[0].id == "slack_water"
    # The assignment can always explain itself.
    assert falling.why(SkyVector(pressure_trend_6h=-0.8))


def test_describe_sonic_speaks_english():
    words = describe_sonic(sonic(valence=0.1, spatiality=0.9, tempo=0.5))
    assert "downcast" in words and "cavernous" in words
    assert "slow" not in words and "quick" not in words  # tempo is unremarkable
    assert describe_sonic(sonic()) == []


def test_retrospective_produces_sensible_cards_for_a_seeded_history():
    playlists, events = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists]
    retro = build_retrospective(USER, records, events)

    assert not retro.cold_start
    assert retro.forges == len(playlists)
    kinds = {c.kind for c in retro.cards}
    for expected in (
        "rain_sound",
        "falling_barometer",
        "first_frost",
        "golden_hour",
        "most_loved_artists",
        "theme_signatures",
        "sky_streak",
    ):
        assert expected in kinds, f"missing the {expected} card"

    # Every card says something, and says how much it is standing on.
    for card in retro.cards:
        assert card.headline.strip() and card.body.strip()
        assert card.headline[0].isupper() or card.headline[0].isdigit()
        assert card.headline.endswith(".")
        assert 0.0 <= card.confidence <= 1.0
        assert card.sample_size > 0


def test_rain_sound_is_keyed_on_real_precipitation_and_reads_true():
    playlists, events = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists]
    retro = build_retrospective(USER, records, events)

    rain = retro.card("rain_sound")
    assert rain is not None
    assert rain.region_id == "deluge"
    assert rain.signature is not None
    # The fixture's rain taste is dark, wide and acoustic; the card must agree.
    assert rain.signature.valence < 0.35
    assert rain.signature.spatiality > 0.7
    assert not rain.inferred_from_targets, "there are loves; this is taste, not exposure"
    assert "Låpsley" in rain.artists


def test_falling_barometer_card_is_distinct_from_the_rain_card():
    playlists, events = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists]
    retro = build_retrospective(USER, records, events)

    rain = retro.card("rain_sound")
    glass = retro.card("falling_barometer")
    assert rain is not None and glass is not None
    assert glass.region_id == "collapsing_barometer"
    assert glass.signature is not None and rain.signature is not None
    # Different weather, different record. If these ever collapse into each
    # other the product's central claim is not being expressed.
    assert glass.signature.as_array() != rain.signature.as_array()
    assert glass.signature.grit > rain.signature.grit
    assert "Godspeed" in glass.artists


def test_first_frost_card_names_a_record():
    playlists, events = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists]
    retro = build_retrospective(USER, records, events)

    frost = retro.card("first_frost")
    assert frost is not None
    assert frost.tracks
    assert frost.tracks[0].artist == "Arvo Pärt"
    assert frost.tracks[0].loves >= 1
    assert "Arvo Pärt" in frost.headline


def test_most_loved_artists_ranks_by_loves_net_of_skips():
    playlists, events = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists]
    retro = build_retrospective(USER, records, events)

    card = retro.card("most_loved_artists")
    assert card is not None
    # "Session Band" is only ever skipped and must not appear.
    assert "Session Band" not in card.artists
    assert set(card.artists) <= {"Låpsley", "Godspeed", "Arvo Pärt", "Khruangbin"}


def test_theme_signature_card_pairs_a_theme_with_an_artist():
    playlists, events = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists]
    retro = build_retrospective(USER, records, events)

    card = retro.card("theme_signatures")
    assert card is not None
    assert not card.inferred_from_targets
    assert "theme-deluge: Låpsley" in card.body
    assert "theme-first_frost: Arvo Pärt" in card.body


def test_sky_streak_reports_drift_across_the_season():
    playlists, events = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists]
    retro = build_retrospective(USER, records, events)

    streak = retro.card("sky_streak")
    assert streak is not None
    assert streak.sample_size == len(records)
    assert set(streak.stats) == set(SONIC_DIMS)
    # The fixture walks from rain-dark to golden-hour-bright, so valence rises.
    assert streak.stats["valence"] > 0


def test_retrospective_degrades_gracefully_with_two_forges():
    playlists, events = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists][:2]
    keep = {r.playlist_id for r in records}
    thin = [e for e in events if e.playlist_id in keep]

    retro = build_retrospective(USER, records, thin)
    assert retro.cold_start
    assert retro.cards == []
    assert retro.forges == 2
    assert retro.notes
    # Honest and small: no claim about a rain sound, no invented personality.
    assert "rain sound" not in retro.headline.lower()
    assert str(COLD_START_FORGES) in retro.body
    assert retro.headline.endswith(".")


def test_retrospective_with_no_history_at_all():
    retro = build_retrospective(USER, [], [])
    assert retro.cold_start
    assert retro.forges == 0
    assert retro.cards == []
    assert "Forge something." in retro.body


def test_retrospective_without_feedback_is_flagged_as_exposure_not_taste():
    playlists, _ = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists]
    retro = build_retrospective(USER, records, [])
    assert not retro.cold_start
    rain = retro.card("rain_sound")
    assert rain is not None
    assert rain.inferred_from_targets
    assert "not loved enough" in rain.body or "engine aimed at" in rain.body
    # No loves means no most-loved-artists card, rather than a fabricated one.
    assert retro.card("most_loved_artists") is None


def test_retrospective_is_deterministic():
    playlists, events = seeded_history(per_region=4)
    records = [ForgeRecord.from_playlist(p) for p in playlists]
    a = build_retrospective(USER, records, events)
    b = build_retrospective(USER, records, events)
    assert a.to_json_dict() == b.to_json_dict()


def test_retrospective_includes_the_learned_lean_when_one_exists():
    records, events = barometer_training_history(n=48)
    doc = fit_nudge(records, events)
    assert doc is not None
    retro = build_retrospective(USER, records, events, nudge=doc)
    lean = retro.card("learned_lean")
    assert lean is not None
    assert "pressure_trend_6h" in lean.body
    assert lean.sample_size == doc.samples


def test_retrospective_for_reads_straight_off_the_store():
    from backend.app.almanac.retrospective import retrospective_for

    playlists, events = seeded_history(per_region=4)
    store = MemoryAlmanac().seed(playlists).seed_feedback(events)
    retro = run(retrospective_for(store, USER))
    assert not retro.cold_start
    assert retro.forges == len(playlists)
    assert retro.card("rain_sound") is not None


# ===========================================================================
# 5. Tunables live in one place
# ===========================================================================


def test_learning_tunables_are_sane():
    assert 0.0 < learning.SKIP_STEP < learning.LOVE_STEP < 1.0
    assert 0.0 < learning.SKIP_WEIGHT < learning.LOVE_WEIGHT
    assert learning.MIN_SAMPLES >= 8
    assert learning.DEFAULT_LAMBDA > 0.0
    assert 0.0 < learning.MAX_COEFFICIENT <= 0.1
    assert learning.COLUMN_L1_BUDGET <= 9 * learning.MAX_COEFFICIENT
