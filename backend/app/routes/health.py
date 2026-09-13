"""Root and readiness routes.

``/`` is a human-readable landing payload; ``/healthz`` is what Cloud Run
polls and must stay dependency-free and instant.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ..config import get_settings

router = APIRouter(tags=["ops"])


# HEAD is listed explicitly. Starlette's plain ``Route`` derives HEAD from GET;
# FastAPI's ``APIRoute`` does not, so uptime checks, link unfurlers and
# ``curl -I`` were all answered with 405 (see the bg.netdev.be and
# barogroove.netdev.be entries at 21:32 and 22:20 on 2026-09-13). Starlette
# drops the body for HEAD on the way out, so the handler needs no branch.
@router.api_route("/", methods=["GET", "HEAD"], summary="What this thing is")
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
@router.get("/api/healthz", response_class=PlainTextResponse, include_in_schema=False)
async def healthz() -> str:
    """Cloud Run liveness probe. No imports, no I/O, no opinions."""
    return "ok"
