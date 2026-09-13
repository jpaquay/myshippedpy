#!/usr/bin/env python3
"""Backend route smoke pass.

Boots the real FastAPI app **offline** (same environment pinning as
``tests/conftest.py``), enumerates *every* route the app actually exposes by
introspecting ``app.routes`` -- including routers mounted through
``include_router``, which modern FastAPI wraps in ``_IncludedRouter`` shims --
and fires one plausible request at each of them through
``fastapi.testclient.TestClient``. No sockets, no upstream calls.

Why introspection rather than a hand-written list: a route that nobody
remembered to document is exactly the route that rots. If a new path appears
without a case here, this script fails with ``no-case`` so somebody has to
look at it.

Each case declares the statuses it considers acceptable. "Acceptable" is not
the same as "healthy" -- with no network, several routes are *expected* to
degrade (fixture sky, unpaired Last.fm, no Firestore). Those are tagged
``offline`` and their expected status reflects the degraded-but-graceful
contract: a structured JSON body, never a 500 stack trace.

Usage::

    python -m scripts.smoke_routes            # table + exit code
    python -m scripts.smoke_routes --json     # machine-readable
    python -m scripts.smoke_routes --verbose  # include response snippets

Exit code is 0 only when every route answered with a status it is allowed to
answer with, and every route has a case. Anything else is a regression.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# --------------------------------------------------------------------------
# Offline posture -- mirrors tests/conftest.py::_offline_env
# --------------------------------------------------------------------------

OFFLINE_ENV = {
    "BG_ENVIRONMENT": "local",
    "BG_WEATHER_OFFLINE": "1",
    "BG_LASTFM_ENABLED": "0",
    "BG_LASTFM_API_KEY": "",
    "BG_SPOTIFY_CLIENT_ID": "",
    "BG_SPOTIFY_CLIENT_SECRET": "",
    "BG_GCP_PROJECT": "",
    "BG_FIREBASE_PROJECT_ID": "",
    "BG_USE_SECRET_MANAGER": "0",
}


def pin_offline() -> None:
    os.environ.update(OFFLINE_ENV)
    from backend.app.config import reload_settings
    from backend.app.container import reset_container
    from backend.app.http import reset_client

    reload_settings()
    reset_container()
    reset_client()


# --------------------------------------------------------------------------
# Case model
# --------------------------------------------------------------------------

BRUSSELS = {"latitude": 50.8503, "longitude": 4.3517, "timezone": "Europe/Brussels", "label": "Brussels"}
USER_HDR = {"X-Barogroove-User": "smoke-user"}

#: 500 is never acceptable anywhere: BAROGROOVE's whole premise is that
#: *something* comes back. Other 5xx are tolerated only where a case declares
#: them explicitly AND the body is structured JSON (see ``_is_ok``).
ALWAYS_FATAL = {500}


@dataclass
class Case:
    """One request we fire at one route."""

    method: str
    path: str  #: the registered template, e.g. ``/api/themes/{theme_id}``
    sent: str  #: human-readable description for the results table
    params: dict[str, Any] | None = None
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    expect: tuple[int, ...] = (200,)
    #: ``core`` = must work fully offline; ``offline`` = degradation expected;
    #: ``oauth`` = unpaired/unconfigured provider handshake.
    kind: str = "core"
    #: Fill ``{placeholders}`` in ``path`` from the shared context dict.
    path_params: Callable[[dict], dict[str, str]] | None = None
    #: Late-bind the body from the shared context (e.g. echo a forged playlist).
    body_from: Callable[[dict], Any] | None = None
    #: Stash something from the response for later cases.
    capture: Callable[[dict, Any], None] | None = None
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.method.upper(), self.path)


# --------------------------------------------------------------------------
# A forged playlist, for POST /api/forge/explain -- the UI round-trips exactly
# this shape back to the backend when it wants a fresh rationale.
# --------------------------------------------------------------------------


def _explain_body(ctx: dict) -> Any:
    forged = ctx.get("forged")
    if forged:
        return forged
    # Fallback: minimum viable Playlist if the forge never produced one.
    return {
        "id": "smoke-fallback",
        "title": "Smoke fallback",
        "sky": ctx.get("sky") or {},
        "sonic_target": {},
        "theme_id": ctx.get("theme_id") or "petrichor",
        "rationale": {},
    }


def _capture_forge(ctx: dict, payload: Any) -> None:
    # POST /api/forge answers with an envelope: {"playlist": {...}, "degraded":
    # [...], "elapsed_ms": ...}. The Playlist itself is one level down.
    if not isinstance(payload, dict):
        return
    playlist = payload.get("playlist") if isinstance(payload.get("playlist"), dict) else payload
    if not playlist.get("id"):
        return
    ctx["forged"] = playlist
    ctx["playlist_id"] = playlist["id"]
    for scored in playlist.get("tracks") or []:
        track = scored.get("track") if isinstance(scored, dict) else None
        key = (track or {}).get("key") if isinstance(track, dict) else None
        if key:
            ctx["track_key"] = key
            break


def _capture_theme(ctx: dict, payload: Any) -> None:
    if isinstance(payload, dict):
        themes = payload.get("themes") or []
        if themes:
            ctx["theme_id"] = themes[0].get("id")


def _capture_geocache(ctx: dict, payload: Any) -> None:
    if isinstance(payload, dict):
        caches = payload.get("geocaches") or []
        if caches:
            ctx["geocache_id"] = caches[0].get("id")


def _capture_sky(ctx: dict, payload: Any) -> None:
    if isinstance(payload, dict):
        ctx["sky"] = payload.get("sky") or payload


def _capture_memory(ctx: dict, payload: Any) -> None:
    if isinstance(payload, dict):
        mem = payload.get("memory") or payload
        if isinstance(mem, dict) and mem.get("id"):
            ctx["memory_id"] = mem["id"]


def _capture_first_id(field_name: str, ctx_key: str) -> Callable[[dict, Any], None]:
    def _cap(ctx: dict, payload: Any) -> None:
        if isinstance(payload, dict):
            rows = payload.get(field_name) or []
            if rows and isinstance(rows[0], dict):
                for k in ("id", f"{ctx_key}", "session_id", "conversation_id", "trajectory_id"):
                    if rows[0].get(k):
                        ctx[ctx_key] = rows[0][k]
                        return

    return _cap


def _pp(name: str, ctx_key: str, default: str) -> Callable[[dict], dict[str, str]]:
    def _f(ctx: dict) -> dict[str, str]:
        return {name: str(ctx.get(ctx_key) or default)}

    return _f


# --------------------------------------------------------------------------
# The cases. Ordered: reads that seed context first, then writes.
# --------------------------------------------------------------------------

CASES: list[Case] = [
    # ---- ops / liveness -------------------------------------------------
    Case("GET", "/api/health", "no args", expect=(200,)),
    Case("GET", "/api/healthz", "no args", expect=(200,)),
    Case("GET", "/healthz", "no args", expect=(200,)),
    Case("GET", "/", "no args", expect=(200,)),
    Case("GET", "/api/openapi.json", "no args", expect=(200,)),
    Case("GET", "/api/docs", "no args", expect=(200,)),
    Case("GET", "/docs/oauth2-redirect", "no args", expect=(200,)),
    Case("GET", "/legacy", "no args", expect=(200,)),
    Case("GET", "/legacy/about", "no args", expect=(200,)),

    # ---- reference data (must be pure, offline) -------------------------
    Case("GET", "/api/themes", "no args", capture=_capture_theme),
    Case("GET", "/api/genres", "no args"),
    Case(
        "GET",
        "/api/themes/{theme_id}",
        "theme_id from /api/themes",
        path_params=_pp("theme_id", "theme_id", "petrichor"),
    ),
    Case(
        "GET",
        "/api/themes/suggest",
        "lat/lon = Brussels",
        params={"lat": 50.8503, "lon": 4.3517},
        kind="offline",
    ),

    # ---- sky ------------------------------------------------------------
    Case("GET", "/api/sky/scenarios", "no args"),
    Case("GET", "/api/sky/geocaches", "no args", capture=_capture_geocache),
    Case("GET", "/api/sky/geocaches", "random=true", params={"random": True}),
    Case(
        "GET",
        "/api/sky/vector",
        "lat/lon = Brussels, scenario=front_collapse",
        params={"lat": 50.8503, "lon": 4.3517, "scenario": "front_collapse"},
        capture=_capture_sky,
        kind="offline",
    ),

    # ---- A2UI surfaces --------------------------------------------------
    Case("GET", "/api/surfaces/catalog", "no args"),
    Case("GET", "/api/surfaces/catalog.json", "no args"),
    Case("GET", "/api/surfaces/health", "no args"),
    Case(
        "GET",
        "/api/surfaces/sky",
        "lat/lon = Brussels, single=true",
        params={"lat": 50.8503, "lon": 4.3517, "single": True},
        kind="offline",
    ),
    Case("GET", "/api/surfaces/themes", "theme=petrichor, genre=any", params={"theme": "petrichor", "genre": "any"}),
    Case("GET", "/api/surfaces/telemetry", "single=false", params={"single": False}),
    Case(
        "POST",
        "/api/surfaces/action",
        "selectTheme chip tap (args.themeId=petrichor)",
        body={
            "action": "barogroove.selectTheme",
            "surfaceId": "barogroove.themes",
            "callId": "smoke-1",
            "context": {},
            "args": {"themeId": "petrichor"},
            "dataModel": {"selectedTheme": "petrichor"},
        },
    ),

    # ---- forge ----------------------------------------------------------
    Case("GET", "/api/forge/demo", "length=6", params={"length": 6}, headers=USER_HDR, kind="offline"),
    Case(
        "POST",
        "/api/forge",
        "Brussels, theme=petrichor, length=6, sink=none, seed=7",
        body={
            "coordinates": BRUSSELS,
            "theme_id": "petrichor",
            "genre_id": "any",
            "length": 6,
            "sink": "none",
            "seed": 7,
            "user_id": "smoke-user",
        },
        headers=USER_HDR,
        capture=_capture_forge,
        kind="offline",
    ),
    Case(
        "POST",
        "/api/forge/explain",
        "the playlist just forged, echoed back",
        body_from=_explain_body,
        kind="offline",
    ),

    # ---- forge jobs (async/resumable variant of the same forge) ---------
    Case(
        "POST",
        "/api/forge/jobs",
        "same forge body, job_id=smoke-job-1 (idempotency key)",
        params={"job_id": "smoke-job-1"},
        body={
            "coordinates": BRUSSELS,
            "theme_id": "petrichor",
            "genre_id": "any",
            "length": 6,
            "sink": "none",
            "seed": 7,
        },
        headers=USER_HDR,
        expect=(200, 202),
        capture=lambda ctx, p: ctx.__setitem__("job_id", (p or {}).get("id") or (p or {}).get("jobId") or "smoke-job-1"),
        kind="offline",
    ),
    Case(
        "POST",
        "/api/forge/jobs",
        "the SAME job_id again -- must join, not forge twice",
        params={"job_id": "smoke-job-1"},
        body={
            "coordinates": BRUSSELS,
            "theme_id": "petrichor",
            "genre_id": "any",
            "length": 6,
            "sink": "none",
            "seed": 7,
        },
        headers=USER_HDR,
        expect=(200, 202),
        kind="offline",
        note="Idempotent retry: 200 means it handed back the in-flight run.",
    ),
    Case(
        "GET",
        "/api/forge/jobs",
        "limit=5",
        params={"limit": 5},
        headers=USER_HDR,
    ),
    Case(
        "GET",
        "/api/forge/jobs/{job_id}",
        "poll the job started above",
        path_params=_pp("job_id", "job_id", "smoke-job-1"),
        headers=USER_HDR,
        expect=(200, 404),
        note="404 is legitimate: the job registry is in-process only.",
    ),

    # ---- almanac --------------------------------------------------------
    # These all carry the same X-Barogroove-User the forge above used. That is
    # what a real client does -- one identity for the whole session -- and the
    # Almanac is user-scoped, so reading as a different caller than the one
    # that wrote would only ever prove that scoping works.
    Case("GET", "/api/almanac/history", "limit=5", params={"limit": 5}, headers=USER_HDR, kind="offline"),
    Case("GET", "/api/almanac/nudge", "no args", headers=USER_HDR, kind="offline"),
    Case("GET", "/api/almanac/retrospective", "no args", headers=USER_HDR, kind="offline"),
    Case("GET", "/api/almanac/scrobbles", "limit=5", params={"limit": 5}, headers=USER_HDR, kind="offline"),
    Case(
        "GET",
        "/api/almanac/scrobbles/analytics",
        "years 2020-2026, limit=5",
        params={"year_start": 2020, "year_end": 2026, "limit": 5},
        headers=USER_HDR,
        kind="offline",
    ),
    Case("GET", "/api/almanac/scrobbles/cache/stats", "no args"),
    Case(
        "GET",
        "/api/almanac/forges/{playlist_id}",
        "playlist_id from POST /api/forge, same user header",
        path_params=_pp("playlist_id", "playlist_id", "no-such-playlist"),
        headers=USER_HDR,
        kind="offline",
    ),
    Case(
        "GET",
        "/api/almanac/forges/{playlist_id}",
        "same id as a DIFFERENT caller -- must stay private",
        path_params=_pp("playlist_id", "playlist_id", "no-such-playlist"),
        expect=(404,),
        note="Per-user scoping: another caller must not be able to fetch this forge by id.",
    ),
    Case("GET", "/api/almanac/qna/status", "no args", kind="offline"),
    Case(
        "POST",
        "/api/almanac/qna/ask",
        '{"question": "which theme do I forge most?"}',
        body={"question": "which theme do I forge most?", "history": [], "preferred_chart_type": "bar"},
        headers=USER_HDR,
        kind="offline",
    ),
    Case(
        "POST",
        "/api/almanac/qna/stream",
        "same question, streaming variant",
        body={"question": "which theme do I forge most?", "history": []},
        headers=USER_HDR,
        kind="offline",
    ),
    Case(
        "POST",
        "/api/almanac/qna/graph-on-demand",
        "bar chart over two literal rows",
        body={
            "title": "Forges by theme",
            "subtitle": "smoke",
            "chart_type": "bar",
            "rows": [{"label": "petrichor", "value": 3}, {"label": "first_frost", "value": 1}],
            "label_field": "label",
            "value_field": "value",
        },
    ),
    Case(
        "POST",
        "/api/almanac/playlist-cohort-check",
        '{"input_text": "Petrichor, falling barometer"}',
        body={"input_text": "Petrichor, falling barometer", "playlist_title": "Smoke set"},
        headers=USER_HDR,
        kind="offline",
    ),
    Case(
        "POST",
        "/api/almanac/feedback",
        'signal="loved" on the first forged track',
        body_from=lambda ctx: {
            "playlist_id": ctx.get("playlist_id") or "smoke-playlist",
            "track_key": ctx.get("track_key") or "grouper::heavy water",
            "signal": "loved",
        },
        headers=USER_HDR,
        kind="offline",
    ),
    Case(
        "POST",
        "/api/almanac/scrobbles/sync",
        "lastfm_user=smokeuser (Last.fm disabled offline)",
        params={"lastfm_user": "smokeuser"},
        headers=USER_HDR,
        kind="offline",
    ),
    Case("POST", "/api/almanac/scrobbles/cache/clear", "no args"),

    # ---- advisor / dataviz ---------------------------------------------
    Case("GET", "/api/advisor/suggestions", "no args", kind="offline"),
    Case(
        "POST",
        "/api/advisor/live",
        '{"prompt": "forge me something for this sky", auto_forge: false}',
        body={
            "prompt": "forge me something for this sky",
            "current_theme_id": "petrichor",
            "current_genre_id": "any",
            "auto_forge": False,
            "session_id": "smoke-session",
            "user_id": "smoke-user",
        },
        kind="offline",
    ),
    Case("GET", "/api/dataviz/dashboard", "no args", kind="offline"),
    Case(
        "POST",
        "/api/dataviz/qna",
        '{"question": "what is my busiest listening hour?"}',
        body={"question": "what is my busiest listening hour?", "voice_mode": False, "user_id": "smoke-user"},
        kind="offline",
    ),
]


# The telemetry router is mounted twice, under /api/telemetry and under its
# newer /api/observability alias. Same handlers, so generate both sets rather
# than copy-pasting nine cases.

def _telemetry_cases(prefix: str) -> list[Case]:
    tag = prefix.rsplit("/", 1)[-1]
    return [
        Case("GET", f"{prefix}/summary", "user_id=smoke-user", params={"user_id": "smoke-user"}),
        Case(
            "GET",
            f"{prefix}/sessions",
            "limit=5",
            params={"limit": 5},
            capture=_capture_first_id("sessions", f"{tag}_session_id"),
        ),
        Case(
            "GET",
            f"{prefix}/sessions/{{session_id}}",
            "id from the sessions list (synthetic if empty)",
            path_params=_pp("session_id", f"{tag}_session_id", "smoke-missing-session"),
            expect=(200, 404),
        ),
        Case(
            "GET",
            f"{prefix}/conversations",
            "limit=5",
            params={"limit": 5},
            capture=_capture_first_id("conversations", f"{tag}_conversation_id"),
        ),
        Case(
            "GET",
            f"{prefix}/conversations/{{conversation_id}}",
            "id from the conversations list (synthetic if empty)",
            path_params=_pp("conversation_id", f"{tag}_conversation_id", "smoke-missing-conversation"),
            expect=(200, 404),
        ),
        Case(
            "GET",
            f"{prefix}/trajectories",
            "limit=5, offset=0",
            params={"limit": 5, "offset": 0},
            capture=_capture_first_id("trajectories", f"{tag}_trajectory_id"),
        ),
        Case(
            "GET",
            f"{prefix}/trajectories/{{trajectory_id}}",
            "id from the trajectories list (synthetic if empty)",
            path_params=_pp("trajectory_id", f"{tag}_trajectory_id", "smoke-missing-trajectory"),
            expect=(200, 404),
        ),
        Case("GET", f"{prefix}/memories", "limit=5", params={"limit": 5}),
        Case(
            "POST",
            f"{prefix}/memories",
            '{"content": "prefers slowcore on falling barometers"}',
            body={
                "user_id": "smoke-user",
                "content": "prefers slowcore on falling barometers",
                "category": "musical_preference",
            },
            expect=(200, 201),
            capture=_capture_memory,
        ),
        Case(
            "DELETE",
            f"{prefix}/memories/{{memory_id}}",
            "the memory just created",
            path_params=_pp("memory_id", "memory_id", "smoke-missing-memory"),
            expect=(200, 204, 404),
        ),
    ]


CASES += _telemetry_cases("/api/telemetry")
CASES += _telemetry_cases("/api/observability")


# ---- pairing ------------------------------------------------------------
# Nothing here can complete offline: there are no OAuth credentials and no
# network. What these cases assert is that each one says so in structured
# JSON rather than melting into a 500.

CASES += [
    Case("GET", "/api/pair/status", "X-Barogroove-User header only", headers=USER_HDR),
    Case(
        "POST",
        "/api/pair/spotify/start",
        "return_to=https://bg.netdev.be/",
        params={"return_to": "https://bg.netdev.be/"},
        headers=USER_HDR,
        expect=(200, 422),
        kind="oauth",
        note="422 = ConfigurationError: no Spotify client id offline.",
    ),
    Case(
        "POST",
        "/api/pair/lastfm/start",
        "return_to=https://bg.netdev.be/",
        params={"return_to": "https://bg.netdev.be/"},
        headers=USER_HDR,
        expect=(200, 422),
        kind="oauth",
        note="422 = ConfigurationError: no Last.fm API key offline.",
    ),
    Case(
        "POST",
        "/api/pair/lastfm/username",
        '{"username": "smokeuser"}',
        body={"username": "smokeuser"},
        headers=USER_HDR,
        expect=(200, 422),
        kind="oauth",
    ),
    Case(
        "POST",
        "/api/pair/spotify/manual-exchange",
        "pasted callback URL with code+state",
        body={"pasted": "https://bg.netdev.be/callback?code=smoke-code&state=smoke-state"},
        headers=USER_HDR,
        expect=(200, 400, 422),
        kind="oauth",
    ),
    Case(
        "GET",
        "/api/pair/spotify/callback",
        "code=smoke-code&state=smoke-state",
        params={"code": "smoke-code", "state": "smoke-state"},
        expect=(200, 400, 422),
        kind="oauth",
    ),
    Case(
        "GET",
        "/api/pair/lastfm/callback",
        "token=smoke-token&state=smoke-state",
        params={"token": "smoke-token", "state": "smoke-state"},
        expect=(200, 400, 422, 503),
        kind="oauth",
        note="503 lastfm_unavailable is the offline answer: no API secret to exchange the token with.",
    ),
    Case(
        "GET",
        "/api/pair/callback",
        "code=smoke-code&state=smoke-state (generic router)",
        params={"code": "smoke-code", "state": "smoke-state"},
        expect=(200, 400, 422),
        kind="oauth",
    ),
    Case(
        "GET",
        "/callback",
        "root alias of the generic OAuth callback",
        params={"code": "smoke-code", "state": "smoke-state"},
        expect=(200, 400, 422),
        kind="oauth",
    ),
    Case(
        "GET",
        "/auth/lastfm/callback",
        "legacy Last.fm redirect alias",
        params={"token": "smoke-token", "state": "smoke-state"},
        expect=(200, 400, 422),
        kind="oauth",
    ),
    Case(
        "GET",
        "/api/pair/{provider}/demo-authorize",
        "provider=spotify, state=smoke-state",
        path_params=lambda ctx: {"provider": "spotify"},
        params={"state": "smoke-state"},
        expect=(200, 400, 404, 422),
        kind="oauth",
    ),
    Case(
        "GET",
        "/api/pair/{provider}/demo-complete",
        "provider=spotify, state=smoke-state, account=smoke@example.com",
        path_params=lambda ctx: {"provider": "spotify"},
        params={"state": "smoke-state", "account": "smoke@example.com"},
        expect=(200, 400, 404, 422),
        kind="oauth",
    ),
    Case(
        "POST",
        "/api/pair/{provider}/configure",
        "provider=spotify, dummy client id/secret",
        path_params=lambda ctx: {"provider": "spotify"},
        body={"client_id": "smoke-client-id", "client_secret": "smoke-client-secret"},
        expect=(200, 400, 422),
        kind="oauth",
        note="No Secret Manager offline; must refuse politely.",
    ),
    Case(
        "POST",
        "/api/pair/{provider}/disconnect",
        "provider=spotify",
        path_params=lambda ctx: {"provider": "spotify"},
        headers=USER_HDR,
        expect=(200, 404, 422),
        kind="oauth",
    ),
]


# --------------------------------------------------------------------------
# Route discovery
# --------------------------------------------------------------------------


def discover_routes(app: Any) -> list[tuple[str, str]]:
    """Every (method, path-template) the app serves, prefixes applied.

    FastAPI >= 0.116 keeps included routers as ``_IncludedRouter`` wrappers in
    ``app.routes`` instead of flattening their routes, so a naive
    ``[r.path for r in app.routes]`` sees six routes out of seventy-nine.
    Recurse through ``original_router`` and re-apply ``include_context.prefix``.
    """

    def walk(routes: Iterable[Any], prefix: str = "") -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                ctx = getattr(route, "include_context", None)
                found += walk(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
                continue
            path = getattr(route, "path", None)
            if path is None:
                continue
            methods = getattr(route, "methods", None) or {"GET"}
            for method in methods:
                if method == "HEAD":
                    continue
                found.append((method, prefix + path))
        return found

    return sorted(set(walk(app.routes)))


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


@dataclass
class Result:
    method: str
    path: str
    sent: str
    status: int | None
    ok: bool
    kind: str
    detail: str = ""


def _one_line(text: str, limit: int = 110) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


def _is_ok(case: Case, status: int, payload: Any) -> bool:
    """A route passes when it answered with a status it is allowed to answer.

    Two extra rules on top of the declared ``expect`` set:

    * 500 is never a pass. If the app cannot do the thing, it must say so in a
      structured body, not leak a stack trace.
    * any other 5xx must additionally carry a JSON body -- "upstream is not
      available on this deployment" is a legitimate answer, an HTML error page
      from the framework is not.
    """

    if status in ALWAYS_FATAL:
        return False
    if status not in case.expect:
        return False
    if status >= 500 and not isinstance(payload, dict):
        return False
    return True


def _failure_detail(case: Case, status: int, payload: Any, raw: str) -> str:
    if status in ALWAYS_FATAL:
        return _one_line(f"{status} -- {raw}")
    if isinstance(payload, dict):
        for key in ("detail", "error", "message"):
            if key in payload:
                return _one_line(f"{status} {key}={payload[key]}")
    return _one_line(f"{status} {raw}")


def run(verbose: bool = False) -> list[Result]:
    pin_offline()
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    app = create_app()
    exposed = discover_routes(app)
    by_key: dict[tuple[str, str], list[Case]] = {}
    for case in CASES:
        by_key.setdefault(case.key, []).append(case)

    ctx: dict[str, Any] = {}
    results: list[Result] = []

    with TestClient(app) as client:
        for case in CASES:
            path = case.path
            if case.path_params:
                for name, value in case.path_params(ctx).items():
                    path = path.replace("{" + name + "}", str(value))
            body = case.body_from(ctx) if case.body_from else case.body
            kwargs: dict[str, Any] = {}
            if case.params:
                kwargs["params"] = case.params
            if body is not None:
                kwargs["json"] = body
            if case.headers:
                kwargs["headers"] = case.headers

            try:
                response = client.request(case.method, path, **kwargs)
            except Exception as exc:  # a handler that raises past the app
                results.append(
                    Result(
                        case.method,
                        case.path,
                        case.sent,
                        None,
                        False,
                        case.kind,
                        _one_line(f"raised {type(exc).__name__}: {exc}"),
                    )
                )
                continue

            raw = response.text or ""
            try:
                payload = response.json()
            except Exception:
                payload = None

            ok = _is_ok(case, response.status_code, payload)
            detail = "" if ok else _failure_detail(case, response.status_code, payload, raw[:400])
            if ok and case.note:
                detail = case.note
            if verbose and ok:
                detail = (detail + " | " if detail else "") + _one_line(raw[:200], 80)

            if ok and case.capture:
                try:
                    case.capture(ctx, payload)
                except Exception:  # capture must never sink the smoke pass
                    pass

            results.append(Result(case.method, case.path, case.sent, response.status_code, ok, case.kind, detail))

    covered = set(by_key)
    for method, path in exposed:
        if (method, path) not in covered:
            results.append(
                Result(method, path, "-- no case --", None, False, "gap", "route has no smoke case; add one")
            )

    stale = covered - set(exposed)
    for method, path in sorted(stale):
        results.append(Result(method, path, "-- stale case --", None, False, "gap", "case targets a route that no longer exists"))

    return results


def render_table(results: list[Result]) -> str:
    head = ("METHOD", "PATH", "SENT", "STATUS", "RESULT", "NOTE")
    rows = [
        (
            r.method,
            r.path,
            r.sent,
            "-" if r.status is None else str(r.status),
            "PASS" if r.ok else "FAIL",
            r.detail,
        )
        for r in results
    ]
    widths = [max(len(h), *(len(row[i]) for row in rows)) if rows else len(h) for i, h in enumerate(head)]
    widths[2] = min(widths[2], 52)
    widths[5] = min(widths[5], 70)

    def fmt(row: tuple[str, ...]) -> str:
        cells = []
        for i, cell in enumerate(row):
            text = cell if len(cell) <= widths[i] else cell[: widths[i] - 1] + "\u2026"
            cells.append(text.ljust(widths[i]))
        return "  ".join(cells).rstrip()

    lines = [fmt(head), fmt(tuple("-" * w for w in widths))]
    lines += [fmt(r) for r in rows]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the table")
    parser.add_argument("--verbose", action="store_true", help="append a response snippet to passing rows")
    parser.add_argument("--only-failures", action="store_true", help="print only the rows that failed")
    args = parser.parse_args(argv)

    results = run(verbose=args.verbose)
    failures = [r for r in results if not r.ok]

    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        shown = failures if args.only_failures else results
        print(render_table(shown))
        print()
        by_kind: dict[str, int] = {}
        for r in results:
            by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
        print(
            f"{len(results)} checks | {len(results) - len(failures)} pass | {len(failures)} fail "
            f"| kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
        )
        if failures:
            print("\nFAILURES")
            for r in failures:
                print(f"  {r.method:6} {r.path:52} {r.status or '-'}  {r.detail}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
