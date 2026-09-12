"""Turn a weather window into a SkyVector.

The whole product rests on one claim: the emotional content of weather is in the
*derivative*. Rain does not mean sad. Rain arriving on a barometer that has dropped
nine hectopascals since lunchtime, forty minutes before an October sunset, means
something very specific — and it means something different from the same rain on the
back edge of a front with the pressure climbing. Likewise 8 degC is meaningless as an
absolute: 8 degC in Helsinki in March is a reprieve, 8 degC in Seville in August is an
emergency. Every "absolute" dimension here is therefore expressed as a deviation from
*this location's own* recent norm, taken from the window's own 7-day history.

Everything in this module is pure, synchronous and deterministic: same window in,
same vector out, no clock reads except the explicitly passed ``at``, no network.
It also never raises. A missing input degrades that one dimension to 0.0 (the
honest "no signal" value) and leaves a breadcrumb in the degradation ledger.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from statistics import fmean, pstdev
from typing import Callable, Final, Sequence, TypeVar

from ..contracts import (
    Coordinates,
    SkyVector,
    WeatherObservation,
    WeatherWindow,
    clamp,
)
from ..errors import DegradationLedger

__all__ = [
    "extract_sky_vector",
    "solar_elevation",
    "solar_declination_deg",
    "equation_of_time_min",
    "daylight_seconds_for",
    "summarise",
]

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Coefficients. Each of these is a judgement call about *feeling*, not physics,
# so each one is justified where it is used rather than dumped in a config file.
# ---------------------------------------------------------------------------

#: Hectopascals of 6-hour change that put the tanh knee at ~0.54. Chosen so a
#: 3 hPa fall — the classic "something is coming" fall — already reads as clearly
#: negative rather than as noise, while the practical +/-12 hPa extreme saturates.
PRESSURE_TREND_KNEE_HPA: Final[float] = 5.0

#: Z-scores are divided by this before tanh. 2.0 means "two sigma from your own
#: 7-day norm" lands at 0.76 — strongly felt, not yet pinned.
ZSCORE_SOFTNESS: Final[float] = 2.0

#: Floors on the window's own sigma. Without them a freakishly steady week makes
#: every trivial wobble a five-sigma event.
PRESSURE_SIGMA_FLOOR_HPA: Final[float] = 0.8
TEMP_SIGMA_FLOOR_C: Final[float] = 1.0

#: Temperature is compared against the same *time of day* across the history window,
#: within this many hours. Without it the diurnal cycle swamps the anomaly: a 16:00
#: reading measured against a 7-day mean that includes every overnight low is warm by
#: construction, every single day, everywhere. That is not a signal, and it would make
#: temp_norm_deviation a noisy duplicate of sun_elevation. Pressure gets no such
#: treatment — outside the tropics the atmospheric tide is well under 1 hPa, so the
#: full-window mean is already the right baseline there.
HOUR_BUCKET_TOLERANCE_H: Final[float] = 2.0
HOUR_BUCKET_MIN_SAMPLES: Final[int] = 5

#: Solar elevation normalisation. -18 deg is astronomical twilight's end: below it
#: there is no sky left, so it pins at -1. +75 deg rather than +90 because outside
#: the tropics the sun never reaches zenith and we want mid-latitude summer noon to
#: actually approach the top of the scale.
SUN_NIGHT_DEG: Final[float] = -18.0
SUN_MAX_DEG: Final[float] = 75.0

#: Golden hour is defined on elevation, not the clock: +/-6 deg around the horizon
#: is the full-strength band (roughly civil twilight plus the low-sun hour), and it
#: decays over the elevation the sun covers in 90 minutes *at this latitude on this
#: date*. In Tromso in June that span is enormous and the light really does last;
#: at the equator it is over in minutes. Clock-based golden hour gets this backwards.
GOLDEN_CORE_DEG: Final[float] = 6.0
GOLDEN_DECAY_MINUTES: Final[float] = 90.0
GOLDEN_MIN_SPAN_DEG: Final[float] = 2.0

#: Standard deviation of gusts (km/h) over the last 6h that reads as fully unsettled.
#: 12 km/h of scatter means gusts are swinging by ~25 km/h peak to trough, which is a
#: sky that cannot make up its mind. Note this is variance, not speed: a steady 40 km/h
#: gale is monotonous, almost meditative; a gusting 15-35 km/h afternoon is nervous.
GUST_SIGMA_FULL_KMH: Final[float] = 12.0

#: Cloud depth weighting. Cover alone cannot distinguish thin high cirrus from a lid.
#: Humidity in the boundary layer is the cheap proxy for how low and thick the deck is.
CLOUD_RH_LOW: Final[float] = 55.0
CLOUD_RH_HIGH: Final[float] = 95.0
CLOUD_DRY_FLOOR: Final[float] = 0.55

#: Precipitation log compression. A: the scale at which drizzle becomes audible.
#: B: the rate that reads as a full downpour. Calibrated so ~2 mm/h (steady rain)
#: lands near 0.5 and ~10 mm/h saturates at 1.0, with 0.2 mm/h drizzle still ~0.10
#: rather than rounding to nothing.
PRECIP_SCALE_MM: Final[float] = 0.6
PRECIP_FULL_MM: Final[float] = 10.0

#: Daylight change normalisation. At mid latitudes the equinox peak is about
#: 4 minutes per day; +/-290 s puts that just below saturation and leaves the
#: solstice weeks — where the change is genuinely nothing — near zero.
DAYLIGHT_DELTA_FULL_S: Final[float] = 290.0

#: How far from the ideal timestamp we will still accept a history row.
_MATCH_TOLERANCE = timedelta(minutes=90)
_TREND_HOURS: Final[int] = 6
_GUST_WINDOW_HOURS: Final[int] = 6


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _soft(value: float, knee: float) -> float:
    """tanh knee, guaranteed inside [-1, 1].

    tanh rather than a linear ramp because human sensitivity to a change is
    roughly logarithmic near zero and flat at the extremes: the difference between
    a 1 hPa and a 4 hPa fall is enormous; the difference between 14 and 18 is not.
    """
    if knee <= 0:
        return 0.0
    return clamp(math.tanh(value / knee), -1.0, 1.0)


def _smoothstep(x: float) -> float:
    x = clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _stddev(values: Sequence[float]) -> float:
    return pstdev(values) if len(values) > 1 else 0.0


# ---------------------------------------------------------------------------
# Solar position — NOAA General Solar Position Calculations, pure Python.
# ---------------------------------------------------------------------------


def _fractional_year_rad(moment: datetime) -> float:
    moment = _as_utc(moment)
    day_of_year = moment.timetuple().tm_yday
    hours = moment.hour + moment.minute / 60.0 + moment.second / 3600.0
    days_in_year = 366 if _is_leap(moment.year) else 365
    return (2.0 * math.pi / days_in_year) * (day_of_year - 1 + (hours - 12.0) / 24.0)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def equation_of_time_min(moment: datetime) -> float:
    """Minutes by which true solar time leads mean solar time (NOAA series)."""
    g = _fractional_year_rad(moment)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )


def solar_declination_deg(moment: datetime) -> float:
    """Solar declination in degrees (NOAA series, ~0.05 deg accuracy — ample here)."""
    g = _fractional_year_rad(moment)
    decl_rad = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.001480 * math.sin(3 * g)
    )
    return math.degrees(decl_rad)


def solar_elevation(latitude: float, longitude: float, moment: datetime) -> float:
    """Solar elevation above the horizon, in degrees.

    Real astronomy rather than interpolation between sunrise and sunset: the
    sunrise/sunset pair tells you nothing about how *steeply* the sun is falling,
    and at high latitudes it can be undefined for months at a time. Elevation is
    defined everywhere, always, including inside polar night.
    """
    moment = _as_utc(moment)
    decl = math.radians(solar_declination_deg(moment))
    lat = math.radians(latitude)

    minutes_utc = moment.hour * 60.0 + moment.minute + moment.second / 60.0
    # 4 minutes of true solar time per degree of longitude.
    true_solar_time = minutes_utc + equation_of_time_min(moment) + 4.0 * longitude
    hour_angle = math.radians((true_solar_time / 4.0) - 180.0)

    cos_zenith = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
    return 90.0 - math.degrees(math.acos(clamp(cos_zenith, -1.0, 1.0)))


def daylight_seconds_for(latitude: float, moment: datetime) -> float | None:
    """Length of the day at this latitude/date, from the sunrise hour angle.

    Used only as a fallback when the upstream feed did not hand us daylight
    duration. Returns None inside polar day/night, where the concept has no value.
    """
    decl = math.radians(solar_declination_deg(moment))
    lat = math.radians(latitude)
    # -0.833 deg accounts for refraction plus the solar disc's radius, the same
    # convention every almanac (and Open-Meteo) uses for sunrise.
    cos_h0 = (math.cos(math.radians(90.833)) - math.sin(lat) * math.sin(decl)) / (
        math.cos(lat) * math.cos(decl)
    )
    if cos_h0 > 1.0 or cos_h0 < -1.0:
        return None
    h0_deg = math.degrees(math.acos(cos_h0))
    return (2.0 * h0_deg / 15.0) * 3600.0


# ---------------------------------------------------------------------------
# History access
# ---------------------------------------------------------------------------


def _sorted_history(window: WeatherWindow) -> list[WeatherObservation]:
    rows = [obs for obs in (window.history or []) if obs is not None]
    return sorted(rows, key=lambda o: _as_utc(o.time))


def _nearest(
    history: Sequence[WeatherObservation],
    target: datetime,
    *,
    tolerance: timedelta = _MATCH_TOLERANCE,
) -> WeatherObservation | None:
    if not history:
        return None
    target = _as_utc(target)
    times = [_as_utc(o.time) for o in history]
    idx = bisect_left(times, target)
    best: WeatherObservation | None = None
    best_gap = tolerance
    for candidate in (idx - 1, idx, idx + 1):
        if 0 <= candidate < len(history):
            gap = abs(times[candidate] - target)
            if gap <= best_gap:
                best_gap = gap
                best = history[candidate]
    return best


def _series_with_time(
    history: Sequence[WeatherObservation],
    field: str,
) -> list[tuple[datetime, float]]:
    out: list[tuple[datetime, float]] = []
    for obs in history:
        value = _finite(getattr(obs, field, None))
        if value is not None:
            out.append((_as_utc(obs.time), value))
    return out


def _hour_matched(
    samples: Sequence[tuple[datetime, float]],
    reference: datetime,
    *,
    tolerance_h: float = HOUR_BUCKET_TOLERANCE_H,
) -> list[float]:
    """Samples taken at roughly the same time of day as the reference.

    Circular distance, so 23:00 and 01:00 are two hours apart rather than 22.
    """
    target = reference.hour + reference.minute / 60.0
    picked: list[float] = []
    for moment, value in samples:
        hour = moment.hour + moment.minute / 60.0
        gap = abs(hour - target)
        gap = min(gap, 24.0 - gap)
        if gap <= tolerance_h:
            picked.append(value)
    return picked


def _series(
    history: Sequence[WeatherObservation],
    field: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[float]:
    out: list[float] = []
    for obs in history:
        t = _as_utc(obs.time)
        if since is not None and t < since:
            continue
        if until is not None and t > until:
            continue
        value = _finite(getattr(obs, field, None))
        if value is not None:
            out.append(value)
    return out


def _pressure_series(
    history: Sequence[WeatherObservation],
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[float]:
    out: list[float] = []
    for obs in history:
        t = _as_utc(obs.time)
        if since is not None and t < since:
            continue
        if until is not None and t > until:
            continue
        value = _finite(obs.pressure)
        if value is not None:
            out.append(value)
    return out


# ---------------------------------------------------------------------------
# The extractor
# ---------------------------------------------------------------------------


def extract_sky_vector(
    window: WeatherWindow,
    *,
    at: datetime | None = None,
    ledger: DegradationLedger | None = None,
) -> SkyVector:
    """Nine numbers describing how the sky is *changing*.

    Never raises. Any dimension whose inputs are missing degrades to 0.0 and is
    recorded in ``ledger``; the caller decides whether a half-degraded vector is
    still worth serving (it usually is — the pressure dims carry most of the signal).
    """
    ledger = ledger if ledger is not None else DegradationLedger()
    notes: list[str] = []

    def note_missing(dim: str, detail: str) -> None:
        ledger.note("sky.extract", f"{dim}: {detail}")

    def guard(dim: str, fn: Callable[[], T], default: T) -> T:
        """One bad dimension must not cost us the other eight."""
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - defensive, exercised by fuzz
            note_missing(dim, f"unexpected error ({type(exc).__name__})")
            return default

    now_obs: WeatherObservation | None = getattr(window, "now", None)
    history = _sorted_history(window)
    coords: Coordinates | None = getattr(window, "coordinates", None)

    observed_at: datetime | None = None
    if now_obs is not None and getattr(now_obs, "time", None) is not None:
        observed_at = _as_utc(now_obs.time)
    reference = _as_utc(at) if at is not None else observed_at
    if reference is None:
        reference = _as_utc(getattr(window, "generated_at", None) or datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # 1. pressure_trend_6h — the load-bearing dimension.
    #
    # Physically: the rate of change of surface pressure is the single best
    # cheap indicator of an approaching or departing synoptic system. Emotionally:
    # a falling barometer is anticipation, unease, the sense of something about to
    # happen — the body registers it before the sky shows it. A rising barometer is
    # resolution and clarity. This dimension is negative when pressure falls.
    # ------------------------------------------------------------------
    def _pressure_trend() -> float:
        p_now = _finite(now_obs.pressure) if now_obs is not None else None
        if p_now is None:
            recent = _pressure_series(history, since=reference - timedelta(hours=2), until=reference)
            p_now = recent[-1] if recent else None
        if p_now is None:
            note_missing("pressure_trend_6h", "no current pressure")
            return 0.0
        past = _nearest(history, reference - timedelta(hours=_TREND_HOURS))
        p_then = _finite(past.pressure) if past is not None else None
        if p_then is None:
            note_missing("pressure_trend_6h", "no observation 6h back")
            return 0.0
        delta = p_now - p_then
        if abs(delta) >= 1.0:
            verb = "fell" if delta < 0 else "rose"
            notes.append(f"pressure {verb} {abs(delta):.1f} hPa in 6h")
        else:
            notes.append(f"pressure flat ({delta:+.1f} hPa in 6h)")
        return _soft(delta, PRESSURE_TREND_KNEE_HPA)

    pressure_trend_6h = guard("pressure_trend_6h", _pressure_trend, 0.0)

    # ------------------------------------------------------------------
    # 2. pressure_norm_deviation — "is this low?" is only answerable locally.
    #
    # 1005 hPa is a deep low in an Azores summer and an unremarkable Tuesday in
    # Reykjavik. We z-score against the window's own 7-day mean and sigma, so the
    # dimension means "unusual for here, lately" rather than "unusual for a textbook".
    # ------------------------------------------------------------------
    def _pressure_norm() -> float:
        series = _pressure_series(history)
        p_now = _finite(now_obs.pressure) if now_obs is not None else None
        if p_now is None and series:
            p_now = series[-1]
        if p_now is None or len(series) < 6:
            note_missing("pressure_norm_deviation", "insufficient pressure history")
            return 0.0
        mean = fmean(series)
        sigma = max(_stddev(series), PRESSURE_SIGMA_FLOOR_HPA)
        z = (p_now - mean) / sigma
        if abs(z) >= 1.0:
            side = "below" if z < 0 else "above"
            notes.append(f"{abs(p_now - mean):.0f} hPa {side} the 7-day norm")
        return _soft(z, ZSCORE_SOFTNESS)

    pressure_norm_deviation = guard("pressure_norm_deviation", _pressure_norm, 0.0)

    # ------------------------------------------------------------------
    # 3. temp_norm_deviation — apparent temperature, not the thermometer.
    #
    # Wind chill and humidity are the whole point: 4 degC in still sun and 4 degC in
    # a wet northerly are different experiences and should produce different music.
    # Same local z-score treatment as pressure — "mild for November here".
    # ------------------------------------------------------------------
    def _temp_norm() -> float:
        samples = _series_with_time(history, "apparent_temperature")
        current = _finite(now_obs.apparent_temperature) if now_obs is not None else None
        if current is None and now_obs is not None:
            # Fall back to dry-bulb rather than losing the dimension entirely; note it.
            current = _finite(now_obs.temperature_2m)
            if current is not None:
                note_missing("temp_norm_deviation", "no apparent_temperature, used temperature_2m")
        if not samples:
            samples = _series_with_time(history, "temperature_2m")
        if current is None and samples:
            current = samples[-1][1]
        if current is None or len(samples) < 6:
            note_missing("temp_norm_deviation", "insufficient temperature history")
            return 0.0

        # Compare like with like: this hour of the day against the same hour on the
        # preceding days. "Warm for a November dawn here" is a real statement; "warm
        # compared to the average of all hours this week" is just an observation that
        # afternoons exist.
        series = _hour_matched(samples, reference)
        if len(series) < HOUR_BUCKET_MIN_SAMPLES:
            series = [value for _, value in samples]
            ledger.note(
                "sky.extract",
                "temp_norm_deviation: too few same-hour samples, using whole-window mean",
            )

        mean = fmean(series)
        sigma = max(_stddev(series), TEMP_SIGMA_FLOOR_C)
        z = (current - mean) / sigma
        if abs(current - mean) >= 2.0:
            side = "below" if z < 0 else "above"
            notes.append(f"feels {abs(current - mean):.0f}\u00b0C {side} this week's norm")
        return _soft(z, ZSCORE_SOFTNESS)

    temp_norm_deviation = guard("temp_norm_deviation", _temp_norm, 0.0)

    # ------------------------------------------------------------------
    # 4/5. sun_elevation and golden_hour_proximity — computed, not clocked.
    # ------------------------------------------------------------------
    elevation_deg: float | None = None
    if coords is not None:
        try:
            elevation_deg = solar_elevation(coords.latitude, coords.longitude, reference)
        except Exception:  # pragma: no cover - defensive
            elevation_deg = None
    if elevation_deg is None:
        note_missing("sun_elevation", "no coordinates for solar position")

    def _sun_elevation() -> float:
        if elevation_deg is None:
            return 0.0
        if elevation_deg <= SUN_NIGHT_DEG:
            value = -1.0
        elif elevation_deg < 0.0:
            # Twilight ramps -1 -> 0 across the 18 deg of astronomical/nautical/civil
            # dusk. The sky is still doing something down here; it is not night yet.
            value = elevation_deg / abs(SUN_NIGHT_DEG)
        else:
            value = min(elevation_deg / SUN_MAX_DEG, 1.0)
        if elevation_deg < -6.0:
            notes.append("full dark")
        elif elevation_deg < 0.0:
            notes.append("twilight")
        return clamp(value, -1.0, 1.0)

    sun_elevation_dim = guard("sun_elevation", _sun_elevation, 0.0)

    def _golden_hour() -> float:
        if elevation_deg is None or coords is None:
            note_missing("golden_hour_proximity", "no coordinates for solar position")
            return 0.0
        excess = abs(elevation_deg) - GOLDEN_CORE_DEG
        if excess <= 0.0:
            _append_horizon_note(notes, coords, reference, elevation_deg)
            return 1.0
        # How many degrees the sun actually moves in GOLDEN_DECAY_MINUTES here, now.
        # Near the poles in summer this is a fraction of a degree and the golden band
        # lasts hours; in the tropics it is ~15 deg and the light is gone in minutes.
        probe = reference + timedelta(minutes=GOLDEN_DECAY_MINUTES)
        rate_span = abs(solar_elevation(coords.latitude, coords.longitude, probe) - elevation_deg)
        span = max(rate_span, GOLDEN_MIN_SPAN_DEG)
        proximity = 1.0 - _smoothstep(excess / span)
        if proximity > 0.35:
            _append_horizon_note(notes, coords, reference, elevation_deg)
        return clamp(proximity, 0.0, 1.0)

    golden_hour_proximity = guard("golden_hour_proximity", _golden_hour, 0.0)

    # ------------------------------------------------------------------
    # 6. gust_variance — the nervousness of the air.
    #
    # Deliberately the standard deviation of gusts over 6h and not the mean speed.
    # A steady 40 km/h gale is monotonous, and monotony is calming. An afternoon
    # swinging between 15 and 35 km/h is agitated: the air keeps changing its mind,
    # doors slam, the trees never settle. That is what we want to hear.
    # ------------------------------------------------------------------
    def _gust_variance() -> float:
        since = reference - timedelta(hours=_GUST_WINDOW_HOURS)
        gusts = _series(history, "wind_gusts_10m", since=since, until=reference)
        if len(gusts) < 3:
            note_missing("gust_variance", "fewer than 3 gust samples in the last 6h")
            return 0.0
        sigma = _stddev(gusts)
        if sigma >= 3.0:
            notes.append(f"gusts swinging {min(gusts):.0f}-{max(gusts):.0f} km/h")
        elif fmean(gusts) >= 25.0:
            notes.append(f"steady {fmean(gusts):.0f} km/h wind")
        return clamp(sigma / GUST_SIGMA_FULL_KMH, 0.0, 1.0)

    gust_variance = guard("gust_variance", _gust_variance, 0.0)

    # ------------------------------------------------------------------
    # 7. cloud_depth — cover is not the same as weight.
    #
    # 100% cover at 60% RH is thin high cloud: bright, diffuse, silvery, and it does
    # not press on you. 100% cover at 95% RH is a saturated low deck — a lid, dark at
    # noon. Cover sets the ceiling, humidity decides how heavy that ceiling feels, so
    # we scale cover by a 0.55..1.0 humidity weight rather than multiplying outright
    # (a dry overcast still counts for something; it is not clear sky).
    # ------------------------------------------------------------------
    def _cloud_depth() -> float:
        cover = _finite(now_obs.cloud_cover) if now_obs is not None else None
        if cover is None:
            note_missing("cloud_depth", "no cloud cover")
            return 0.0
        cover_frac = clamp(cover / 100.0, 0.0, 1.0)
        rh = _finite(now_obs.relative_humidity_2m) if now_obs is not None else None
        if rh is None:
            note_missing("cloud_depth", "no humidity, using unweighted cover")
            weight = 1.0
        else:
            span = CLOUD_RH_HIGH - CLOUD_RH_LOW
            wet = clamp((rh - CLOUD_RH_LOW) / span, 0.0, 1.0)
            weight = CLOUD_DRY_FLOOR + (1.0 - CLOUD_DRY_FLOOR) * wet
        depth = clamp(cover_frac * weight, 0.0, 1.0)
        if depth >= 0.8:
            notes.append("low overcast, lid on")
        elif cover_frac >= 0.75:
            notes.append("high thin overcast")
        elif cover_frac <= 0.15:
            notes.append("clear sky")
        return depth

    cloud_depth = guard("cloud_depth", _cloud_depth, 0.0)

    # ------------------------------------------------------------------
    # 8. precip_intensity — log-compressed so drizzle survives.
    #
    # Linear mm/h wastes the entire useful range: 0.2 mm/h drizzle (which changes
    # everything about how a street sounds) and 0 mm/h would be indistinguishable,
    # while a 30 mm/h cell would flatten the top. Log compression keeps drizzle at
    # ~0.1, steady rain at ~0.5 and a downpour at 1.0.
    # ------------------------------------------------------------------
    def _precip_intensity() -> float:
        mm = _finite(now_obs.precipitation) if now_obs is not None else None
        if mm is None:
            note_missing("precip_intensity", "no precipitation value")
            return 0.0
        mm = max(mm, 0.0)
        if mm <= 0.0:
            return 0.0
        denom = math.log1p(PRECIP_FULL_MM / PRECIP_SCALE_MM)
        value = clamp(math.log1p(mm / PRECIP_SCALE_MM) / denom, 0.0, 1.0)
        if mm >= 4.0:
            notes.append(f"heavy rain, {mm:.1f} mm/h")
        elif mm >= 0.6:
            notes.append(f"rain, {mm:.1f} mm/h")
        else:
            notes.append("drizzle")
        return value

    precip_intensity = guard("precip_intensity", _precip_intensity, 0.0)

    # ------------------------------------------------------------------
    # 9. daylight_delta — the slow one, the one nobody notices consciously.
    #
    # Day length changes by up to ~4 minutes a day near the equinoxes at mid
    # latitudes and by essentially nothing at the solstices. Negative means the
    # year is closing in, which is a real and specific late-October feeling; the
    # same 8 degC in February with this dimension positive is an entirely different
    # record. Normalised against +/-290 s so the equinox peak nearly saturates.
    # ------------------------------------------------------------------
    def _daylight_delta() -> float:
        today = _finite(getattr(window, "daylight_seconds", None))
        yesterday = _finite(getattr(window, "daylight_seconds_yesterday", None))

        if today is None:
            sunrise = getattr(window, "sunrise", None)
            sunset = getattr(window, "sunset", None)
            if sunrise is not None and sunset is not None:
                today = (_as_utc(sunset) - _as_utc(sunrise)).total_seconds()
                ledger.note("sky.extract", "daylight_delta: derived today from sunrise/sunset")
        if today is None and coords is not None:
            today = daylight_seconds_for(coords.latitude, reference)
            if today is not None:
                ledger.note("sky.extract", "daylight_delta: today's daylight computed astronomically")

        if yesterday is None and coords is not None and today is not None:
            # The API gave no yesterday figure; recompute it from first principles for
            # the same latitude 24h earlier. Cheap, and better than dropping the dim.
            yesterday = daylight_seconds_for(coords.latitude, reference - timedelta(days=1))
            if yesterday is not None:
                ledger.note("sky.extract", "daylight_delta: yesterday's daylight computed astronomically")

        if today is None or yesterday is None:
            note_missing("daylight_delta", "no daylight duration for today and yesterday")
            return 0.0

        delta = today - yesterday
        if abs(delta) >= 45.0:
            direction = "shorter" if delta < 0 else "longer"
            notes.append(f"day {abs(delta) / 60.0:.0f} min {direction} than yesterday")
        return clamp(delta / DAYLIGHT_DELTA_FULL_S, -1.0, 1.0)

    daylight_delta = guard("daylight_delta", _daylight_delta, 0.0)

    if getattr(window, "stale", False):
        notes.append("using last-known-good weather")

    return SkyVector(
        pressure_trend_6h=pressure_trend_6h,
        pressure_norm_deviation=pressure_norm_deviation,
        temp_norm_deviation=temp_norm_deviation,
        sun_elevation=sun_elevation_dim,
        daylight_delta=daylight_delta,
        golden_hour_proximity=golden_hour_proximity,
        gust_variance=gust_variance,
        cloud_depth=cloud_depth,
        precip_intensity=precip_intensity,
        observed_at=observed_at,
        coordinates=coords,
        stale=bool(getattr(window, "stale", False)),
        notes=notes[:8],
    )


def _append_horizon_note(
    notes: list[str],
    coords: Coordinates,
    reference: datetime,
    elevation_deg: float,
) -> None:
    """Add a "N min to sunset" breadcrumb by walking the elevation forward/back.

    Derived from the computed elevation rather than the sunrise/sunset timestamps so
    it stays truthful when those are absent or meaningless.
    """
    rising = solar_elevation(coords.latitude, coords.longitude, reference + timedelta(minutes=10)) > elevation_deg
    step = 5
    for minutes in range(step, 241, step):
        probe = reference + timedelta(minutes=minutes)
        elev = solar_elevation(coords.latitude, coords.longitude, probe)
        if not rising and elev <= 0.0 < elevation_deg:
            notes.append(f"{minutes} min to sunset")
            return
        if rising and elev >= 0.0 > elevation_deg:
            notes.append(f"{minutes} min to sunrise")
            return
    if elevation_deg >= 0.0:
        notes.append("low sun" if elevation_deg < GOLDEN_CORE_DEG else "sun up")
    else:
        notes.append("just after sunset" if not rising else "just before sunrise")


def summarise(vector: SkyVector) -> str:
    """One dry sentence a human can read on the rationale card.

    Ordered by how much each dimension tends to dominate the felt experience:
    pressure derivative first, always.
    """
    parts: list[str] = []

    trend = vector.pressure_trend_6h
    if trend <= -0.6:
        parts.append("barometer collapsing")
    elif trend <= -0.25:
        parts.append("pressure falling")
    elif trend >= 0.6:
        parts.append("pressure building hard")
    elif trend >= 0.25:
        parts.append("pressure rising")
    else:
        parts.append("pressure holding")

    if vector.precip_intensity >= 0.6:
        parts.append("rain coming down")
    elif vector.precip_intensity >= 0.15:
        parts.append("wet air")

    if vector.golden_hour_proximity >= 0.6:
        parts.append("low golden light")
    elif vector.sun_elevation <= -0.8:
        parts.append("deep night")
    elif vector.sun_elevation >= 0.7:
        parts.append("high sun")

    if vector.cloud_depth >= 0.75:
        parts.append("heavy overcast")
    elif vector.cloud_depth <= 0.15:
        parts.append("clear")

    if vector.gust_variance >= 0.5:
        parts.append("unsettled gusty air")

    if vector.temp_norm_deviation >= 0.5:
        parts.append("well above the local norm")
    elif vector.temp_norm_deviation <= -0.5:
        parts.append("well below the local norm")

    if vector.daylight_delta <= -0.5:
        parts.append("the year closing in")
    elif vector.daylight_delta >= 0.5:
        parts.append("days opening out")

    summary = ", ".join(parts)
    return summary[:1].upper() + summary[1:] + "."
