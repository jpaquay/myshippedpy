"""Tests for the SkyVector engine. No network, no clock dependence.

The assertions are deliberately *directional* rather than exact. Pinning
pressure_trend_6h to 0.9046 would turn every future tuning of the tanh knee into a
test failure, which teaches the next person to edit the expectation instead of
thinking. What must never change is the sign and the rough magnitude: a collapsing
barometer is strongly negative, a building ridge is strongly positive, and a dead
flat November afternoon is neither.
"""

from __future__ import annotations

import asyncio
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.contracts import SKY_DIMS, Coordinates, WeatherObservation, WeatherWindow  # noqa: E402
from app.errors import DegradationLedger  # noqa: E402
from app.sky.cache import WeatherWindowCache, cache_key  # noqa: E402
from app.sky.extract import (  # noqa: E402
    daylight_seconds_for,
    extract_sky_vector,
    solar_elevation,
    summarise,
)
from app.sky.fixtures import (  # noqa: E402
    BRUSSELS,
    SCENARIOS,
    FixtureWeatherSource,
    build_window,
)

SIGNED_DIMS = (
    "pressure_trend_6h",
    "pressure_norm_deviation",
    "temp_norm_deviation",
    "sun_elevation",
    "daylight_delta",
)
UNSIGNED_DIMS = (
    "golden_hour_proximity",
    "gust_variance",
    "cloud_depth",
    "precip_intensity",
)


def vector_for(scenario: str):
    window = build_window(scenario)
    return extract_sky_vector(window, at=window.now.time)


# ---------------------------------------------------------------------------
# Scenario directionality — the product thesis, expressed as assertions.
# ---------------------------------------------------------------------------


def test_front_collapse_has_strongly_negative_pressure_trend() -> None:
    v = vector_for("front_collapse")
    assert v.pressure_trend_6h < -0.8, "an 11 hPa fall must dominate the vector"
    assert v.precip_intensity > 0.4, "rain is arriving, not threatened"
    assert v.cloud_depth > 0.8, "saturated low deck"
    assert v.golden_hour_proximity > 0.5, "40 minutes to sunset is inside the band"


def test_ridge_building_has_positive_pressure_trend() -> None:
    v = vector_for("ridge_building")
    assert v.pressure_trend_6h > 0.6
    assert v.pressure_norm_deviation > 0.2, "sitting above its own weekly norm"
    assert v.precip_intensity == 0.0
    assert v.cloud_depth < 0.35


def test_flat_grey_is_flat_on_both_pressure_dims() -> None:
    v = vector_for("flat_grey")
    assert abs(v.pressure_trend_6h) < 0.2, "dead flat means dead flat"
    assert abs(v.pressure_norm_deviation) < 0.45
    assert v.precip_intensity == 0.0
    assert v.cloud_depth > 0.7, "total overcast at high humidity is a lid"
    assert v.gust_variance < 0.3


def test_first_frost_is_below_its_own_norm() -> None:
    v = vector_for("first_frost")
    assert v.temp_norm_deviation < -0.5, "the anomaly is local, not absolute"
    assert v.pressure_norm_deviation > 0.0, "high pressure relative to the week"
    assert v.cloud_depth < 0.25


def test_temp_norm_is_not_just_the_diurnal_cycle() -> None:
    """The local norm must be de-seasonalised for time of day.

    Compared against a flat 7-day mean of all hours, any pre-dawn reading is cold by
    construction and any afternoon reading is warm by construction, everywhere, every
    day. That is not an anomaly, it is a clock — and it would make this dimension a
    noisy copy of sun_elevation. On the deliberately inert scenario both ends of the
    day must therefore read near zero.
    """
    dawn = datetime(2025, 11, 12, 6, 0, tzinfo=timezone.utc)
    afternoon = datetime(2025, 11, 12, 15, 0, tzinfo=timezone.utc)

    cold_hour = extract_sky_vector(build_window("flat_grey", BRUSSELS, dawn), at=dawn)
    warm_hour = extract_sky_vector(build_window("flat_grey", BRUSSELS, afternoon), at=afternoon)

    assert abs(cold_hour.temp_norm_deviation) < 0.35, "a cold dawn is not an anomaly"
    assert abs(warm_hour.temp_norm_deviation) < 0.35, "a mild afternoon is not an anomaly"

    # Genuine anomalies must still survive the same-hour comparison.
    assert vector_for("first_frost").temp_norm_deviation < -0.5
    assert vector_for("heatwave_evening").temp_norm_deviation > 0.5


def test_heatwave_evening_is_above_norm_and_still() -> None:
    v = vector_for("heatwave_evening")
    assert v.temp_norm_deviation > 0.5
    assert v.gust_variance < 0.25, "still air"
    assert v.golden_hour_proximity > 0.5


def test_gusty_front_is_variance_not_trend() -> None:
    v = vector_for("gusty_front")
    assert v.gust_variance > 0.5, "the air cannot make up its mind"
    assert abs(v.pressure_trend_6h) < 0.7, "wobbling, not committing"


def test_scenarios_are_genuinely_distinct() -> None:
    """Six scenarios that produce near-identical vectors would be one scenario."""
    vectors = {name: vector_for(name).as_array() for name in SCENARIOS}
    names = sorted(vectors)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            distance = math.dist(vectors[a], vectors[b])
            assert distance > 0.5, f"{a} and {b} are the same situation ({distance:.2f})"


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_all_dims_inside_declared_ranges(scenario: str) -> None:
    v = vector_for(scenario)
    values = v.as_dict()
    assert set(values) == set(SKY_DIMS)
    for dim in SIGNED_DIMS:
        assert -1.0 <= values[dim] <= 1.0, f"{scenario}.{dim} = {values[dim]}"
    for dim in UNSIGNED_DIMS:
        assert 0.0 <= values[dim] <= 1.0, f"{scenario}.{dim} = {values[dim]}"
    assert all(math.isfinite(x) for x in v.as_array())


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_scenario_produces_a_readable_summary(scenario: str) -> None:
    v = vector_for(scenario)
    summary = summarise(v)
    assert summary.endswith(".")
    assert summary[0].isupper()
    assert v.notes, "the rationale card needs breadcrumbs"


# ---------------------------------------------------------------------------
# Solar position
# ---------------------------------------------------------------------------


def test_brussels_june_solar_noon_elevation() -> None:
    # 21 June, ~13:40 local (12:00 UT + longitude and equation-of-time correction).
    # Textbook value: 90 - (latitude - declination) = 90 - (50.85 - 23.44) ~= 62.6 deg.
    noon = datetime(2025, 6, 21, 11, 40, tzinfo=timezone.utc)
    elevation = solar_elevation(BRUSSELS.latitude, BRUSSELS.longitude, noon)
    assert 61.0 < elevation < 64.0, elevation


def test_brussels_midnight_is_below_the_horizon() -> None:
    midnight = datetime(2025, 6, 21, 22, 40, tzinfo=timezone.utc)  # ~00:40 local
    elevation = solar_elevation(BRUSSELS.latitude, BRUSSELS.longitude, midnight)
    assert elevation < 0.0
    # Brussels in midsummer never gets true astronomical darkness.
    assert elevation > -18.0


def test_brussels_december_solar_noon_is_low() -> None:
    # 90 - (50.85 + 23.44) ~= 15.7 deg.
    noon = datetime(2025, 12, 21, 11, 40, tzinfo=timezone.utc)
    elevation = solar_elevation(BRUSSELS.latitude, BRUSSELS.longitude, noon)
    assert 14.0 < elevation < 18.0, elevation


def test_equator_equinox_noon_is_overhead() -> None:
    noon = datetime(2025, 3, 20, 12, 0, tzinfo=timezone.utc)
    elevation = solar_elevation(0.0, 0.0, noon)
    assert elevation > 86.0, elevation


def test_polar_night_has_no_daylight_value() -> None:
    assert daylight_seconds_for(78.0, datetime(2025, 12, 21, 12, 0, tzinfo=timezone.utc)) is None
    brussels_june = daylight_seconds_for(
        BRUSSELS.latitude, datetime(2025, 6, 21, 12, 0, tzinfo=timezone.utc)
    )
    assert brussels_june is not None
    assert 16.3 * 3600 < brussels_june < 16.9 * 3600, brussels_june


def test_daylight_delta_sign_follows_the_season() -> None:
    october = extract_sky_vector(build_window("front_collapse"))
    april = extract_sky_vector(build_window("ridge_building"))
    assert october.daylight_delta < -0.3, "mid-October: the year is closing in"
    assert april.daylight_delta > 0.3, "April: days opening out"


def test_solstice_daylight_delta_is_near_zero() -> None:
    coords = BRUSSELS
    solstice = datetime(2025, 6, 21, 10, 0, tzinfo=timezone.utc)
    window = build_window("flat_grey", coords, solstice)
    v = extract_sky_vector(window, at=solstice)
    assert abs(v.daylight_delta) < 0.1, "nothing moves at the solstice"


# ---------------------------------------------------------------------------
# Golden hour is defined on elevation, not the clock
# ---------------------------------------------------------------------------


def test_golden_hour_peaks_near_the_horizon_and_dies_at_noon() -> None:
    coords = BRUSSELS
    dusk = build_window("front_collapse")  # anchored 40 min before sunset
    near = extract_sky_vector(dusk, at=dusk.now.time)

    noon = datetime(2025, 10, 17, 11, 0, tzinfo=timezone.utc)
    midday_window = build_window("front_collapse", coords, noon)
    midday = extract_sky_vector(midday_window, at=noon)

    assert near.golden_hour_proximity > midday.golden_hour_proximity + 0.5
    assert midday.golden_hour_proximity < 0.2


def test_sun_elevation_pins_at_astronomical_night() -> None:
    deep_night = datetime(2025, 12, 21, 1, 0, tzinfo=timezone.utc)
    window = build_window("flat_grey", BRUSSELS, deep_night)
    v = extract_sky_vector(window, at=deep_night)
    assert v.sun_elevation == pytest.approx(-1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def _empty_window(rows: int = 24) -> WeatherWindow:
    base = datetime(2025, 10, 17, 12, 0, tzinfo=timezone.utc)
    history = [WeatherObservation(time=base - timedelta(hours=h)) for h in range(rows, -1, -1)]
    return WeatherWindow(
        coordinates=BRUSSELS,
        generated_at=base,
        now=history[-1],
        history=history,
        sunrise=None,
        sunset=None,
        daylight_seconds=None,
        daylight_seconds_yesterday=None,
    )


def test_all_none_observations_degrade_without_raising() -> None:
    ledger = DegradationLedger()
    v = extract_sky_vector(_empty_window(), ledger=ledger)

    assert v.pressure_trend_6h == 0.0
    assert v.pressure_norm_deviation == 0.0
    assert v.temp_norm_deviation == 0.0
    assert v.cloud_depth == 0.0
    assert v.precip_intensity == 0.0
    assert v.gust_variance == 0.0
    # Solar geometry needs no observations at all, so it must still be real.
    assert v.sun_elevation != 0.0
    assert not ledger.clean
    assert any("pressure_trend_6h" in note for note in ledger.as_list())


def test_empty_history_does_not_raise() -> None:
    window = WeatherWindow(
        coordinates=BRUSSELS,
        generated_at=datetime(2025, 10, 17, 12, 0, tzinfo=timezone.utc),
        now=WeatherObservation(time=datetime(2025, 10, 17, 12, 0, tzinfo=timezone.utc)),
        history=[],
    )
    v = extract_sky_vector(window)
    assert all(math.isfinite(x) for x in v.as_array())


def test_missing_coordinates_degrades_only_the_solar_dims() -> None:
    window = build_window("front_collapse")
    window.coordinates = None  # type: ignore[assignment]
    ledger = DegradationLedger()
    v = extract_sky_vector(window, at=window.now.time, ledger=ledger)
    assert v.sun_elevation == 0.0
    assert v.golden_hour_proximity == 0.0
    assert v.pressure_trend_6h < -0.8, "the pressure dims do not need coordinates"


def test_extract_is_deterministic() -> None:
    window = build_window("gusty_front")
    first = extract_sky_vector(window, at=window.now.time).as_array()
    second = extract_sky_vector(window, at=window.now.time).as_array()
    assert first == second


def test_fixture_history_is_a_full_week_of_hours() -> None:
    window = build_window("front_collapse")
    assert len(window.history) == 7 * 24 + 1
    times = [o.time for o in window.history]
    assert times == sorted(times), "history must run oldest -> newest"
    assert window.now.time == times[-1]


def test_unknown_scenario_is_rejected_loudly() -> None:
    with pytest.raises(KeyError):
        build_window("perfect_weather")
    with pytest.raises(KeyError):
        FixtureWeatherSource("perfect_weather")


def test_fixture_source_serves_without_network() -> None:
    source = FixtureWeatherSource()
    assert source.name == "fixture"
    assert source.scenario == "front_collapse"
    window = asyncio.run(source.window(BRUSSELS))
    assert window.source.startswith("fixture:")
    assert extract_sky_vector(window, at=window.now.time).pressure_trend_6h < -0.8


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_cache_key_is_geohash_plus_rounded_hour() -> None:
    a = cache_key(BRUSSELS, datetime(2025, 10, 17, 12, 5, tzinfo=timezone.utc))
    b = cache_key(BRUSSELS, datetime(2025, 10, 17, 12, 55, tzinfo=timezone.utc))
    c = cache_key(BRUSSELS, datetime(2025, 10, 17, 13, 5, tzinfo=timezone.utc))
    assert a == b, "the same hour is the same key"
    assert a != c
    assert a.startswith(BRUSSELS.geohash(5))


def test_cache_hit_miss_and_geohash_sharing() -> None:
    async def scenario() -> None:
        cache = WeatherWindowCache(ttl_s=900)
        moment = datetime(2025, 10, 17, 12, 0, tzinfo=timezone.utc)
        window = build_window("front_collapse")

        assert await cache.get(BRUSSELS, moment) is None
        await cache.set(BRUSSELS, window, moment)
        assert await cache.get(BRUSSELS, moment) is window

        # A few hundred metres away is the same geohash-5 cell and the same weather.
        nearby = Coordinates(latitude=BRUSSELS.latitude + 0.002, longitude=BRUSSELS.longitude)
        assert await cache.get(nearby, moment) is window

        # An hour later is a different key.
        assert await cache.get(BRUSSELS, moment + timedelta(hours=1)) is None

        stats = cache.stats()
        assert stats.hits == 2
        assert stats.misses == 2
        assert 0.0 < stats.hit_rate < 1.0
        assert stats.entries == 1

    asyncio.run(scenario())


def test_cache_expiry_still_leaves_a_last_known_good() -> None:
    async def scenario() -> None:
        cache = WeatherWindowCache(ttl_s=1)
        moment = datetime(2025, 10, 17, 12, 0, tzinfo=timezone.utc)
        window = build_window("ridge_building")
        await cache.set(BRUSSELS, window, moment)

        # Reach in and age the entry rather than sleeping; tests should not wait.
        entry = cache._fresh[cache_key(BRUSSELS, moment)]  # noqa: SLF001
        entry.stored_at = entry.stored_at - timedelta(hours=3)

        assert await cache.get(BRUSSELS, moment) is None, "TTL must expire"
        fallback = await cache.last_known_good(BRUSSELS)
        assert fallback is window, "degradation must always have something to serve"
        assert cache.stats().expiries == 1

    asyncio.run(scenario())


def test_stale_windows_are_not_promoted_to_last_known_good() -> None:
    async def scenario() -> None:
        cache = WeatherWindowCache()
        stale = build_window("flat_grey").model_copy(update={"stale": True})
        await cache.set(BRUSSELS, stale)
        assert await cache.last_known_good(BRUSSELS) is None

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Open-Meteo parsing (offline: a canned payload in the documented shape)
# ---------------------------------------------------------------------------


def _canned_open_meteo_payload() -> dict[str, object]:
    """The real response shape, trimmed: local naive stamps + a separate offset."""
    times = [f"2025-10-17T{h:02d}:00" for h in range(24)]
    return {
        "latitude": 50.85,
        "longitude": 4.35,
        "utc_offset_seconds": 7200,
        "timezone": "Europe/Brussels",
        "hourly": {
            "time": times,
            "surface_pressure": [1010.0 - 0.5 * h for h in range(24)],
            "pressure_msl": [1013.0 - 0.5 * h for h in range(24)],
            "temperature_2m": [12.0] * 12 + [None] + [13.0] * 11,
            "apparent_temperature": [10.0] * 24,
            "cloud_cover": [90.0] * 24,
            "precipitation": [0.0] * 20 + [1.2] * 4,
            "wind_gusts_10m": [20.0] * 24,
            "relative_humidity_2m": [88.0] * 24,
        },
        "daily": {
            "time": ["2025-10-16", "2025-10-17"],
            "sunrise": ["2025-10-16T08:19", "2025-10-17T08:21"],
            "sunset": ["2025-10-16T19:00", "2025-10-17T18:58"],
            "daylight_duration": [38460.0, 38220.0],
        },
    }


def test_open_meteo_parsing_handles_offsets_nulls_and_now_selection() -> None:
    from app.sky.open_meteo import OpenMeteoSource

    source = OpenMeteoSource.__new__(OpenMeteoSource)  # no settings, no I/O
    reference = datetime(2025, 10, 17, 12, 0, tzinfo=timezone.utc)  # 14:00 local
    window = source._parse(_canned_open_meteo_payload(), BRUSSELS, reference)  # noqa: SLF001

    assert len(window.history) == 24
    # Local 00:00 with a +02:00 offset is 22:00 UTC the previous day.
    assert window.history[0].time == datetime(2025, 10, 16, 22, 0, tzinfo=timezone.utc)
    # "now" is the row nearest the reference, not the last row of the array.
    assert window.now.time == reference
    assert window.now.time != window.history[-1].time
    # A null in one column must not shift the others.
    assert any(o.temperature_2m is None for o in window.history)
    assert all(o.apparent_temperature == 10.0 for o in window.history)
    assert window.daylight_seconds == 38220.0
    assert window.daylight_seconds_yesterday == 38460.0
    assert window.sunset == datetime(2025, 10, 17, 16, 58, tzinfo=timezone.utc)
    assert not window.stale

    v = extract_sky_vector(window, at=reference)
    assert v.pressure_trend_6h < -0.4, "a 3 hPa fall must already be clearly felt"


# ---------------------------------------------------------------------------
# Route surface
# ---------------------------------------------------------------------------


def test_sky_routes_serve_fixtures_without_a_container() -> None:
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.routes.sky import router

    app = fastapi.FastAPI()
    app.include_router(router)
    client = TestClient(app)

    listing = client.get("/api/sky/scenarios")
    assert listing.status_code == 200
    names = {item["name"] for item in listing.json()["scenarios"]}
    assert set(SCENARIOS) == names

    response = client.get("/api/sky/vector", params={"scenario": "front_collapse"})
    assert response.status_code == 200
    body = response.json()
    assert body["vector"]["pressure_trend_6h"] < -0.8
    assert body["dims"] == list(SKY_DIMS)
    assert body["summary"]
    assert body["notes"]


def test_sky_route_degrades_to_neutral_without_weather() -> None:
    fastapi = pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.routes.sky import router

    app = fastapi.FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # In the assembled tree the container resolves fine and serves fixture
    # weather, so "no weather" has to be forced rather than assumed. Break the
    # source itself: a WeatherSource whose .window() always raises is exactly the
    # Open-Meteo-is-down case, and the route must answer 200 with a neutral
    # vector and an honest degradation note rather than surfacing a 500.
    from app.container import get_container

    class DeadWeather:
        name = "dead"

        async def window(self, coords, at=None):  # noqa: ANN001, ANN201
            raise RuntimeError("open-meteo unreachable")

    container = get_container()
    container._cache["weather"] = DeadWeather()  # noqa: SLF001
    try:
        response = client.get("/api/sky/vector", params={"lat": 50.85, "lon": 4.35})
    finally:
        container._cache.pop("weather", None)  # noqa: SLF001
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["degradations"]
    assert all(value == 0.0 for value in body["vector"].values())
