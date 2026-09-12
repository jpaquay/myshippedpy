"""Unit tests for GoogleWeatherSource (`weather.googleapis.com` client)."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.contracts import Coordinates  # noqa: E402
from app.sky.fixtures import FixtureWeatherSource  # noqa: E402
from app.sky.google_weather import GoogleWeatherSource, _obs_from_google_payload  # noqa: E402


def test_obs_from_google_payload_maps_all_fields() -> None:
    payload = {
        "temperature": {"degrees": 18.4, "unit": "CELSIUS"},
        "feelsLikeTemperature": {"degrees": 17.9, "unit": "CELSIUS"},
        "airPressure": {"meanSeaLevelMillibars": 1024.8},
        "cloudCover": 72,
        "precipitation": {"qpf": {"quantity": 0.4, "unit": "MILLIMETERS"}},
        "wind": {
            "speed": {"value": 14.0, "unit": "KILOMETERS_PER_HOUR"},
            "gust": {"value": 23.0, "unit": "KILOMETERS_PER_HOUR"},
        },
        "relativeHumidity": 68,
    }
    ts = datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)
    obs = _obs_from_google_payload(payload, ts)
    assert obs.time == ts
    assert obs.temperature_2m == pytest.approx(18.4)
    assert obs.apparent_temperature == pytest.approx(17.9)
    assert obs.surface_pressure == pytest.approx(1024.8)
    assert obs.pressure_msl == pytest.approx(1024.8)
    assert obs.cloud_cover == pytest.approx(72.0)
    assert obs.precipitation == pytest.approx(0.4)
    assert obs.wind_gusts_10m == pytest.approx(23.0)
    assert obs.relative_humidity_2m == pytest.approx(68.0)


@pytest.mark.asyncio
async def test_google_weather_source_falls_back_when_no_adc(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = FixtureWeatherSource()
    src = GoogleWeatherSource(fallback=fallback)  # type: ignore[arg-type]
    monkeypatch.setattr(src, "_get_adc_headers", lambda: None)

    coords = Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels")
    win = await src.window(coords, datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc))
    assert win.coordinates == coords
    assert win.now.temperature_2m is not None
