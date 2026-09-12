"""Open-Meteo forecast client.

Verified against the live endpoint rather than from memory. As of this writing
``GET https://api.open-meteo.com/v1/forecast`` with::

    hourly=surface_pressure,pressure_msl,temperature_2m,apparent_temperature,
           cloud_cover,precipitation,wind_gusts_10m,relative_humidity_2m
    daily=sunrise,sunset,daylight_duration
    timezone=auto&past_days=7&forecast_days=1

returns a columnar document:

    {"latitude":50.854,"longitude":4.35,"utc_offset_seconds":7200,
     "timezone":"Europe/Brussels","elevation":27.0,
     "hourly_units":{"time":"iso8601","surface_pressure":"hPa", ...},
     "hourly":{"time":["2026-09-03T00:00", ...192 entries...],
               "surface_pressure":[1016.8, ...], ...},
     "daily_units":{"daylight_duration":"s", ...},
     "daily":{"time":["2026-09-03", ...8 entries...],
              "sunrise":["2026-09-03T06:59", ...],
              "sunset":["2026-09-03T20:23", ...],
              "daylight_duration":[48302.44, ...]}}

Two things that bite:

* with ``timezone=auto`` every timestamp is **local wall time with no offset
  suffix**. The offset arrives separately as ``utc_offset_seconds`` and must be
  reattached by hand, otherwise everything is silently wrong by up to 14 hours.
* ``past_days=7&forecast_days=1`` yields 8 calendar days of hourly rows, ending at
  23:00 *today*. The tail of the array is therefore forecast, not observation, so
  "now" is the row nearest the reference instant — never the last row.

There is no API key for Open-Meteo's free tier and none is invented here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Final, Iterable, Mapping, Sequence

from ..config import Settings, get_settings
from ..contracts import Coordinates, WeatherObservation, WeatherWindow
from ..errors import DegradationLedger, WeatherUnavailable
from ..http import UpstreamError, get_json
from .cache import WeatherWindowCache

__all__ = ["OpenMeteoSource", "HOURLY_VARIABLES", "DAILY_VARIABLES"]

HOURLY_VARIABLES: Final[tuple[str, ...]] = (
    "surface_pressure",
    "pressure_msl",
    "temperature_2m",
    "apparent_temperature",
    "cloud_cover",
    "precipitation",
    "wind_gusts_10m",
    "relative_humidity_2m",
)

DAILY_VARIABLES: Final[tuple[str, ...]] = ("sunrise", "sunset", "daylight_duration")

#: Maps our WeatherObservation field names onto the hourly arrays. They happen to be
#: identical today; keeping the indirection means an upstream rename is a one-line fix.
_OBSERVATION_FIELDS: Final[dict[str, str]] = {
    "temperature_2m": "temperature_2m",
    "apparent_temperature": "apparent_temperature",
    "surface_pressure": "surface_pressure",
    "pressure_msl": "pressure_msl",
    "cloud_cover": "cloud_cover",
    "precipitation": "precipitation",
    "wind_gusts_10m": "wind_gusts_10m",
    "relative_humidity_2m": "relative_humidity_2m",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _tz_from_offset(seconds: Any) -> timezone:
    try:
        return timezone(timedelta(seconds=int(seconds)))
    except (TypeError, ValueError):
        return timezone.utc


def _parse_local(stamp: Any, tz: timezone) -> datetime | None:
    """Parse an Open-Meteo timestamp, attaching the document's offset if naive."""
    if not isinstance(stamp, str) or not stamp:
        return None
    text = stamp.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # Daily 'time' entries are bare dates.
        try:
            parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _column(block: Mapping[str, Any], name: str, length: int) -> Sequence[Any]:
    """A column of the right length, whatever upstream actually sent.

    Open-Meteo pads with nulls rather than truncating, but a short or absent array
    must not shift every subsequent row, so we normalise the length here.
    """
    raw = block.get(name)
    if not isinstance(raw, list):
        return [None] * length
    if len(raw) < length:
        return list(raw) + [None] * (length - len(raw))
    return raw


class OpenMeteoSource:
    """WeatherSource backed by Open-Meteo, with a two-tier cache in front of it.

    Failure policy, in order of preference:
      1. fresh cache hit -> serve it, no network;
      2. successful fetch -> serve it, populate both cache tiers;
      3. upstream error, last-known-good exists -> serve it with ``stale=True``;
      4. upstream error, nothing cached -> ``WeatherUnavailable``.

    Step 3 is why the cache exists. A stale window still produces a usable
    SkyVector: the 6-hour pressure derivative from two hours ago is a far better
    description of the current sky than a neutral vector is.
    """

    name = "open-meteo"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        cache: WeatherWindowCache | None = None,
        ledger: DegradationLedger | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        ttl = int(getattr(self._settings, "weather_cache_ttl_s", 900) or 900)
        self._cache = cache or WeatherWindowCache(ttl_s=ttl)
        self._ledger = ledger

    @property
    def cache(self) -> WeatherWindowCache:
        return self._cache

    # -- protocol ------------------------------------------------------------

    async def window(self, coords: Coordinates, at: datetime | None = None) -> WeatherWindow:
        reference = _as_utc(at) if at is not None else _utcnow()

        if bool(getattr(self._settings, "weather_offline", False)):
            # Offline mode is not a failure path; it is the demo path. Imported
            # lazily so the fixtures module never loads in normal operation.
            from .fixtures import FixtureWeatherSource

            self._note("weather_offline set, serving fixture window")
            return await FixtureWeatherSource().window(coords, reference)

        cached = await self._cache.get(coords, reference)
        if cached is not None:
            return cached

        try:
            payload = await self._fetch(coords)
        except UpstreamError as exc:
            return await self._degrade(coords, exc)

        try:
            window = self._parse(payload, coords, reference)
        except Exception as exc:  # malformed payload is an upstream fault too
            return await self._degrade(coords, exc)

        await self._cache.set(coords, window, reference)
        return window

    # -- internals -----------------------------------------------------------

    async def _fetch(self, coords: Coordinates) -> Any:
        params = {
            "latitude": f"{coords.latitude:.4f}",
            "longitude": f"{coords.longitude:.4f}",
            "hourly": ",".join(HOURLY_VARIABLES),
            "daily": ",".join(DAILY_VARIABLES),
            # 'auto' resolves the IANA zone from the coordinates; it is also what
            # makes 'daily' legal at all, since daily aggregation needs a zone.
            "timezone": coords.timezone or "auto",
            "past_days": int(getattr(self._settings, "open_meteo_past_days", 7) or 7),
            "forecast_days": 1,
        }
        return await get_json(
            str(getattr(self._settings, "open_meteo_base", "https://api.open-meteo.com/v1/forecast")),
            service=self.name,
            params=params,
            settings=self._settings,
        )

    async def _degrade(self, coords: Coordinates, exc: Exception) -> WeatherWindow:
        detail = getattr(exc, "service", None) and str(exc) or repr(exc)
        fallback = await self._cache.last_known_good(coords)
        if fallback is not None:
            self._note(f"open-meteo unavailable ({detail}); serving last-known-good window")
            return fallback.model_copy(update={"stale": True})
        raise WeatherUnavailable(
            f"open-meteo unavailable and no cached window for {coords.geohash(5)}: {detail}"
        ) from exc

    def _note(self, detail: str) -> None:
        if self._ledger is not None:
            self._ledger.note("sky.open_meteo", detail)

    def _parse(self, payload: Any, coords: Coordinates, reference: datetime) -> WeatherWindow:
        if not isinstance(payload, Mapping):
            raise ValueError("open-meteo returned a non-object payload")

        tz = _tz_from_offset(payload.get("utc_offset_seconds", 0))
        resolved = coords
        zone_name = payload.get("timezone")
        if isinstance(zone_name, str) and zone_name and (coords.timezone in (None, "", "auto")):
            resolved = coords.model_copy(update={"timezone": zone_name})

        history = self._parse_hourly(payload.get("hourly"), tz)
        if not history:
            raise ValueError("open-meteo returned no hourly rows")

        now_obs = self._pick_now(history, reference)
        sunrise, sunset, daylight_today, daylight_yesterday = self._parse_daily(
            payload.get("daily"), tz, reference
        )

        return WeatherWindow(
            coordinates=resolved,
            generated_at=_utcnow(),
            now=now_obs,
            history=history,
            sunrise=sunrise,
            sunset=sunset,
            daylight_seconds=daylight_today,
            daylight_seconds_yesterday=daylight_yesterday,
            stale=False,
            source=self.name,
        )

    def _parse_hourly(self, block: Any, tz: timezone) -> list[WeatherObservation]:
        if not isinstance(block, Mapping):
            return []
        times = block.get("time")
        if not isinstance(times, list):
            return []
        length = len(times)
        columns = {
            field: _column(block, source, length) for field, source in _OBSERVATION_FIELDS.items()
        }

        rows: list[WeatherObservation] = []
        for i, stamp in enumerate(times):
            moment = _parse_local(stamp, tz)
            if moment is None:
                # A row with no timestamp cannot be placed on the derivative
                # timeline, so it is worthless — drop it rather than guessing.
                continue
            rows.append(
                WeatherObservation(
                    time=moment,
                    **{field: _num(column[i]) for field, column in columns.items()},
                )
            )
        rows.sort(key=lambda o: o.time)
        return rows

    @staticmethod
    def _pick_now(history: Sequence[WeatherObservation], reference: datetime) -> WeatherObservation:
        """Nearest row to the reference instant.

        The array runs to 23:00 today, so its tail is forecast. Taking the last row
        would hand the extractor a pressure trend from the future — which would look
        plausible and be entirely wrong.
        """
        return min(history, key=lambda o: abs(_as_utc(o.time) - reference))

    @staticmethod
    def _parse_daily(
        block: Any,
        tz: timezone,
        reference: datetime,
    ) -> tuple[datetime | None, datetime | None, float | None, float | None]:
        if not isinstance(block, Mapping):
            return None, None, None, None
        days = block.get("time")
        if not isinstance(days, list) or not days:
            return None, None, None, None

        length = len(days)
        sunrises = _column(block, "sunrise", length)
        sunsets = _column(block, "sunset", length)
        daylight = _column(block, "daylight_duration", length)

        local_today = reference.astimezone(tz).date()
        index = _index_of_day(days, local_today)
        if index is None:
            # past_days + forecast_days=1 means today is normally last; fall back to
            # that rather than to day zero, which is a week old.
            index = length - 1

        sunrise = _parse_local(sunrises[index], tz)
        sunset = _parse_local(sunsets[index], tz)
        today = _num(daylight[index])
        yesterday = _num(daylight[index - 1]) if index >= 1 else None
        return sunrise, sunset, today, yesterday


def _index_of_day(days: Iterable[Any], target: date) -> int | None:
    for i, value in enumerate(days):
        if not isinstance(value, str):
            continue
        try:
            if date.fromisoformat(value[:10]) == target:
                return i
        except ValueError:
            continue
    return None
