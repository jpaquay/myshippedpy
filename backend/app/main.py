"""FastAPI application factory.

The entry point stays ``app.py`` at the repo root — that is the one file this
project inherited from its hello-world ancestor and it keeps its job. This
module is where the real assembly happens.

Router mounting is *defensive*: each optional router is imported inside a
try/except so a half-finished subsystem degrades to "that route 404s" instead
of "the container won't start". Cloud Run's health check is the only thing
that must never break.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .container import get_container
from .errors import BarogrooveError
from .http import close_client, stats

log = logging.getLogger("barogroove")

DESCRIPTION = """
**Your sky has a soundtrack.**

BAROGROOVE reads the local weather, takes its *derivative*, converts that into
a target musical feeling, crosses it with your real listening history and a
chosen theme, and forges a playlist that explains itself.

Weather's emotional signal lives in the change, not the value. 8 °C on a
falling barometer forty minutes before sunset is a different record from 8 °C
on a rising barometer at ten in the morning.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    log.info("BAROGROOVE starting — env=%s region=%s host=%s",
             settings.environment, settings.gcp_region, settings.public_host)
    for line in settings.degraded_modes():
        log.warning("degraded | %s", line)
    app.state.started_at = time.time()
    app.state.settings = settings
    app.state.container = get_container()
    try:
        yield
    finally:
        await close_client()
        log.info("BAROGROOVE stopped.")


_OPTIONAL_ROUTERS: list[str] = [
    "backend.app.routes.sky",
    "backend.app.routes.themes",
    "backend.app.routes.forge",
    "backend.app.routes.pairing",
    "backend.app.routes.almanac",
    "backend.app.routes.surfaces",
    "backend.app.routes.advisor",
    "backend.app.routes.dataviz",
]


def _mount(app: FastAPI, module_path: str, attr: str = "router", *, label: str) -> bool:
    """Import and include a router, tolerating an absent/broken subsystem."""
    try:
        module = __import__(module_path, fromlist=[attr])
        app.include_router(getattr(module, attr))
        return True
    except Exception as exc:  # pragma: no cover - depends on build stage
        log.warning("router %-10s unavailable: %s", label, exc)
        app.state.missing_routers = getattr(app.state, "missing_routers", [])
        app.state.missing_routers.append(f"{label}: {exc}")
        return False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="BAROGROOVE",
        description=DESCRIPTION,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.missing_routers = []

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"https://{settings.public_host}",
            "http://localhost:5000",
            "http://localhost:8080",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _timing(request: Request, call_next):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Barogroove-Ms"] = f"{elapsed_ms:.1f}"
        return response

    @app.exception_handler(BarogrooveError)
    async def _domain_error(request: Request, exc: BarogrooveError) -> JSONResponse:
        log.warning("domain error on %s: %s", request.url.path, exc)
        return JSONResponse(status_code=422, content={"error": type(exc).__name__, "detail": str(exc)})

    # --- always available -------------------------------------------------
    from .routes.health import router as health_router
    from .routes.legacy import router as legacy_router

    app.include_router(health_router)
    app.include_router(legacy_router)

    # --- built by parallel workers; each may not exist yet ----------------
    _mount(app, "backend.app.routes.sky", label="sky")
    _mount(app, "backend.app.routes.themes", label="themes")
    _mount(app, "backend.app.routes.forge", label="forge")
    _mount(app, "backend.app.routes.pairing", label="pairing")
    _mount(app, "backend.app.routes.almanac", label="almanac")
    _mount(app, "backend.app.routes.surfaces", label="surfaces")
    _mount(app, "backend.app.routes.advisor", label="advisor")
    _mount(app, "backend.app.routes.dataviz", label="dataviz")

    @app.get("/callback", include_in_schema=False)
    async def _root_oauth_callback(request: Request):  # type: ignore[no-untyped-def]
        from .routes.pairing import generic_callback, get_spotify_auth

        return await generic_callback(
            request=request,
            code=request.query_params.get("code"),
            state=request.query_params.get("state"),
            token=request.query_params.get("token"),
            error=request.query_params.get("error"),
            auth=get_spotify_auth(),
        )

    # --- MCP server, streamable HTTP, mounted on this same app ------------
    #
    # OFF for now. `mcp_enabled` defaults False, so /mcp is not mounted and the
    # path 404s rather than existing-and-refusing. This is a deliberate hold on
    # exposing the agent surface, not a bug and not a fallback: the code below
    # is complete, guarded and fully tested, it is simply not wired up yet.
    #
    # Turn it on with BG_MCP_ENABLED=1. See backend/app/mcp/principal.py first.
    if getattr(settings, "mcp_enabled", False):
        try:
            from .mcp.server import mount_mcp

            mount_mcp(app)
            log.info("MCP server mounted at /mcp")
        except Exception as exc:  # pragma: no cover
            log.warning("MCP server unavailable: %s", exc)
            app.state.missing_routers.append(f"mcp: {exc}")
    else:
        log.info("MCP endpoint disabled (mcp_enabled=False); /mcp is not mounted")
        app.state.mcp_enabled = False

    @app.get("/api/health", tags=["ops"], summary="Liveness + capability report")
    async def health() -> dict[str, object]:
        s = stats()
        container = getattr(app.state, "container", None)
        return {
            "status": "ok",
            "service": "barogroove",
            "version": "1.0.0",
            "environment": settings.environment,
            "region": settings.gcp_region,
            "uptime_s": round(time.time() - getattr(app.state, "started_at", time.time()), 1),
            "capabilities": settings.capability_report(),
            "degraded": settings.degraded_modes(),
            "missing_routers": app.state.missing_routers,
            "subsystem_fallbacks": container.failures if container else {},
            "http": {"requests": s.requests, "retries": s.retries, "failures": s.failures},
        }

    @app.get("/auth/lastfm/callback", include_in_schema=False)
    async def lastfm_legacy_callback(request: Request) -> object:
        from fastapi.responses import RedirectResponse

        qs = request.url.query
        target = f"/api/pair/lastfm/callback?{qs}" if qs else "/api/pair/lastfm/callback"
        return RedirectResponse(url=target, status_code=302)

    return app
