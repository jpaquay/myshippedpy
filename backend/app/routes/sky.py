"""HTTP surface for the SkyVector engine.

Design rule for this router: it must never 500 because the weather is unavailable.
A playlist app that shows an error page when an upstream feed hiccups is worse than
one that says "we cannot read the sky right now" and hands back the neutral vector.
Degradation is reported in the payload, not in the status code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Final

from fastapi import APIRouter, Query

from ..contracts import SKY_DIMS, Coordinates, SkyVector
from ..errors import DegradationLedger, WeatherUnavailable
from ..sky.extract import extract_sky_vector, summarise
from ..sky.fixtures import BRUSSELS, SCENARIOS, FixtureWeatherSource

router = APIRouter(prefix="/api/sky", tags=["sky"])

_DEFAULT_LAT: Final[float] = BRUSSELS.latitude
_DEFAULT_LON: Final[float] = BRUSSELS.longitude


def _payload(
    vector: SkyVector,
    *,
    source: str,
    ledger: DegradationLedger,
    summary: str | None = None,
) -> dict[str, Any]:
    return {
        "dims": list(SKY_DIMS),
        "vector": vector.as_dict(),
        "array": vector.as_array(),
        "summary": summary if summary is not None else summarise(vector),
        "notes": list(vector.notes),
        "observed_at": vector.observed_at.isoformat() if vector.observed_at else None,
        "coordinates": vector.coordinates.model_dump() if vector.coordinates else None,
        "stale": vector.stale,
        "source": source,
        "degraded": not ledger.clean,
        "degradations": ledger.as_list(),
    }


@router.get("/vector", summary="Current sky vector for a location")
async def get_sky_vector(
    lat: float = Query(_DEFAULT_LAT, ge=-90.0, le=90.0, description="Latitude, WGS84."),
    lon: float = Query(_DEFAULT_LON, ge=-180.0, le=180.0, description="Longitude, WGS84."),
    scenario: str | None = Query(
        None,
        description="Force a canned fixture scenario instead of live weather.",
    ),
    at: datetime | None = Query(
        None,
        description="Evaluate the sky at this instant instead of now. Mostly for demos.",
    ),
) -> dict[str, Any]:
    ledger = DegradationLedger()
    coords = Coordinates(latitude=lat, longitude=lon, timezone="auto")
    reference = at.astimezone(timezone.utc) if at and at.tzinfo else at

    if scenario is not None and scenario not in SCENARIOS:
        ledger.note("sky.routes", f"unknown scenario {scenario!r}, falling back to live weather")
        scenario = None

    if scenario is not None:
        source: Any = FixtureWeatherSource(scenario)
    else:
        # Imported lazily: the container wires the whole application together, and a
        # module-level import here would make this router unloadable in isolation
        # (and in tests, which must run with no container and no network).
        try:
            from ..container import get_container

            source = get_container().weather()
        except Exception as exc:
            ledger.note("sky.routes", f"weather source unavailable ({type(exc).__name__})")
            return _payload(
                SkyVector.neutral(),
                source="none",
                ledger=ledger,
                summary="No sky reading available.",
            )

    source_name = getattr(source, "name", "unknown")
    try:
        window = await source.window(coords, reference)
    except WeatherUnavailable as exc:
        ledger.note("sky.routes", f"weather unavailable: {exc}")
        return _payload(
            SkyVector.neutral(),
            source=source_name,
            ledger=ledger,
            summary="No sky reading available.",
        )
    except Exception as exc:
        # Anything else is a bug, but a bug must not cost the user their playlist.
        ledger.note("sky.routes", f"weather lookup failed ({type(exc).__name__})")
        return _payload(
            SkyVector.neutral(),
            source=source_name,
            ledger=ledger,
            summary="No sky reading available.",
        )

    vector = extract_sky_vector(window, at=reference, ledger=ledger)
    return _payload(vector, source=getattr(window, "source", source_name), ledger=ledger)


@router.get("/scenarios", summary="Available fixture scenarios")
async def list_scenarios() -> dict[str, Any]:
    return {
        "default": "front_collapse",
        "scenarios": [
            {"name": spec.key, "description": spec.description, "tags": list(spec.tags)}
            for spec in SCENARIOS.values()
        ],
    }
