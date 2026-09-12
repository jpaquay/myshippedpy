"""Tests for the sonic subsystem: matrix, themes, corridors, target, rationale.

No network, no fixtures on disk, no clock dependence. Everything here is pure
arithmetic over frozen models, which is the whole reason the transfer function
was built as a table of numbers rather than a pile of if-statements.

The important tests in this file are the **directional** ones. Shape assertions
only prove the matrix is 9x7; they say nothing about whether it is *right*.
Every strong claim made in a comment in ``matrix.py`` is restated here as an
executable assertion, so that retuning a coefficient in a way that contradicts
its own stated argument breaks the build rather than quietly shipping.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# The app package lives under backend/. Self-bootstrapping keeps this file
# runnable on its own (`pytest barogroove/tests/test_sonic.py`) without
# depending on a conftest.py that another part of the tree owns.
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.contracts import (  # noqa: E402
    SKY_DIMS,
    SONIC_DIMS,
    THEME_IDS,
    GenreCorridor,
    SkyVector,
    SonicVector,
    TasteVector,
)
from app.errors import ThemeNotFound  # noqa: E402
from app.sonic.corridors import CORRIDORS, get_corridor, list_corridors  # noqa: E402
from app.sonic.matrix import (  # noqa: E402
    BASE_SONIC,
    MATRIX_VERSION,
    SKY_TO_SONIC,
    TRANSFER_MATRIX,
    apply_transfer,
    coefficient,
    explain_transfer,
)
from app.sonic.rationale import build_rationale, short_headline  # noqa: E402
from app.sonic.target import build_target  # noqa: E402
from app.sonic.themes import (  # noqa: E402
    THEMES,
    get_theme,
    list_themes,
    suggest_theme,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sky(**kwargs: float) -> SkyVector:
    """A sky with everything at zero except what the test cares about."""
    return SkyVector(**kwargs)


NEUTRAL = SkyVector.neutral()


def rich_taste(**overrides: object) -> TasteVector:
    payload: dict[str, object] = {
        "centroid": SonicVector(
            valence=0.40, energy=0.45, tempo=0.38, acousticness=0.60,
            density=0.40, grit=0.50, spatiality=0.72,
        ),
        "spread": SonicVector(
            valence=0.18, energy=0.20, tempo=0.16, acousticness=0.22,
            density=0.20, grit=0.24, spatiality=0.18,
        ),
        "top_tags": {"shoegaze": 1.0, "slowcore": 0.8},
        "top_artists": ["Talk Talk", "Bark Psychosis", "Slowdive"],
        "scrobble_count": 8213,
        "confidence": 0.84,
        "source": "lastfm",
    }
    payload.update(overrides)
    return TasteVector(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Matrix: shape and provenance
# ---------------------------------------------------------------------------


class TestMatrixShape:
    def test_dense_matrix_is_9x7(self) -> None:
        assert len(TRANSFER_MATRIX) == len(SKY_DIMS) == 9
        assert all(len(row) == len(SONIC_DIMS) == 7 for row in TRANSFER_MATRIX)

    def test_legible_table_and_dense_matrix_agree(self) -> None:
        """The dict is the source of truth; the grid is derived. They must match.

        This is the test that lets the matrix stay readable: it guarantees the
        thing a human edits and the thing the arithmetic uses can never drift.
        """
        assert set(SKY_TO_SONIC) == set(SKY_DIMS)
        for i, sky_dim in enumerate(SKY_DIMS):
            for j, sonic_dim in enumerate(SONIC_DIMS):
                expected = SKY_TO_SONIC[sky_dim].get(sonic_dim, 0.0)
                assert TRANSFER_MATRIX[i][j] == pytest.approx(expected), (
                    f"{sky_dim} -> {sonic_dim} disagrees"
                )
                assert coefficient(sky_dim, sonic_dim) == pytest.approx(expected)

    def test_table_declares_no_unknown_dimensions(self) -> None:
        for sky_dim, row in SKY_TO_SONIC.items():
            assert sky_dim in SKY_DIMS
            assert set(row) <= set(SONIC_DIMS)

    def test_coefficients_stay_small_and_interpretable(self) -> None:
        """The intercept carries the level; coefficients only carry deflection.

        A coefficient above 0.35 would mean one weather dim could swing a
        musical dim across two-thirds of its range on its own, which is the
        point at which the model stops being a blend and starts being a switch.
        """
        for i, sky_dim in enumerate(SKY_DIMS):
            for j, sonic_dim in enumerate(SONIC_DIMS):
                assert abs(TRANSFER_MATRIX[i][j]) <= 0.35, f"{sky_dim} -> {sonic_dim} too large"

    def test_matrix_has_deliberate_zeros(self) -> None:
        """Some cells are zero on purpose. A fully dense matrix is unconsidered."""
        zeros = sum(1 for row in TRANSFER_MATRIX for value in row if value == 0.0)
        assert zeros >= 5

    def test_version_is_fingerprinted(self) -> None:
        assert MATRIX_VERSION.startswith("1.0.0+")
        assert re.fullmatch(r"1\.0\.0\+[0-9a-f]{8}", MATRIX_VERSION)

    def test_neutral_sky_returns_the_intercept(self) -> None:
        """Zero sky, zero deflection: the transfer must reproduce BASE_SONIC exactly."""
        assert apply_transfer(NEUTRAL).as_array() == pytest.approx(BASE_SONIC.as_array())


# ---------------------------------------------------------------------------
# Matrix: the directional claims. These are the tests that matter.
# ---------------------------------------------------------------------------


class TestDirectionalClaims:
    """Each test here restates a claim argued in a comment in ``matrix.py``."""

    def test_falling_pressure_lowers_valence(self) -> None:
        """THE key property. Same sky twice, opposite barometer, different feeling.

        This single assertion is the difference between BAROGROOVE and every
        `rain -> sad songs` toy: the absolute weather is *identical* in both
        readings and only the derivative differs.
        """
        common = dict(cloud_depth=0.5, temp_norm_deviation=-0.2, sun_elevation=0.3)
        falling = apply_transfer(sky(pressure_trend_6h=-0.8, **common))
        rising = apply_transfer(sky(pressure_trend_6h=+0.8, **common))

        assert falling.valence < rising.valence
        # "Materially different" has to mean something. A fifth of the range.
        assert rising.valence - falling.valence > 0.20

    def test_falling_pressure_raises_reverb(self) -> None:
        """Low pressure carries sound further, so the music gets room."""
        falling = apply_transfer(sky(pressure_trend_6h=-0.8))
        rising = apply_transfer(sky(pressure_trend_6h=+0.8))
        assert falling.spatiality > rising.spatiality
        assert falling.spatiality - rising.spatiality > 0.15

    def test_falling_pressure_lowers_tempo(self) -> None:
        """The pre-frontal slump, in BPM."""
        falling = apply_transfer(sky(pressure_trend_6h=-0.8))
        rising = apply_transfer(sky(pressure_trend_6h=+0.8))
        assert falling.tempo_bpm < rising.tempo_bpm
        assert rising.tempo_bpm - falling.tempo_bpm > 15.0

    def test_falling_pressure_empties_the_arrangement(self) -> None:
        """The pre-frontal hush: pressure owns space, gusts own density."""
        falling = apply_transfer(sky(pressure_trend_6h=-0.8))
        rising = apply_transfer(sky(pressure_trend_6h=+0.8))
        assert falling.density < rising.density

    def test_gust_variance_raises_density_and_grit(self) -> None:
        """Unsettled air wants texture and event density, not volume."""
        still = apply_transfer(sky(gust_variance=0.0))
        gusty = apply_transfer(sky(gust_variance=1.0))
        assert gusty.density > still.density
        assert gusty.grit > still.grit
        assert gusty.density - still.density > 0.10
        assert gusty.grit - still.grit > 0.10

    def test_sun_elevation_raises_energy(self) -> None:
        """The obvious one, and the only obvious one the table allows."""
        night = apply_transfer(sky(sun_elevation=-1.0))
        noon = apply_transfer(sky(sun_elevation=+1.0))
        assert noon.energy > night.energy
        assert noon.energy - night.energy > 0.25

    def test_darkness_raises_reverb(self) -> None:
        """You cannot see the walls, so the music expands to fill the room."""
        night = apply_transfer(sky(sun_elevation=-1.0))
        noon = apply_transfer(sky(sun_elevation=+1.0))
        assert night.spatiality > noon.spatiality

    def test_golden_hour_is_warm_but_not_fast(self) -> None:
        """Warm and slow is not the same axis as happy and fast.

        Valence up, tempo *down*, from a single dim. If a refactor ever makes
        these two agree in sign, the model has lost the distinction that most
        justifies having seven dimensions instead of one mood slider.
        """
        plain = apply_transfer(sky(golden_hour_proximity=0.0))
        golden = apply_transfer(sky(golden_hour_proximity=1.0))

        assert golden.valence > plain.valence
        assert golden.tempo < plain.tempo
        # ...and warmth must stay modest, or the app serves sunshine pop at dusk.
        assert golden.valence - plain.valence < 0.13

    def test_rain_is_enclosing_not_sad(self) -> None:
        """Rain barely touches valence; it moves acousticness and reverb instead."""
        dry = apply_transfer(sky(precip_intensity=0.0))
        wet = apply_transfer(sky(precip_intensity=1.0))

        assert wet.acousticness > dry.acousticness
        assert wet.spatiality > dry.spatiality
        # The naive mapping would put its whole weight here. We do not.
        assert abs(wet.valence - dry.valence) < 0.10
        assert (wet.acousticness - dry.acousticness) > abs(wet.valence - dry.valence)

    def test_cold_reads_acoustic(self) -> None:
        """Wood and breath when it is raw; voltage when it is warm."""
        raw = apply_transfer(sky(temp_norm_deviation=-1.0))
        mild = apply_transfer(sky(temp_norm_deviation=+1.0))
        assert raw.acousticness > mild.acousticness
        assert mild.valence > raw.valence

    def test_pressure_trend_outweighs_pressure_level(self) -> None:
        """The derivative-first thesis, as an inequality.

        You habituate to a level within a day and never habituate to a change,
        so every trend coefficient must beat its level counterpart.
        """
        for sonic_dim in ("valence", "spatiality"):
            trend = abs(coefficient("pressure_trend_6h", sonic_dim))
            level = abs(coefficient("pressure_norm_deviation", sonic_dim))
            assert trend > level, f"{sonic_dim}: level is outweighing trend"

    def test_year_closing_differs_from_year_opening(self) -> None:
        """Identical cold clear morning in March and October. Different record."""
        march = apply_transfer(sky(temp_norm_deviation=-0.5, daylight_delta=+1.0))
        october = apply_transfer(sky(temp_norm_deviation=-0.5, daylight_delta=-1.0))
        assert march.valence > october.valence
        assert march.distance(october) > 0.02


# ---------------------------------------------------------------------------
# Matrix: ranges, nudge, explanation
# ---------------------------------------------------------------------------


def _extreme_skies() -> list[SkyVector]:
    """Corner cases plus every single-dim extreme, for range fuzzing."""
    signed = {"pressure_trend_6h", "pressure_norm_deviation", "temp_norm_deviation",
              "sun_elevation", "daylight_delta"}
    out = [NEUTRAL]
    for dim in SKY_DIMS:
        lows = (-1.0, 1.0) if dim in signed else (0.0, 1.0)
        for value in lows:
            out.append(sky(**{dim: value}))
    # All dims slammed to both rails at once: the worst case for the squash.
    out.append(SkyVector(**{d: (-1.0 if d in signed else 0.0) for d in SKY_DIMS}))
    out.append(SkyVector(**{d: 1.0 for d in SKY_DIMS}))
    return out


class TestRanges:
    @pytest.mark.parametrize("candidate", _extreme_skies())
    def test_all_outputs_stay_in_unit_range(self, candidate: SkyVector) -> None:
        result = apply_transfer(candidate)
        for dim, value in result.as_dict().items():
            assert 0.0 <= value <= 1.0, f"{dim} escaped the unit range at {value}"

    def test_tempo_denormalises_into_the_declared_bpm_band(self) -> None:
        for candidate in _extreme_skies():
            assert 60.0 <= apply_transfer(candidate).tempo_bpm <= 180.0

    def test_squash_preserves_ordering_past_the_rails(self) -> None:
        """A worse sky must always score lower, even out where clamping would tie."""
        bad = apply_transfer(sky(pressure_trend_6h=-1.0, cloud_depth=1.0, precip_intensity=1.0))
        worse = apply_transfer(
            sky(pressure_trend_6h=-1.0, cloud_depth=1.0, precip_intensity=1.0,
                temp_norm_deviation=-1.0, daylight_delta=-1.0, sun_elevation=-1.0)
        )
        assert worse.valence < bad.valence


class TestNudge:
    def test_nudge_shifts_the_result(self) -> None:
        target_sky = sky(pressure_trend_6h=-0.6)
        base = apply_transfer(target_sky)
        # Flatten every valence coefficient: a user who does not want the sky
        # dictating their mood.
        nudge = [
            [-SKY_TO_SONIC[d].get(s, 0.0) if s == "valence" else 0.0 for s in SONIC_DIMS]
            for d in SKY_DIMS
        ]
        nudged = apply_transfer(target_sky, nudge=nudge)
        assert nudged.valence == pytest.approx(BASE_SONIC.valence, abs=1e-6)
        assert nudged.valence != pytest.approx(base.valence)
        # ...and nothing else moved.
        assert nudged.spatiality == pytest.approx(base.spatiality)

    def test_malformed_nudge_is_rejected_loudly(self) -> None:
        with pytest.raises(ValueError):
            apply_transfer(NEUTRAL, nudge=[[0.0] * 7] * 3)
        with pytest.raises(ValueError):
            apply_transfer(NEUTRAL, nudge=[[0.0] * 2] * 9)


class TestExplain:
    def test_explain_returns_the_dominant_terms(self) -> None:
        candidate = sky(pressure_trend_6h=-0.9, cloud_depth=0.3)
        result = apply_transfer(candidate)
        terms = explain_transfer(candidate, result, top_n=3)

        assert len(terms) == 3
        assert terms[0][0] == "pressure_trend_6h"
        # Sorted by absolute contribution, descending.
        magnitudes = [abs(t[2]) for t in terms]
        assert magnitudes == sorted(magnitudes, reverse=True)
        for sky_dim, sonic_dim, _ in terms:
            assert sky_dim in SKY_DIMS
            assert sonic_dim in SONIC_DIMS

    def test_explanation_is_deterministic(self) -> None:
        candidate = sky(pressure_trend_6h=-0.5, gust_variance=0.6)
        result = apply_transfer(candidate)
        assert explain_transfer(candidate, result) == explain_transfer(candidate, result)

    def test_contributions_reconcile_with_the_actual_output(self) -> None:
        """Reported terms for a dim must sum to the deflection you can see.

        This is what makes the hero card's numbers checkable rather than
        decorative -- explain_transfer rescales for squash compression so the
        arithmetic on screen actually adds up.
        """
        candidate = sky(pressure_trend_6h=-0.7, cloud_depth=0.8, gust_variance=0.5)
        result = apply_transfer(candidate)
        terms = explain_transfer(candidate, result, top_n=63)

        for j, sonic_dim in enumerate(SONIC_DIMS):
            reported = sum(c for _, dim, c in terms if dim == sonic_dim)
            actual = result.as_array()[j] - BASE_SONIC.as_array()[j]
            assert reported == pytest.approx(actual, abs=5e-3), sonic_dim

    def test_neutral_sky_explains_nothing(self) -> None:
        assert explain_transfer(NEUTRAL, apply_transfer(NEUTRAL)) == []


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------


class TestThemes:
    def test_all_eight_present_and_in_contract_order(self) -> None:
        assert set(THEMES) == set(THEME_IDS)
        assert [t.id for t in list_themes()] == list(THEME_IDS)

    @pytest.mark.parametrize("theme_id", THEME_IDS)
    def test_theme_is_fully_populated(self, theme_id: str) -> None:
        theme = get_theme(theme_id)
        assert theme.name and theme.tagline and theme.description
        assert len(theme.description) > 120, "descriptions must have something to say"
        assert len(theme.seed_tags) >= 5
        assert len(theme.avoid_tags) >= 3
        assert 4 <= len(theme.palette) <= 6
        assert theme.voice
        assert theme.affinity
        assert 0.0 <= theme.bias_weight <= 1.0

    @pytest.mark.parametrize("theme_id", THEME_IDS)
    def test_palette_entries_are_hex_colours(self, theme_id: str) -> None:
        for name, colour in get_theme(theme_id).palette.items():
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", colour), f"{theme_id}.{name} = {colour}"

    @pytest.mark.parametrize("theme_id", THEME_IDS)
    def test_affinity_only_references_real_sky_dims(self, theme_id: str) -> None:
        assert set(get_theme(theme_id).affinity) <= set(SKY_DIMS)

    def test_biases_are_all_distinct(self) -> None:
        """Eight themes that resolve to the same vector would be one theme."""
        themes = list_themes()
        for i, first in enumerate(themes):
            for second in themes[i + 1:]:
                assert first.bias.distance(second.bias) > 0.05, (
                    f"{first.id} and {second.id} are too close to be different themes"
                )

    def test_seed_and_avoid_tags_never_overlap(self) -> None:
        for theme in list_themes():
            assert not set(theme.seed_tags) & set(theme.avoid_tags), theme.id

    def test_unknown_theme_raises(self) -> None:
        with pytest.raises(ThemeNotFound):
            get_theme("drizzlecore")


class TestSuggestTheme:
    def test_storm_sky_picks_a_storm_reading(self) -> None:
        storm = sky(
            pressure_trend_6h=-0.85, pressure_norm_deviation=-0.55,
            gust_variance=0.80, cloud_depth=0.75, precip_intensity=0.65, sun_elevation=0.20,
        )
        theme, confidence = suggest_theme(storm)
        assert theme.id in {"storm_front", "petrichor"}
        assert confidence > 0.5

    def test_clear_cold_dawn_picks_first_frost(self) -> None:
        frost = sky(
            temp_norm_deviation=-0.80, pressure_trend_6h=0.50, pressure_norm_deviation=0.60,
            cloud_depth=0.05, gust_variance=0.05, sun_elevation=0.12, daylight_delta=-0.50,
        )
        theme, confidence = suggest_theme(frost)
        assert theme.id == "first_frost"
        assert confidence > 0.4

    def test_hot_clear_afternoon_picks_the_heatwave(self) -> None:
        heat = sky(temp_norm_deviation=0.90, sun_elevation=0.80, cloud_depth=0.05, gust_variance=0.10)
        assert suggest_theme(heat)[0].id == "heatwave_cruise"

    def test_still_deep_cloud_picks_the_fog(self) -> None:
        fog = sky(cloud_depth=0.95, gust_variance=0.02, temp_norm_deviation=-0.30, sun_elevation=0.10)
        assert suggest_theme(fog)[0].id == "nordic_fog"

    def test_windy_daytime_cloudy_sky_does_not_pick_nordic_fog(self) -> None:
        windy_cloudy = sky(
            cloud_depth=0.88,
            gust_variance=0.44,
            sun_elevation=0.35,
            pressure_norm_deviation=0.50,
            temp_norm_deviation=-0.10,
        )
        assert suggest_theme(windy_cloudy)[0].id != "nordic_fog"

    def test_golden_and_blue_hour_are_separated_by_the_sun(self) -> None:
        """Both live in the same window; only the sign of the elevation splits them."""
        golden = sky(golden_hour_proximity=0.95, sun_elevation=0.06, temp_norm_deviation=0.30)
        blue = sky(golden_hour_proximity=0.80, sun_elevation=-0.15, daylight_delta=-0.30)
        assert suggest_theme(golden)[0].id == "golden_hour"
        assert suggest_theme(blue)[0].id == "blue_hour"

    def test_neutral_sky_yields_low_confidence(self) -> None:
        """No opinion is the right amount of confidence to have about nothing."""
        _, confidence = suggest_theme(NEUTRAL)
        assert confidence <= 0.2

    def test_stale_sky_costs_confidence(self) -> None:
        storm_kwargs = dict(
            pressure_trend_6h=-0.85, gust_variance=0.80,
            cloud_depth=0.75, precip_intensity=0.65,
        )
        fresh = suggest_theme(SkyVector(**storm_kwargs))[1]
        stale = suggest_theme(SkyVector(stale=True, **storm_kwargs))[1]
        assert stale < fresh


# ---------------------------------------------------------------------------
# Corridors
# ---------------------------------------------------------------------------


class TestCorridors:
    def test_at_least_fourteen_corridors(self) -> None:
        assert len(CORRIDORS) >= 14

    def test_expected_corridors_exist(self) -> None:
        expected = {
            "any", "krautrock", "ambient", "shoegaze", "post-punk", "dub-techno",
            "spiritual-jazz", "folk", "soul", "indie-rock", "drone", "hip-hop",
            "electronica", "modern-composition", "desert-blues", "slowcore",
        }
        assert expected <= set(CORRIDORS)

    def test_any_is_listed_first_and_unconstrained(self) -> None:
        corridors = list_corridors()
        assert corridors[0].id == "any"
        assert corridors[0].anchor is None
        assert corridors[0].width == 1.0

    @pytest.mark.parametrize("corridor_id", sorted(set(CORRIDORS) - {"any"}))
    def test_real_corridors_are_well_formed(self, corridor_id: str) -> None:
        corridor = CORRIDORS[corridor_id]
        assert corridor.anchor is not None
        assert len(corridor.tags) >= 4
        assert 0.05 <= corridor.width <= 1.0
        assert len(corridor.description) > 40

    def test_anchors_are_distinct(self) -> None:
        real = [c for c in list_corridors() if c.anchor is not None]
        for i, first in enumerate(real):
            for second in real[i + 1:]:
                assert first.anchor.distance(second.anchor) > 0.03, (  # type: ignore[union-attr]
                    f"{first.id} and {second.id} anchor in the same place"
                )

    def test_unknown_genre_falls_back_rather_than_raising(self) -> None:
        """An unrecognised filter must never kill a forge."""
        assert get_corridor("krautrok").id == "any"
        assert get_corridor(None).id == "any"
        assert get_corridor("").id == "any"

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("post punk", "post-punk"),
            ("POSTPUNK", "post-punk"),
            ("Dub Techno", "dub-techno"),
            ("idm", "electronica"),
            ("classical", "modern-composition"),
            ("  Krautrock  ", "krautrock"),
        ],
    )
    def test_alias_resolution(self, given: str, expected: str) -> None:
        assert get_corridor(given).id == expected


# ---------------------------------------------------------------------------
# Target pipeline
# ---------------------------------------------------------------------------


STORMY = SkyVector(
    pressure_trend_6h=-0.77, cloud_depth=0.72, golden_hour_proximity=0.58,
    sun_elevation=0.05, temp_norm_deviation=-0.34, daylight_delta=-0.45,
    gust_variance=0.32, precip_intensity=0.15,
    notes=["pressure fell 9.2 hPa since noon"],
)


class TestBuildTarget:
    def test_theme_only_mode_works(self) -> None:
        """taste=None is a first-class path, not an error branch."""
        target, moves = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("any"), taste=None
        )
        assert isinstance(target, SonicVector)
        for value in target.as_array():
            assert 0.0 <= value <= 1.0
        assert moves
        assert any("theme" in m.lower() or "sky" in m.lower() for m in moves)

    def test_moves_are_human_readable_and_ordered(self) -> None:
        _, moves = build_target(
            STORMY, theme=get_theme("storm_front"), corridor=get_corridor("krautrock"),
            taste=rich_taste(),
        )
        assert len(moves) >= 4
        assert moves[0].startswith("Sky alone")
        assert moves[-1].startswith("Final target")
        for move in moves:
            assert move.endswith(".")
            assert len(move) > 25

    @pytest.mark.parametrize("theme_id", THEME_IDS)
    @pytest.mark.parametrize("corridor_id", ["any", "ambient", "krautrock", "drone"])
    def test_every_combination_stays_in_range(self, theme_id: str, corridor_id: str) -> None:
        target, _ = build_target(
            STORMY, theme=get_theme(theme_id), corridor=get_corridor(corridor_id),
            taste=rich_taste(),
        )
        for dim, value in target.as_dict().items():
            assert 0.0 <= value <= 1.0, dim

    def test_narrow_corridor_actually_constrains(self) -> None:
        """Width is a radius. After the projection the target must be inside it."""
        for corridor_id in ("drone", "ambient", "folk", "hip-hop"):
            corridor = get_corridor(corridor_id)
            target, _ = build_target(
                STORMY, theme=get_theme("storm_front"), corridor=corridor, taste=rich_taste()
            )
            assert corridor.anchor is not None
            assert target.distance(corridor.anchor) <= corridor.width + 1e-6

    def test_thin_taste_does_not_drag_the_target(self) -> None:
        """A handful of scrobbles must not outvote the weather."""
        thin = rich_taste(scrobble_count=9, confidence=0.2)
        without, _ = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("any"), taste=None
        )
        with_thin, moves = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("any"), taste=thin
        )
        assert without.distance(with_thin) < 0.03
        assert any("thin" in m.lower() for m in moves)

    def test_rich_taste_does_move_the_target(self) -> None:
        without, _ = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("any"), taste=None
        )
        with_taste, _ = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("any"), taste=rich_taste()
        )
        assert without.distance(with_taste) > 0.02

    def test_taste_never_takes_over(self) -> None:
        """Even a maximal profile leaves the weather holding the casting vote."""
        maximal = rich_taste(
            scrobble_count=500_000,
            confidence=1.0,
            spread=SonicVector(**{d: 0.0 for d in SONIC_DIMS}),
        )
        without, _ = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("any"), taste=None
        )
        with_taste, _ = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("any"), taste=maximal
        )
        centroid = maximal.centroid
        # The target must remain strictly closer to the sky-and-theme answer
        # than to the user's own centre of gravity.
        assert with_taste.distance(without) < without.distance(centroid)


class TestOrthogonality:
    """Theme and genre are separate knobs. This is the headline feature."""

    def test_same_theme_two_corridors_diverge(self) -> None:
        """'Petrichor x krautrock' must not be 'Petrichor x ambient'."""
        kraut, _ = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("krautrock")
        )
        ambient, _ = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("ambient")
        )
        assert kraut.distance(ambient) > 0.05
        assert abs(kraut.tempo_bpm - ambient.tempo_bpm) > 8.0
        assert abs(kraut.density - ambient.density) > 0.05

    def test_same_corridor_two_themes_diverge(self) -> None:
        """And the corridor must not flatten the theme out of existence."""
        petrichor, _ = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("krautrock")
        )
        storm, _ = build_target(
            STORMY, theme=get_theme("storm_front"), corridor=get_corridor("krautrock")
        )
        assert petrichor.distance(storm) > 0.02

    def test_the_full_crossing_is_mostly_unique(self) -> None:
        """8 themes x 6 corridors should not collapse into a handful of results."""
        seen: list[SonicVector] = []
        for theme_id in THEME_IDS:
            for corridor_id in ("any", "ambient", "krautrock", "folk", "hip-hop", "shoegaze"):
                target, _ = build_target(
                    STORMY, theme=get_theme(theme_id), corridor=get_corridor(corridor_id)
                )
                seen.append(target)
        for i, first in enumerate(seen):
            for second in seen[i + 1:]:
                assert first.distance(second) > 1e-6


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------

DIGIT = re.compile(r"\d")


class TestRationale:
    def _build(self, candidate: SkyVector = STORMY, **overrides: object):
        theme = overrides.pop("theme", None) or get_theme("petrichor")
        corridor = overrides.pop("corridor", None) or get_corridor("ambient")
        taste = overrides.pop("taste", "default")
        taste_vector = rich_taste() if taste == "default" else taste
        target, moves = build_target(
            candidate, theme=theme, corridor=corridor, taste=taste_vector  # type: ignore[arg-type]
        )
        return build_rationale(
            sky=candidate, sonic=target, theme=theme, corridor=corridor,
            taste=taste_vector, moves=moves, **overrides,  # type: ignore[arg-type]
        )

    def test_body_cites_real_numbers(self) -> None:
        rationale = self._build()
        assert DIGIT.search(rationale.body)
        assert "hPa" in rationale.body
        assert re.search(r"\d+\.\d+ hPa", rationale.body)

    def test_units_survive_capitalisation(self) -> None:
        """'hPa' must never come back as 'hpa'. str.capitalize is banned here."""
        rationale = self._build()
        assert "hpa" not in rationale.body
        assert "degc" not in rationale.body.lower().replace("degC", "")

    def test_headline_quotes_a_tempo(self) -> None:
        rationale = self._build()
        assert "BPM" in rationale.headline
        assert DIGIT.search(rationale.headline)

    def test_deterministic_for_a_fixed_sky(self) -> None:
        first = self._build()
        second = self._build()
        assert first.headline == second.headline
        assert first.body == second.body
        assert first.taste_note == second.taste_note
        assert first.sky_reading == second.sky_reading

    def test_different_skies_read_differently(self) -> None:
        """Deterministic, but not a stencil."""
        other = STORMY.model_copy(
            update={"pressure_trend_6h": 0.62, "cloud_depth": 0.18,
                    "temp_norm_deviation": 0.55, "notes": []}
        )
        assert self._build().body != self._build(other).body

    def test_taste_note_names_a_real_artist(self) -> None:
        rationale = self._build()
        assert any(artist in rationale.taste_note for artist in rich_taste().top_artists)

    def test_theme_only_mode_says_so_and_costs_confidence(self) -> None:
        with_taste = self._build()
        without = self._build(taste=None)

        assert without.degraded, "a missing pairing must never be hidden"
        assert any("theme-only" in line.lower() for line in without.degraded)
        assert without.confidence < with_taste.confidence

    def test_degraded_ledger_is_translated_to_plain_language(self) -> None:
        rationale = self._build(degraded=["lastfm: no user paired", "spotify: not connected"])
        joined = " ".join(rationale.degraded)
        assert "Last.fm" in joined
        assert "M3U" in joined
        # No raw subsystem prefixes leaking to the user.
        assert "lastfm:" not in joined

    def test_unknown_subsystem_still_surfaces(self) -> None:
        rationale = self._build(degraded=["gizmo: exploded"])
        assert any("exploded" in line for line in rationale.degraded)

    def test_stale_sky_lowers_confidence_and_is_announced(self) -> None:
        fresh = self._build()
        stale = self._build(STORMY.model_copy(update={"stale": True}))
        assert stale.confidence < fresh.confidence
        assert any("last sky" in line.lower() for line in stale.sky_reading)

    def test_extractor_notes_are_surfaced_verbatim(self) -> None:
        rationale = self._build()
        assert "pressure fell 9.2 hPa since noon" in rationale.sky_reading

    def test_sonic_moves_are_populated_from_the_pipeline(self) -> None:
        rationale = self._build()
        assert rationale.sonic_moves
        assert any("BPM" in move for move in rationale.sonic_moves)

    def test_sonic_moves_fall_back_to_the_matrix_explanation(self) -> None:
        """Without the pipeline's narration the card gets thinner, never empty."""
        target, _ = build_target(
            STORMY, theme=get_theme("petrichor"), corridor=get_corridor("any")
        )
        rationale = build_rationale(
            sky=STORMY, sonic=target, theme=get_theme("petrichor"),
            corridor=get_corridor("any"), moves=None,
        )
        assert rationale.sonic_moves
        assert any(DIGIT.search(move) for move in rationale.sonic_moves)

    @pytest.mark.parametrize("theme_id", THEME_IDS)
    def test_every_theme_voice_produces_prose(self, theme_id: str) -> None:
        rationale = self._build(theme=get_theme(theme_id))
        assert len(rationale.body) > 120
        assert rationale.body.endswith(("." , "!", "?"))
        assert 0.0 <= rationale.confidence <= 1.0

    def test_neutral_sky_does_not_invent_facts(self) -> None:
        rationale = self._build(NEUTRAL, taste=None)
        assert rationale.body
        assert rationale.confidence < 0.7

    def test_short_headline_is_short_and_names_the_theme(self) -> None:
        headline = short_headline(STORMY, get_theme("petrichor"))
        assert "Petrichor" in headline
        assert len(headline) < 90
        assert short_headline(STORMY, get_theme("petrichor")) == headline

    def test_tracks_are_mentioned_when_supplied(self) -> None:
        class _FakeTrack:
            display = "Talk Talk — New Grass"

        rationale = self._build(tracks=[_FakeTrack()])
        assert "New Grass" in rationale.body
