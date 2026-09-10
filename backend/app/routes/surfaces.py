"""HTTP binding for the A2UI surfaces.

A2UI does not mandate a transport -- there are bindings for HTTP
request/response, streaming, A2A and MCP. BAROGROOVE ships two: MCP (owned by
another module) and this plain-HTTP router, so the Flutter *web* client can
fetch a surface stream with a single GET and no MCP session.

Both bindings call the SAME builders in :mod:`app.a2ui.surfaces`. This file
contains no UI: it resolves services, calls a builder, and serialises. If you
find yourself constructing a component here, stop -- it belongs in surfaces.py.

Every response is ``application/a2ui+json``, the MIME type the spec standardises
for A2UI payloads, so an off-the-shelf renderer can consume it unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..a2ui.catalog import (
    CATALOG,
    CATALOG_ID,
    FN_EXPLAIN_DIMENSION,
    FN_FORGE,
    FN_OPEN_ALMANAC_ENTRY,
    FN_OPEN_TRACK,
    FN_REFRESH_SKY,
    FN_RETRY,
    FN_SELECT_GENRE,
    FN_SELECT_THEME,
    FN_SET_CORRIDOR_WIDTH,
    FN_TRACK_FEEDBACK,
    SKY_DIM_LABELS,
    catalog_json,
    validate_action,
)
from ..a2ui.palette import THEME_IDS, THEME_INTENT, THEME_PALETTES
from ..a2ui.protocol import A2UI_MIME_TYPE, A2UIProtocolError
from ..a2ui.surfaces import (
    agent_function_response,
    build_error_surface,
    build_sky_surface,
    build_themes_surface,
    patch_selection,
    patch_track_feedback,
    single_message,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/surfaces", tags=["a2ui"])


def _a2ui(messages: list[dict[str, Any]], *, single: bool = False) -> JSONResponse:
    payload = single_message(messages) if single else messages
    return JSONResponse(content=payload, media_type=A2UI_MIME_TYPE)


# --------------------------------------------------------------------------- #
# Defensive service / domain resolution
# --------------------------------------------------------------------------- #
#
# app.sonic.themes and app.container belong to other workers. This router must
# load and serve even before those land, because the Flutter worker needs
# /api/surfaces/catalog on day one. So: import inside the handler, catch
# ImportError, and fall back to the palette-derived themes below.


def _fallback_themes() -> list[Any]:
    """Themes derived from the palette when ``app.sonic.themes`` is unavailable.

    Same eight ids, same tints -- only the sonic bias is missing, and the themes
    surface never reads the bias.
    """
    from ..contracts import Theme

    return [
        Theme(
            id=theme_id,
            name=theme_id.replace("_", " ").title(),
            tagline=THEME_INTENT.get(theme_id, ""),
            description=THEME_INTENT.get(theme_id, ""),
            palette=dict(THEME_PALETTES[theme_id]),
        )
        for theme_id in THEME_IDS
    ]


def _fallback_corridors() -> list[Any]:
    """A minimal, honest corridor set so the second axis is never empty."""
    from ..contracts import GenreCorridor

    seeds: list[tuple[str, str, str, list[str]]] = [
        ("krautrock", "Krautrock", "Motorik pulse, patient repetition.",
         ["krautrock", "motorik", "kosmische"]),
        ("ambient", "Ambient", "Space before notes.", ["ambient", "drone", "field recording"]),
        ("dub", "Dub", "Bass and the room it echoes in.", ["dub", "reggae", "dub techno"]),
        ("post_punk", "Post-punk", "Tight, cold, wiry.", ["post-punk", "coldwave", "no wave"]),
        ("modern_classical", "Modern classical", "Strings and restraint.",
         ["modern classical", "minimalism", "neoclassical"]),
        ("jazz", "Jazz", "Conversation, not consensus.", ["jazz", "spiritual jazz", "modal"]),
        ("techno", "Techno", "Machines keeping time.", ["techno", "minimal techno", "electro"]),
        ("folk", "Folk", "One voice, weather-worn.", ["folk", "americana", "singer-songwriter"]),
    ]
    return [
        GenreCorridor(id=cid, name=name, description=desc, tags=tags, width=0.5)
        for cid, name, desc, tags in seeds
    ]


def _load_themes() -> tuple[list[Any], list[Any], bool]:
    """(themes, corridors, degraded).  Never raises."""
    try:
        from ..sonic import themes as sonic_themes  # type: ignore[attr-defined]
    except Exception as exc:  # ImportError, or a half-built module
        log.warning("app.sonic.themes unavailable (%s); using palette fallback", exc)
        return _fallback_themes(), _fallback_corridors(), True

    themes = (
        getattr(sonic_themes, "THEMES", None)
        or getattr(sonic_themes, "ALL_THEMES", None)
        or _fallback_themes()
    )
    corridors = (
        getattr(sonic_themes, "CORRIDORS", None)
        or getattr(sonic_themes, "GENRE_CORRIDORS", None)
        or _fallback_corridors()
    )
    if isinstance(themes, dict):
        themes = list(themes.values())
    if isinstance(corridors, dict):
        corridors = list(corridors.values())
    return list(themes), list(corridors), False


async def _read_sky(lat: float, lon: float) -> Any:
    """Resolve the weather service via the container and read the sky.

    The weather service's method name is owned by another worker, so we probe a
    short list rather than hard-coding one and breaking the router if it differs.
    """
    from ..container import get_container

    weather = get_container().weather()
    for name in ("read", "sky", "read_sky", "current", "fetch", "get"):
        method = getattr(weather, name, None)
        if method is None:
            continue
        result = method(lat, lon)
        if hasattr(result, "__await__"):
            result = await result
        return result
    raise RuntimeError(
        "weather service exposes none of read/sky/read_sky/current/fetch/get"
    )


# --------------------------------------------------------------------------- #
# GET /api/surfaces/catalog
# --------------------------------------------------------------------------- #


@router.get(
    "/catalog",
    summary="The BAROGROOVE A2UI component catalog",
    response_description="A2UI catalog document (JSON Schema style).",
)
def get_catalog() -> JSONResponse:
    """The catalog the Flutter renderer resolves components against.

    Identical to ``frontend/a2ui/catalog.json``; the test suite asserts it.
    """
    return JSONResponse(content=CATALOG, media_type="application/json")


@router.get("/catalog.json", include_in_schema=False)
def get_catalog_file() -> JSONResponse:
    """Byte-for-byte the generated catalog file, for renderers that want the file."""
    import json

    return JSONResponse(content=json.loads(catalog_json()), media_type="application/json")


# --------------------------------------------------------------------------- #
# GET /api/surfaces/sky
# --------------------------------------------------------------------------- #


@router.get("/sky", summary="Sky surface stream")
async def get_sky_surface(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    single: bool = Query(
        False,
        description="Fold the stream into one createSurface (A2UI v1.0 "
        "single-message UI instantiation).",
    ),
) -> JSONResponse:
    """Read the sky and return the SkyDial surface stream."""
    try:
        sky = await _read_sky(lat, lon)
    except Exception as exc:
        log.exception("sky read failed for %s,%s", lat, lon)
        return _a2ui(
            build_error_surface(
                "We could not read your sky just now.",
                detail=f"{type(exc).__name__}: {exc}",
            ),
            single=single,
        )
    return _a2ui(build_sky_surface(sky), single=single)


# --------------------------------------------------------------------------- #
# GET /api/surfaces/themes
# --------------------------------------------------------------------------- #


@router.get("/themes", summary="Themes x genre corridors surface stream")
def get_themes_surface(
    theme: str | None = Query(None, description="Pre-selected theme id."),
    genre: str | None = Query(None, description="Pre-selected genre corridor id."),
    single: bool = Query(False),
) -> JSONResponse:
    """The two orthogonal axes. Loads even if the sonic layer is not deployed yet."""
    themes, corridors, degraded = _load_themes()
    if degraded:
        log.info("serving themes surface from the palette fallback")
    return _a2ui(
        build_themes_surface(
            themes, corridors, selected_theme=theme, selected_genre=genre
        ),
        single=single,
    )


# --------------------------------------------------------------------------- #
# POST /api/surfaces/action  -- the client -> agent round trip
# --------------------------------------------------------------------------- #


class ActionRequest(BaseModel):
    """The A2UI ``actionResponse`` / ``callAgentFunction`` payload over plain HTTP.

    Action ids and catalog function names are the same strings, so a renderer can
    post whatever the component declared without a translation table. ``context``
    and ``args`` are accepted interchangeably because the two A2UI shapes name the
    argument bag differently.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    action: str = Field(description="Action id == catalog function name.")
    surface_id: str | None = Field(default=None, alias="surfaceId")
    call_id: str | None = Field(default=None, alias="callId")
    context: dict[str, Any] = Field(default_factory=dict)
    args: dict[str, Any] = Field(default_factory=dict)
    data_model: dict[str, Any] | None = Field(default=None, alias="dataModel")

    def payload(self) -> dict[str, Any]:
        merged = {**self.context, **self.args}
        merged.pop("surfaceId", None)
        return merged


@router.post("/action", summary="A2UI action / callAgentFunction endpoint")
def post_action(request: ActionRequest = Body(...)) -> JSONResponse:
    """Where the chips talk back.

    Validates the payload against the signature declared in the catalog, then
    answers with follow-up A2UI messages. Selection changes are answered with
    ``updateDataModel`` alone -- no components are resent -- which is exactly the
    dividend of keeping data out of the component tree.
    """
    try:
        payload = validate_action(request.action, request.payload())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2UIProtocolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    surface_id = request.surface_id
    messages: list[dict[str, Any]] = []
    result: dict[str, Any] = {"ok": True, "action": request.action}

    if request.action == FN_SELECT_THEME and surface_id:
        messages += patch_selection(surface_id, theme_id=payload["themeId"])
        result["themeId"] = payload["themeId"]

    elif request.action == FN_SELECT_GENRE and surface_id:
        messages += patch_selection(surface_id, genre_id=payload["genreId"])
        result["genreId"] = payload["genreId"]

    elif request.action == FN_SET_CORRIDOR_WIDTH and surface_id:
        messages += patch_selection(
            surface_id, genre_id=payload["genreId"], width=float(payload["width"])
        )
        result["width"] = float(payload["width"])

    elif request.action == FN_TRACK_FEEDBACK and surface_id:
        position = int(payload.get("position") or 1)
        messages += patch_track_feedback(
            surface_id, index=max(position - 1, 0), verdict=payload["verdict"]
        )
        result |= {"trackKey": payload["trackKey"], "verdict": payload["verdict"]}

    elif request.action == FN_EXPLAIN_DIMENSION:
        dimension = payload["dimension"]
        result |= {
            "dimension": dimension,
            "label": SKY_DIM_LABELS.get(dimension, dimension),
        }

    elif request.action in {FN_FORGE, FN_OPEN_TRACK, FN_OPEN_ALMANAC_ENTRY, FN_RETRY}:
        # These need services other workers own (the forge pipeline, the sinks).
        # Acknowledge the typed call so the renderer's promise resolves; the MCP
        # layer performs the work and pushes the resulting surface separately.
        result |= {"accepted": True, "args": payload}

    elif request.action == FN_REFRESH_SKY:
        result |= {"accepted": True, "lat": payload["lat"], "lon": payload["lon"]}

    if request.call_id and surface_id:
        messages.append(
            agent_function_response(surface_id, request.call_id, result=result)
        )

    if not messages:
        # Nothing to re-render, but the caller still deserves a typed answer.
        return JSONResponse(content={"result": result}, media_type="application/json")
    return _a2ui(messages)


@router.get("/health", include_in_schema=False)
def health() -> dict[str, object]:
    themes, corridors, degraded = _load_themes()
    return {
        "catalogId": CATALOG_ID,
        "components": len(CATALOG["components"]),
        "functions": len(CATALOG["functions"]),
        "themes": len(themes),
        "corridors": len(corridors),
        "sonicThemesModule": "fallback" if degraded else "live",
    }


SurfaceKind = Literal["sky", "themes", "playlist", "rationale", "almanac", "error"]
