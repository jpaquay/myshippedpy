"""Emit the real A2UI surface payloads to a fixture the Dart tests can render.

## Why this file exists

BAROGROOVE's UI is described in Python and rendered in Dart. Nothing in either
language's test suite used to look at the *other* side, so a Python change that
renamed a property, or wrapped an array in a ``ChildTemplate`` the Flutter
catalog has no builder for, produced a payload that parsed perfectly, validated
perfectly, passed 1119 Python tests -- and then degraded to a grey

    Missing data: "genreCorridor": no corridors bound to "items"

note in front of the user. Three separate regressions shipped that way.

This script is the seam. It runs the real surface builders over fixed sample
data and writes both published shapes of every surface:

  ``raw``      -- exactly what ``backend/app/a2ui/surfaces.py`` emits, which is
                  what the MCP stream serves.
  ``flutter``  -- the same messages after ``routes/surfaces.py``'s adapter, which
                  is what ``GET /api/surfaces/*`` serves.

Both are checked in at :data:`FIXTURE_PATH`. ``tests/test_a2ui_surface_contract.py``
asserts the file on disk is byte-identical to what this script produces, and
``frontend/test/a2ui_surface_contract_test.dart`` drives the *actual* renderer
over every surface in it and fails if any component falls through to a
placeholder. So a Python change that breaks a Dart binding fails CI twice: once
because the fixture is stale, and once -- after you regenerate it -- because the
renderer cannot bind the new shape.

Both shapes are covered deliberately. The REST adapter used to inject the array
bindings on its way to Flutter, which made the app look fine while the MCP
stream and the published contract stayed broken. Pinning only the adapted shape
would have re-created exactly that blind spot.

## Regenerating

    .venv/bin/python -m scripts.gen_a2ui_fixtures

Sample data is frozen here on purpose: no clock, no telemetry store, no
weather. A fixture that changes when you run it twice is not a contract.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.app.a2ui import palette as pal  # noqa: E402
from backend.app.a2ui import surfaces as sfc  # noqa: E402
from backend.app.contracts import (  # noqa: E402
    Coordinates,
    GenreCorridor,
    Playlist,
    Rationale,
    ScoredTrack,
    SonicVector,
    SkyVector,
    Theme,
    Track,
)
from backend.app.routes.surfaces import _to_flutter_a2ui  # noqa: E402

#: Where the generated payloads live. Under ``frontend/test`` rather than
#: ``frontend/a2ui`` because this is a test artefact, not a published contract
#: -- ``catalog.json`` is the published contract and it lives next door.
FIXTURE_PATH = _ROOT / "frontend" / "test" / "fixtures" / "a2ui_surfaces.json"

_FROZEN = datetime(2026, 3, 14, 17, 5, tzinfo=timezone.utc)
_BRUSSELS = Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels")


# --------------------------------------------------------------------------- #
# Frozen sample domain objects
# --------------------------------------------------------------------------- #


def _sky() -> SkyVector:
    return SkyVector(
        pressure_trend_6h=-0.88,
        pressure_norm_deviation=-0.79,
        temp_norm_deviation=0.42,
        sun_elevation=0.18,
        golden_hour_proximity=0.72,
        gust_variance=0.64,
        cloud_depth=0.83,
        precip_intensity=0.55,
        daylight_delta=-0.31,
        observed_at=_FROZEN,
        coordinates=_BRUSSELS,
        stale=False,
        notes=[
            "pressure fell 9.2 hPa in 6h",
            "38 min to sunset",
            "gusts swinging 14-33 km/h",
        ],
    )


def _themes() -> list[Theme]:
    """Every canonical theme, so the icon vocabulary is exercised in full."""
    return [
        Theme(
            id=theme_id,
            name=theme_id.replace("_", " ").title(),
            tagline=pal.THEME_INTENT[theme_id],
            description=pal.THEME_INTENT[theme_id],
            bias=SonicVector.neutral(),
            palette=dict(pal.THEME_PALETTES[theme_id]),
        )
        for theme_id in pal.THEME_IDS
    ]


def _corridors() -> list[GenreCorridor]:
    return [
        GenreCorridor(
            id="krautrock",
            name="Krautrock",
            description="Motorik pulse, patient repetition.",
            tags=["krautrock", "motorik", "kosmische"],
            width=0.4,
        ),
        GenreCorridor(
            id="ambient",
            name="Ambient",
            description="Space before notes.",
            tags=["ambient", "drone", "field recording"],
            width=0.7,
        ),
    ]


def _rationale() -> Rationale:
    return Rationale(
        headline="Pressure fell nine hectopascals; the music leans in.",
        body="A six-hour collapse of this size usually lands as restlessness.",
        sky_reading=[
            "Pressure trend -9.2 hPa/6h - the steepest fall in a fortnight.",
            "Gust variance 7.4 m/s - the wind is not settled.",
        ],
        sonic_moves=["energy +0.18", "acousticness -0.12", "grit +0.09"],
        taste_note="You reach for motorik when the barometer drops.",
        confidence=0.82,
        degraded=[],
    )


def _playlist() -> Playlist:
    roles = ["opener", "build", "peak", "descent", "closer"]
    return Playlist(
        id="pl-fixture-0001",
        title="Nine Hectopascals Down",
        subtitle="Petrichor x krautrock",
        tracks=[
            ScoredTrack(
                track=Track(
                    title=f"Track {i}",
                    artist=f"Artist {i}",
                    duration_ms=210_000 + i * 1000,
                    spotify_uri=f"spotify:track:{i:022d}",
                    tags=["krautrock"],
                ),
                score=0.9 - i * 0.05,
                sonic_distance=0.1 + i * 0.02,
                role=roles[i % len(roles)],
                position=i + 1,
                why=f"Sits at {i + 1} because the fall wants momentum here.",
            )
            for i in range(7)
        ],
        sky=_sky(),
        sonic_target=SonicVector(
            valence=0.31,
            energy=0.38,
            tempo=0.28,
            acousticness=0.44,
            density=0.52,
            grit=0.47,
            spatiality=0.78,
        ),
        theme_id="petrichor",
        genre_id="krautrock",
        rationale=_rationale(),
        created_at=_FROZEN,
        coordinates=_BRUSSELS,
    )


def _trajectories() -> list[dict[str, Any]]:
    return [
        {
            "trajectory_id": "traj_fixture_0001",
            "surface": "a2ui",
            "endpoint": "GET /api/surfaces/themes",
            "execution_path": "deterministic-fallback",
            "latency_ms": 1.5,
            "token_usage": {"total_tokens": 35},
            "trace_id": "trace_fixture_0001",
            "created_at": "2026-03-14T17:05:00Z",
            "status": "ok",
        },
        {
            "trajectory_id": "traj_fixture_0002",
            "surface": "advisor",
            "endpoint": "POST /api/advisor/ask",
            "execution_path": "gemini-2.5-flash",
            "latency_ms": 812.0,
            "token_usage": {"total_tokens": 1904},
            "trace_id": "trace_fixture_0002",
            "created_at": "2026-03-14T17:06:00Z",
            "status": "ok",
        },
    ]


def _summary() -> dict[str, Any]:
    return {
        "total_ai_calls": 2,
        "token_usage": {"total_tokens": 1939},
        "active_sessions": 1,
        "stored_memories": 7,
        "avg_latency_ms": 406.75,
    }


# --------------------------------------------------------------------------- #
# The fixture
# --------------------------------------------------------------------------- #


def build_surface_fixtures() -> dict[str, Any]:
    """Every surface, in both published shapes, from frozen sample data."""
    sky = _sky()
    playlist = _playlist()

    raw: dict[str, list[dict[str, Any]]] = {
        "sky": sfc.build_sky_surface(sky, surface_id="sky"),
        "themes": sfc.build_themes_surface(
            _themes(),
            _corridors(),
            selected_theme="petrichor",
            selected_genre="krautrock",
            surface_id="themes",
        ),
        "playlist": sfc.build_playlist_surface(playlist, surface_id="playlist"),
        "rationale": sfc.build_rationale_surface(
            _rationale(), surface_id="rationale"
        ),
        "almanac": sfc.build_almanac_surface([playlist], surface_id="almanac"),
        "telemetry": sfc.build_telemetry_surface(
            _trajectories(), _summary(), surface_id="telemetry"
        ),
        "error": sfc.build_error_surface(
            "We could not read your sky just now.",
            detail="upstream 503",
            surface_id="error",
        ),
    }

    # The adapter needs the domain objects for the numbers it backfills; the
    # surfaces that do not carry them get the plain pass-through, which is
    # exactly what the route does for them too.
    adapter_args: dict[str, dict[str, Any]] = {
        "sky": {"sky": sky},
        "playlist": {"playlist": playlist},
        "almanac": {"almanac_entries": [playlist]},
    }

    return {
        name: {
            "raw": messages,
            "flutter": _to_flutter_a2ui(
                messages, name, **adapter_args.get(name, {})
            ),
        }
        for name, messages in raw.items()
    }


def surface_fixtures_json() -> str:
    """The exact bytes that belong at :data:`FIXTURE_PATH`."""
    return json.dumps(build_surface_fixtures(), indent=2, sort_keys=False) + "\n"


def main() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(surface_fixtures_json(), encoding="utf-8")
    print(f"wrote {FIXTURE_PATH.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
