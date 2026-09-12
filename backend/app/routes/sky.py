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
from ..sky.geocaches import (
    STREET_ART_GEOCACHES,
    StreetArtGeoCache,
    find_nearest_geocache,
    get_geocache,
    pick_random_geocache,
)

router = APIRouter(prefix="/api/sky", tags=["sky"])

_DEFAULT_LAT: Final[float] = BRUSSELS.latitude
_DEFAULT_LON: Final[float] = BRUSSELS.longitude


def _geocache_dict(gc: StreetArtGeoCache, utc_now: datetime | None = None) -> dict[str, Any]:
    return {
        "id": gc.id,
        "name": gc.name,
        "city": gc.city,
        "country": gc.country,
        "label": gc.label,
        "lat": gc.lat,
        "lon": gc.lon,
        "tz_offset_hours": gc.tz_offset_hours,
        "local_time": gc.local_time_label(utc_now),
        "day_period": gc.day_period(utc_now),
        "artist_highlight": gc.artist_highlight,
        "description": gc.description,
        "vibe_tags": list(gc.vibe_tags),
    }


def _payload(
    vector: SkyVector,
    *,
    source: str,
    ledger: DegradationLedger,
    summary: str | None = None,
    geocache: StreetArtGeoCache | None = None,
) -> dict[str, Any]:
    gc = geocache or (
        find_nearest_geocache(vector.coordinates.latitude, vector.coordinates.longitude)
        if vector.coordinates
        else None
    )
    return {
        "dims": list(SKY_DIMS),
        "vector": vector.as_dict(),
        "array": vector.as_array(),
        "summary": summary if summary is not None else summarise(vector),
        "notes": list(vector.notes),
        "observed_at": vector.observed_at.isoformat() if vector.observed_at else None,
        "coordinates": vector.coordinates.model_dump() if vector.coordinates else None,
        "geocache": _geocache_dict(gc) if gc else None,
        "stale": vector.stale,
        "source": source,
        "degraded": not ledger.clean,
        "degradations": ledger.as_list(),
    }


@router.get("/geocaches", summary="Curated World Street-Art Geo-Cache landmarks")
async def list_geocaches(
    random_pick: bool = Query(False, alias="random", description="Return a pseudo-random landmark"),
    exclude_id: str | None = Query(None, description="Optional landmark ID to exclude when random"),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    items = [_geocache_dict(gc, now) for gc in STREET_ART_GEOCACHES]
    picked = pick_random_geocache(exclude_id) if random_pick else STREET_ART_GEOCACHES[0]
    return {
        "count": len(items),
        "selected": _geocache_dict(picked, now),
        "geocaches": items,
        "items": items,
    }


@router.get("/vector", summary="Current sky vector for a location or street-art geo-cache")
async def get_sky_vector(
    lat: float = Query(_DEFAULT_LAT, ge=-90.0, le=90.0, description="Latitude, WGS84."),
    lon: float = Query(_DEFAULT_LON, ge=-180.0, le=180.0, description="Longitude, WGS84."),
    geocache_id: str | None = Query(
        None,
        description="Optional street-art geo-cache ID or 'random' to override lat/lon.",
    ),
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
    matched_gc: StreetArtGeoCache | None = get_geocache(geocache_id)
    if matched_gc is not None:
        lat = matched_gc.lat
        lon = matched_gc.lon
        coords = Coordinates(latitude=lat, longitude=lon, label=matched_gc.label, timezone="auto")
    else:
        coords = Coordinates(latitude=lat, longitude=lon, timezone="auto")
        matched_gc = find_nearest_geocache(lat, lon)

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
                geocache=matched_gc,
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
            geocache=matched_gc,
        )
    except Exception as exc:
        # Anything else is a bug, but a bug must not cost the user their playlist.
        ledger.note("sky.routes", f"weather lookup failed ({type(exc).__name__})")
        return _payload(
            SkyVector.neutral(),
            source=source_name,
            ledger=ledger,
            summary="No sky reading available.",
            geocache=matched_gc,
        )

    vector = extract_sky_vector(window, at=reference, ledger=ledger)
    if matched_gc and vector.coordinates:
        vector = vector.model_copy(
            update={"coordinates": vector.coordinates.model_copy(update={"label": matched_gc.label})}
        )
    return _payload(
        vector,
        source=getattr(window, "source", source_name),
        ledger=ledger,
        geocache=matched_gc,
    )


@router.get("/scenarios", summary="Available fixture scenarios")
async def list_scenarios() -> dict[str, Any]:
    items = [
        {"id": spec.key, "name": spec.key, "description": spec.description, "tags": list(spec.tags)}
        for spec in SCENARIOS.values()
    ]
    return {
        "default": "front_collapse",
        "scenarios": items,
        "items": items,
    }
