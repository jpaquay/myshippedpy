"""Root and readiness routes.

``/`` is a human-readable landing payload; ``/healthz`` is what Cloud Run
polls and must stay dependency-free and instant.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ..config import get_settings

router = APIRouter(tags=["ops"])


@router.get("/", summary="What this thing is")
async def root() -> dict[str, object]:
    settings = get_settings()
    return {
        "service": "BAROGROOVE",
        "tagline": "your sky has a soundtrack",
        "insight": (
            "Weather's emotional signal lives in the derivative. 8 °C on a falling "
            "barometer forty minutes before sunset is not the same record as 8 °C on "
            "a rising barometer at ten in the morning."
        ),
        "host": settings.public_host,
        "docs": "/api/docs",
        "health": "/api/health",
        "legacy": "/legacy",
        "mcp": "/mcp",
    }


@router.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
async def healthz() -> str:
    """Cloud Run liveness probe. No imports, no I/O, no opinions."""
    return "ok"
