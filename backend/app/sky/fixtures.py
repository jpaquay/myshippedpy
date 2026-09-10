"""Canned weather windows. No network, no clock dependence, no surprises.

Six scenarios, chosen so that no two of them are the same *derivative* situation.
That is the discriminating axis for this product: "rainy" and "sunny" are not
scenarios, they are wallpaper. "Pressure crashing eleven hectopascals with the light
going" and "pressure crashing eleven hectopascals at 10am in April" would be two
different records, and a fixture set that cannot express the difference is useless
for testing the thing we actually built.

Every scenario generates a full 7-day hourly history programmatically — diurnal
temperature curve, synoptic pressure drift, humidity tracking cloud, deterministic
jitter from a fixed seed — because 168 hand-written rows would be both unreadable and
subtly inconsistent. Anchors are expressed relative to real computed sunrise/sunset
for the scenario's date and latitude, so "40 minutes to sunset in October" is
genuinely 40 minutes to sunset and not a hard-coded 18:47.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Final, Literal
from zoneinfo import ZoneInfo

from ..contracts import Coordinates, WeatherObservation, WeatherWindow
from .extract import daylight_seconds_for, solar_elevation

__all__ = [
    "SCENARIOS",
    "Scenario",
    "FixtureWeatherSource",
    "build_window",
    "BRUSSELS",
    "DEFAULT_SCENARIO",
]

BRUSSELS: Final[Coordinates] = Coordinates(
    latitude=50.8503,
    longitude=4.3517,
    timezone="Europe/Brussels",
    label="Brussels",
)

DEFAULT_SCENARIO: Final[str] = "front_collapse"

_HISTORY_DAYS: Final[int] = 7
_HISTORY_HOURS: Final[int] = _HISTORY_DAYS * 24

AnchorKind = Literal["clock", "before_sunset", "after_sunrise", "solar_noon"]


@dataclass(frozen=True)
class Scenario:
    """A derivative situation, not a weather type."""

    key: str
    description: str
    month: int
    day: int
    year: int = 2025

    # Anchor: where in the day "now" sits.
    anchor: AnchorKind = "clock"
    anchor_value: float = 12.0  # hours for "clock", minutes for the relative kinds

    # Pressure: a slow synoptic baseline plus a shaped final 6 hours. The final
    # ramp is what pressure_trend_6h reads; the baseline is what the z-score reads.
    pressure_base: float = 1015.0
    pressure_week_drift: float = 0.0  # hPa change across the whole 7 days
    pressure_ramp_6h: float = 0.0  # hPa change over the final 6h (signed)
    pressure_wobble: float = 0.3  # hPa of deterministic jitter
    # Amplitude of the slow synoptic wave riding on the baseline. Turned right down
    # for the inert control scenario: a "flat" barometer that still drifts a
    # hectopascal every six hours is not flat, and the control has to be honest or
    # it stops being a control.
    pressure_wave: float = 1.6

    # Temperature: weekly mean, diurnal amplitude, and a late anomaly that pushes
    # "now" away from the location's own recent norm.
    temp_mean: float = 11.0
    temp_diurnal: float = 5.0
    temp_anomaly: float = 0.0  # deg C applied over the final ~30h
    wind_chill: float = 0.0  # apparent = temperature + this (negative = chill)

    # Sky state at "now".
    cloud_now: float = 40.0
    cloud_background: float = 45.0
    humidity_now: float = 70.0
    precip_now: float = 0.0
    precip_ramp_hours: int = 0  # hours over which rain builds to precip_now

    # Wind: gust mean and swing over the last 6h. Swing is the whole point.
    gust_mean: float = 15.0
    gust_swing: float = 3.0

    seed: int = 0
    tags: tuple[str, ...] = field(default_factory=tuple)


SCENARIOS: Final[dict[str, Scenario]] = {
    # The reference case. Everything the product exists to detect happens here at
    # once: a deep, fast fall; rain arriving rather than falling; the light going.
    "front_collapse": Scenario(
        key="front_collapse",
        description="Pressure crashing 11 hPa in six hours, rain arriving, 40 minutes to an October sunset.",
        month=10,
        day=17,
        anchor="before_sunset",
        anchor_value=40.0,
        pressure_base=1008.0,
        pressure_week_drift=-6.0,
        pressure_ramp_6h=-11.0,
        pressure_wobble=0.4,
        temp_mean=11.5,
        temp_diurnal=4.5,
        temp_anomaly=1.5,
        wind_chill=-2.5,
        cloud_now=97.0,
        cloud_background=70.0,
        humidity_now=93.0,
        precip_now=2.4,
        precip_ramp_hours=3,
        gust_mean=34.0,
        gust_swing=9.0,
        seed=101,
        tags=("falling", "rain", "dusk"),
    ),
    # The mirror image: same magnitude of change, opposite sign, opposite feeling.
    "ridge_building": Scenario(
        key="ridge_building",
        description="Pressure rising steadily into a ridge, cloud clearing, crisp mid-morning.",
        month=4,
        day=9,
        anchor="clock",
        anchor_value=10.0,
        pressure_base=1024.0,
        pressure_week_drift=9.0,
        pressure_ramp_6h=6.5,
        pressure_wobble=0.25,
        temp_mean=9.5,
        temp_diurnal=7.0,
        temp_anomaly=0.5,
        wind_chill=-1.0,
        cloud_now=15.0,
        cloud_background=55.0,
        humidity_now=58.0,
        precip_now=0.0,
        gust_mean=13.0,
        gust_swing=2.0,
        seed=202,
        tags=("rising", "clearing", "morning"),
    ),
    # The control. Every dimension deliberately inert. If this scenario produces a
    # dramatic vector, the extractor is lying somewhere.
    "flat_grey": Scenario(
        key="flat_grey",
        description="Barometer dead flat, total overcast, no rain, midday. Nothing is happening.",
        month=11,
        day=12,
        anchor="clock",
        anchor_value=12.5,
        pressure_base=1016.0,
        pressure_week_drift=0.4,
        pressure_ramp_6h=0.1,
        pressure_wobble=0.1,
        pressure_wave=0.25,
        temp_mean=7.5,
        temp_diurnal=2.0,
        temp_anomaly=0.0,
        wind_chill=-1.5,
        cloud_now=100.0,
        cloud_background=92.0,
        humidity_now=88.0,
        precip_now=0.0,
        gust_mean=11.0,
        gust_swing=1.2,
        seed=303,
        tags=("flat", "overcast"),
    ),
    # Absolute heat is not the signal; heat relative to this week here is.
    "heatwave_evening": Scenario(
        key="heatwave_evening",
        description="Well above the local norm, air completely still, golden hour in high summer.",
        month=7,
        day=28,
        anchor="before_sunset",
        anchor_value=25.0,
        pressure_base=1019.0,
        pressure_week_drift=1.5,
        pressure_ramp_6h=-0.8,
        pressure_wobble=0.2,
        temp_mean=21.0,
        temp_diurnal=7.5,
        temp_anomaly=8.5,
        wind_chill=1.5,  # humid heat feels hotter than the thermometer
        cloud_now=8.0,
        cloud_background=25.0,
        humidity_now=48.0,
        precip_now=0.0,
        gust_mean=5.0,
        gust_swing=1.0,
        seed=404,
        tags=("hot", "still", "golden"),
    ),
    # The opposite anomaly, and the one that most needs a local baseline: -3 degC in
    # a mild week is a shock; -3 degC in a cold week is Tuesday.
    "first_frost": Scenario(
        key="first_frost",
        description="Sharply below the week's norm, clear sky, high pressure, first light.",
        month=11,
        day=3,
        anchor="after_sunrise",
        anchor_value=15.0,
        pressure_base=1029.0,
        pressure_week_drift=6.0,
        pressure_ramp_6h=1.2,
        pressure_wobble=0.2,
        temp_mean=8.0,
        temp_diurnal=5.0,
        temp_anomaly=-9.0,
        wind_chill=-1.5,
        cloud_now=5.0,
        cloud_background=50.0,
        humidity_now=92.0,  # cold clear dawn: high RH, no cloud to weight it
        precip_now=0.0,
        gust_mean=4.0,
        gust_swing=1.0,
        seed=505,
        tags=("cold", "clear", "dawn"),
    ),
    # Variance without a trend. Pressure wobbles instead of moving; the air is
    # agitated but the synoptic situation is unresolved.
    "gusty_front": Scenario(
        key="gusty_front",
        description="Gusts swinging wildly under broken cloud, barometer wobbling without committing.",
        month=3,
        day=21,
        anchor="clock",
        anchor_value=15.0,
        pressure_base=1004.0,
        pressure_week_drift=-2.0,
        pressure_ramp_6h=-2.0,
        pressure_wobble=1.6,
        temp_mean=8.0,
        temp_diurnal=5.5,
        temp_anomaly=0.0,
        wind_chill=-4.0,
        cloud_now=65.0,
        cloud_background=68.0,
        humidity_now=76.0,
        precip_now=0.3,
        precip_ramp_hours=2,
        gust_mean=26.0,
        gust_swing=16.0,
        seed=606,
        tags=("gusty", "unsettled", "equinox"),
    ),
}


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _zone(coords: Coordinates) -> ZoneInfo:
    name = coords.timezone
    if not name or name == "auto":
        name = "Europe/Brussels"
    try:
        return ZoneInfo(name)
    except Exception:  # pragma: no cover - missing tzdata on exotic hosts
        return ZoneInfo("UTC")


def _sun_event(coords: Coordinates, local_day: datetime, *, rising: bool) -> datetime | None:
    """Find sunrise/sunset by bisecting the computed elevation.

    Reusing the extractor's own solar model keeps the fixtures honest: if the solar
    code drifts, the fixture anchors drift with it and the tests still describe the
    same physical moment.
    """
    start = local_day.replace(hour=0, minute=0, second=0, microsecond=0)
    step = timedelta(minutes=10)
    previous = solar_elevation(coords.latitude, coords.longitude, start)
    t = start
    for _ in range(int(24 * 60 / 10)):
        nxt = t + step
        current = solar_elevation(coords.latitude, coords.longitude, nxt)
        crossed_up = previous < 0.0 <= current
        crossed_down = previous >= 0.0 > current
        if (rising and crossed_up) or (not rising and crossed_down):
            lo, hi = t, nxt
            for _ in range(20):  # ~0.6 s resolution, far finer than needed
                mid = lo + (hi - lo) / 2
                if (solar_elevation(coords.latitude, coords.longitude, mid) >= 0.0) == rising:
                    hi = mid
                else:
                    lo = mid
            return lo + (hi - lo) / 2
        previous = current
        t = nxt
    return None


def _resolve_anchor(scenario: Scenario, coords: Coordinates) -> datetime:
    tz = _zone(coords)
    local_midnight = datetime(scenario.year, scenario.month, scenario.day, tzinfo=tz)

    if scenario.anchor == "clock":
        hours = scenario.anchor_value
        return (local_midnight + timedelta(hours=hours)).astimezone(timezone.utc)

    if scenario.anchor == "solar_noon":
        # Elevation maximum, found by coarse scan; good to a minute, which is plenty.
        best = max(
            (local_midnight + timedelta(minutes=m) for m in range(0, 24 * 60, 2)),
            key=lambda t: solar_elevation(coords.latitude, coords.longitude, t),
        )
        return best.astimezone(timezone.utc)

    rising = scenario.anchor == "after_sunrise"
    event = _sun_event(coords, local_midnight, rising=rising)
    if event is None:  # polar day/night: fall back to local noon
        return (local_midnight + timedelta(hours=12)).astimezone(timezone.utc)
    offset = timedelta(minutes=scenario.anchor_value)
    return (event + offset if rising else event - offset).astimezone(timezone.utc)


def _diurnal(local_hour: float) -> float:
    """Normalised -1..1 daily temperature shape: coldest ~05:00, warmest ~15:00."""
    return -math.cos(2.0 * math.pi * (local_hour - 5.0) / 24.0)


def _build_history(
    scenario: Scenario,
    coords: Coordinates,
    now_utc: datetime,
) -> list[WeatherObservation]:
    tz = _zone(coords)
    rng = random.Random(scenario.seed)  # deterministic: fixtures must be reproducible
    rows: list[WeatherObservation] = []

    # Hourly grid ending exactly at `now_utc`, oldest first.
    for offset in range(_HISTORY_HOURS, -1, -1):
        moment = now_utc - timedelta(hours=offset)
        local = moment.astimezone(tz)
        local_hour = local.hour + local.minute / 60.0
        age_frac = 1.0 - offset / _HISTORY_HOURS  # 0 at the oldest row, 1 at "now"

        # -- pressure: week-long drift + a gentle synoptic wave + the final ramp.
        pressure = scenario.pressure_base + scenario.pressure_week_drift * (age_frac - 0.5)
        pressure += scenario.pressure_wave * math.sin(2.0 * math.pi * offset / 54.0)
        if offset <= 6:
            # Shaped so the change is monotone across the final 6h and matches
            # pressure_ramp_6h exactly at offset 0 — the trend dim reads this.
            pressure += scenario.pressure_ramp_6h * (1.0 - offset / 6.0)
        pressure += rng.uniform(-scenario.pressure_wobble, scenario.pressure_wobble)

        # -- temperature: weekly mean + diurnal swing + a late anomaly that only
        # affects the last ~30h, so the 7-day norm stays a genuine baseline.
        anomaly_weight = 0.0
        if offset <= 30:
            anomaly_weight = 1.0 - (offset / 30.0) ** 1.5
        temperature = (
            scenario.temp_mean
            + scenario.temp_diurnal * _diurnal(local_hour)
            + scenario.temp_anomaly * anomaly_weight
            + rng.uniform(-0.35, 0.35)
        )
        apparent = temperature + scenario.wind_chill

        # -- cloud: background for most of the week, easing to the scenario value
        # across the final 12h so the "now" sky is the one described.
        blend = 0.0 if offset > 12 else 1.0 - offset / 12.0
        cloud = scenario.cloud_background * (1.0 - blend) + scenario.cloud_now * blend
        cloud += 12.0 * math.sin(2.0 * math.pi * offset / 37.0)
        cloud = min(100.0, max(0.0, cloud + rng.uniform(-4.0, 4.0)))

        # -- humidity tracks cloud loosely; anchored to the scenario value at "now".
        humidity_bg = 62.0 + 0.22 * cloud
        humidity = humidity_bg * (1.0 - blend) + scenario.humidity_now * blend
        humidity = min(100.0, max(20.0, humidity + rng.uniform(-2.5, 2.5)))

        # -- precipitation: dry all week, ramping in over the final few hours only
        # if the scenario says so. Rain that has been falling for a week reads very
        # differently from rain that just started.
        precip = 0.0
        if scenario.precip_now > 0.0:
            ramp = max(scenario.precip_ramp_hours, 1)
            if offset <= ramp:
                precip = scenario.precip_now * (1.0 - offset / (ramp + 1.0))
            elif offset <= ramp + 2:
                precip = scenario.precip_now * 0.05
        precip = round(max(0.0, precip), 2)

        # -- gusts: swing only applies to the last 6h; the rest of the week is a
        # calm baseline so gust_variance measures *this afternoon*, not the week.
        if offset <= 6:
            phase = math.sin(2.0 * math.pi * offset / 3.0)
            gust = scenario.gust_mean + scenario.gust_swing * phase * 1.35
        else:
            gust = scenario.gust_mean * 0.7 + 4.0 * math.sin(2.0 * math.pi * offset / 19.0)
        gust = max(0.0, gust + rng.uniform(-1.0, 1.0))

        rows.append(
            WeatherObservation(
                time=moment,
                temperature_2m=round(temperature, 1),
                apparent_temperature=round(apparent, 1),
                surface_pressure=round(pressure, 1),
                pressure_msl=round(pressure + 3.2, 1),  # Brussels sits ~27 m up
                cloud_cover=round(cloud, 0),
                precipitation=precip,
                wind_gusts_10m=round(gust, 1),
                relative_humidity_2m=round(humidity, 0),
            )
        )
    return rows


def build_window(
    scenario: str,
    coords: Coordinates | None = None,
    at: datetime | None = None,
) -> WeatherWindow:
    """A complete, self-consistent WeatherWindow for one named scenario.

    ``at`` overrides the scenario's own anchor, which is how a test can ask
    "front_collapse, but at 3am" and get a genuinely different vector out.
    """
    try:
        spec = SCENARIOS[scenario]
    except KeyError:
        raise KeyError(
            f"unknown scenario {scenario!r}; known: {', '.join(sorted(SCENARIOS))}"
        ) from None

    coordinates = coords or BRUSSELS
    now_utc = (
        at.astimezone(timezone.utc) if at is not None and at.tzinfo else
        at.replace(tzinfo=timezone.utc) if at is not None else
        _resolve_anchor(spec, coordinates)
    )
    now_utc = now_utc.replace(second=0, microsecond=0)

    history = _build_history(spec, coordinates, now_utc)
    now_obs = history[-1]

    tz = _zone(coordinates)
    local_day = now_utc.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    sunrise = _sun_event(coordinates, local_day, rising=True)
    sunset = _sun_event(coordinates, local_day, rising=False)

    daylight_today = daylight_seconds_for(coordinates.latitude, now_utc)
    daylight_yesterday = daylight_seconds_for(coordinates.latitude, now_utc - timedelta(days=1))
    if daylight_today is None and sunrise is not None and sunset is not None:
        daylight_today = (sunset - sunrise).total_seconds()

    return WeatherWindow(
        coordinates=coordinates,
        generated_at=now_utc,
        now=now_obs,
        history=history,
        sunrise=sunrise,
        sunset=sunset,
        daylight_seconds=daylight_today,
        daylight_seconds_yesterday=daylight_yesterday,
        stale=False,
        source=f"fixture:{spec.key}",
    )


class FixtureWeatherSource:
    """WeatherSource that never touches the network.

    Defaults to ``front_collapse`` because that is the scenario in which the
    product's thesis is legible: everything interesting is in the derivative.
    """

    name = "fixture"

    def __init__(self, scenario: str = DEFAULT_SCENARIO) -> None:
        if scenario not in SCENARIOS:
            raise KeyError(
                f"unknown scenario {scenario!r}; known: {', '.join(sorted(SCENARIOS))}"
            )
        self.scenario = scenario

    async def window(self, coords: Coordinates, at: datetime | None = None) -> WeatherWindow:
        return build_window(self.scenario, coords, at)

    def describe(self) -> str:
        return SCENARIOS[self.scenario].description


def scenario_catalogue() -> list[dict[str, str | list[str]]]:
    """Name + one-line description for every scenario, for the API and the demo UI."""
    return [
        {"name": spec.key, "description": spec.description, "tags": list(spec.tags)}
        for spec in SCENARIOS.values()
    ]
