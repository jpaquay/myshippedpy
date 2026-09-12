"""Google Cloud Weather API client (`weather.googleapis.com`).

Uses Google Cloud Application Default Credentials (ADC) with the
``X-Goog-User-Project`` header so Cloud Run services can query Google's
first-party Weather API directly via IAM (`roles/serviceusage.serviceUsageConsumer`)
without static API keys.

Endpoints queried:
  - ``GET https://weather.googleapis.com/v1/currentConditions:lookup``
  - ``GET https://weather.googleapis.com/v1/history/hours:lookup?hours=24``

If ADC credentials are unavailable (e.g. local unit test environments) or if
the upstream Google Weather call fails, transparently falls back to
``OpenMeteoSource`` so the weather pipeline never breaks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..contracts import Coordinates, WeatherObservation, WeatherWindow
from ..errors import DegradationLedger
from .cache import WeatherWindowCache
from .extract import daylight_seconds_for
from .open_meteo import OpenMeteoSource

logger = logging.getLogger(__name__)

_CURRENT_URL = "https://weather.googleapis.com/v1/currentConditions:lookup"
_HISTORY_URL = "https://weather.googleapis.com/v1/history/hours:lookup"


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _num(d: Any, *keys: str) -> float | None:
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    if cur is None:
        return None
    try:
        return float(cur)
    except (TypeError, ValueError):
        return None


def _obs_from_google_payload(payload: dict[str, Any], timestamp: datetime) -> WeatherObservation:
    temp = _num(payload, "temperature", "degrees")
    feels = _num(payload, "feelsLikeTemperature", "degrees")
    msl = _num(payload, "airPressure", "meanSeaLevelMillibars")
    clouds = _num(payload, "cloudCover")
    precip = _num(payload, "precipitation", "qpf", "quantity")
    gust = _num(payload, "wind", "gust", "value")
    if gust is None:
        gust = _num(payload, "wind", "speed", "value")
    rh = _num(payload, "relativeHumidity")

    return WeatherObservation(
        time=timestamp,
        temperature_2m=temp,
        apparent_temperature=feels if feels is not None else temp,
        surface_pressure=msl,
        pressure_msl=msl,
        cloud_cover=clouds,
        precipitation=precip if precip is not None else 0.0,
        wind_gusts_10m=gust,
        relative_humidity_2m=rh,
    )


class GoogleWeatherSource:
    """Primary WeatherSource backed by Google Cloud Weather API (`weather.googleapis.com`)."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        cache: WeatherWindowCache | None = None,
        fallback: OpenMeteoSource | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._cache = cache or WeatherWindowCache()
        self._fallback = fallback or OpenMeteoSource(settings=self._settings, cache=self._cache)
        self._project_id = self._settings.gcp_project or "netdev-firebase"

    def _get_adc_headers(self) -> dict[str, str] | None:
        try:
            import google.auth
            import google.auth.transport.requests

            creds, project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            req = google.auth.transport.requests.Request()
            creds.refresh(req)
            if not creds.token:
                return None
            quota_project = self._project_id or project or "netdev-firebase"
            return {
                "Authorization": f"Bearer {creds.token}",
                "X-Goog-User-Project": quota_project,
            }
        except Exception as exc:
            logger.debug("Google Weather ADC token unavailable: %s", exc)
            return None

    async def window(
        self,
        coords: Coordinates,
        at: datetime | None = None,
        *,
        ledger: DegradationLedger | None = None,
    ) -> WeatherWindow:
        ref_time = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cached = await self._cache.get(coords, ref_time)
        if cached is not None:
            return cached
        headers = self._get_adc_headers()
        if not headers:
            return await self._fallback.window(coords, ref_time)

        params_cur = {
            "location.latitude": f"{coords.latitude:.4f}",
            "location.longitude": f"{coords.longitude:.4f}",
        }
        params_hist = {
            "location.latitude": f"{coords.latitude:.4f}",
            "location.longitude": f"{coords.longitude:.4f}",
            "hours": "24",
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                cur_resp = await client.get(_CURRENT_URL, params=params_cur, headers=headers)
                hist_resp = await client.get(_HISTORY_URL, params=params_hist, headers=headers)

            if cur_resp.status_code != 200:
                logger.warning(
                    "Google Weather currentConditions returned %s: %s",
                    cur_resp.status_code,
                    cur_resp.text[:200],
                )
                return await self._fallback.window(coords, ref_time)

            cur_data = cur_resp.json()
            now_ts = _parse_iso(cur_data.get("currentTime")) or ref_time
            now_obs = _obs_from_google_payload(cur_data, now_ts)

            google_history: list[WeatherObservation] = []
            if hist_resp.status_code == 200:
                hist_data = hist_resp.json()
                for row in hist_data.get("historyHours", []):
                    ts = _parse_iso(row.get("interval", {}).get("startTime"))
                    if ts is not None:
                        google_history.append(_obs_from_google_payload(row, ts))

            # Optionally enrich older (>24h) baseline history from OpenMeteo for 7-day z-scores
            merged_by_hour: dict[int, WeatherObservation] = {}
            try:
                om_win = await self._fallback.window(coords, ref_time)
                for obs in om_win.history:
                    hour_key = int(obs.time.timestamp() // 3600)
                    merged_by_hour[hour_key] = obs
            except Exception:
                pass

            for obs in google_history:
                hour_key = int(obs.time.timestamp() // 3600)
                merged_by_hour[hour_key] = obs

            now_key = int(now_obs.time.timestamp() // 3600)
            merged_by_hour[now_key] = now_obs

            history_sorted = sorted(merged_by_hour.values(), key=lambda o: o.time)

            daylight_today = daylight_seconds_for(coords.latitude, ref_time.date())
            from datetime import timedelta

            daylight_yest = daylight_seconds_for(
                coords.latitude, (ref_time - timedelta(days=1)).date()
            )

            win = WeatherWindow(
                coordinates=coords,
                generated_at=datetime.now(timezone.utc),
                now=now_obs,
                history=history_sorted,
                daylight_seconds=daylight_today,
                daylight_seconds_yesterday=daylight_yest,
                stale=False,
                source="google-weather",
            )
            await self._cache.set(coords, win, ref_time)
            return win
        except Exception as exc:
            logger.warning("Google Weather lookup failed (%s); falling back to Open-Meteo", exc)
            return await self._fallback.window(coords, ref_time)
