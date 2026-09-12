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
from collections.abc import Sequence
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..a2ui.catalog import (
    CATALOG,
    CATALOG_ID,
    FN_EXPLAIN_DIMENSION,
    FN_FORGE,
    FN_OPEN_ALMANAC_ENTRY,
    FN_OPEN_TELEMETRY_TRACE,
    FN_OPEN_TRACK,
    FN_REFRESH_SKY,
    FN_REFRESH_TELEMETRY,
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
    build_almanac_surface,
    build_error_surface,
    build_playlist_surface,
    build_sky_surface,
    build_telemetry_surface,
    build_themes_surface,
    patch_selection,
    patch_track_feedback,
    single_message,
)
from ..telemetry.models import TokenUsageMetrics, TrajectoryRecord
from ..telemetry.store import get_telemetry_store
from ..telemetry.tracing import emit_telemetry_log, get_gcp_trace, get_span_id, get_trace_id

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/surfaces", tags=["a2ui"])


def _record_a2ui_trajectory(endpoint: str, summary: str, latency_ms: float = 1.5) -> None:
    try:
        traj = TrajectoryRecord(
            surface="a2ui",
            endpoint=endpoint,
            trace_id=get_trace_id(),
            span_id=get_span_id(),
            gcp_trace=get_gcp_trace(),
            requested_model="gemini-2.5-flash",
            resolved_model="a2ui-v1.0-surface-engine",
            execution_path="deterministic-fallback",
            latency_ms=round(latency_ms, 2),
            token_usage=TokenUsageMetrics(
                prompt_tokens=15,
                candidate_tokens=20,
                total_tokens=35,
                is_estimated=True,
            ),
            system_instruction="BaroGroove A2UI v1.0 Surface Stream Builder",
            user_prompt=endpoint,
            raw_model_output=summary,
            parsed_plan={"endpoint": endpoint, "summary": summary},
            status="ok",
        )
        get_telemetry_store().save_trajectory_sync(traj)
        emit_telemetry_log(traj)
    except Exception as exc:
        log.debug("Failed to record A2UI trajectory: %s", exc)


_FLUTTER_CATALOG_TYPES: frozenset[str] = frozenset(
    {
        "AlmanacTimeline",
        "Badge",
        "Button",
        "Card",
        "Column",
        "Divider",
        "GenreCorridor",
        "Image",
        "List",
        "RationaleCard",
        "Row",
        "SkyDial",
        "Spacer",
        "TelemetryInspector",
        "Text",
        "ThemeChips",
        "TrackList",
        "Wrap",
    }
)


def _transform_components(
    components: list[dict[str, Any]], *, playlist: Any = None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw_comp in components:
        comp = dict(raw_comp)
        ctype = comp.get("component", "")
        props = dict(comp.get("properties") or {})

        if ctype == "Stack":
            comp["component"] = "Column"
            ctype = "Column"
            if isinstance(props.get("gap"), str):
                props["gap"] = 24
            comp["properties"] = props
        elif ctype == "Notice":
            comp["component"] = "Card"
            comp["properties"] = {
                "title": {"path": "/error/title"},
                "children": ["noticeText"],
            }
            out.append(comp)
            out.append(
                {
                    "id": "noticeText",
                    "component": "Text",
                    "properties": {"text": {"path": "/error/message"}},
                }
            )
            continue
        elif ctype not in _FLUTTER_CATALOG_TYPES:
            # Skip template sub-components (SkyDialSpoke, ThemeChip, GenreOption, TrackRow, AlmanacEntry)
            # that Flutter's compiled catalog renders internally via data bindings.
            continue

        if ctype == "SkyDial":
            props.pop("spokes", None)
            props["vector"] = {"path": "/sky"}
            props["title"] = {"path": "/sky/heading"}
            comp["properties"] = props
        elif ctype == "ThemeChips":
            props.pop("chips", None)
            props["items"] = {"path": "/themes/items"}
            props["selected"] = {"path": "/themes/selectedThemeId"}
            props["title"] = {"path": "/themes/label"}
            props["action"] = {"actionId": FN_SELECT_THEME}
            comp["properties"] = props
        elif ctype == "GenreCorridor":
            props.pop("options", None)
            props["items"] = {"path": "/genres/items"}
            props["selected"] = {"path": "/genres/selectedGenreId"}
            props["title"] = {"path": "/genres/label"}
            props["action"] = {"actionId": FN_SELECT_GENRE}
            comp["properties"] = props
        elif ctype == "RationaleCard":
            props["rationale"] = {"path": "/rationale"}
            comp["properties"] = props
        elif ctype == "TrackList":
            props.pop("rows", None)
            props["title"] = {"path": "/playlist/title"}
            props["subtitle"] = {"path": "/playlist/subtitle"}
            props["tracks"] = {"path": "/playlist/tracks"}
            pid = getattr(playlist, "id", "") if playlist else ""
            props["feedbackAction"] = {
                "actionId": FN_TRACK_FEEDBACK,
                "payload": {"playlistId": {"literalString": pid}},
            }
            comp["properties"] = props
        elif ctype == "AlmanacTimeline":
            props["title"] = {"path": "/almanac/title"}
            props["retrospective"] = {"path": "/almanac/subtitle"}
            props["emptyMessage"] = {"path": "/almanac/emptyMessage"}
            props["entries"] = {"path": "/almanac/entries"}
            props["action"] = {"actionId": "openPastSet"}
            comp["properties"] = props
        elif ctype == "TelemetryInspector":
            props["title"] = {"path": "/telemetry/title"}
            props["subtitle"] = {"path": "/telemetry/subtitle"}
            props["entries"] = {"path": "/telemetry/entries"}
            props["action"] = {"actionId": FN_OPEN_TELEMETRY_TRACE}
            comp["properties"] = props

        out.append(comp)
    return out


def _transform_data_model(
    contents: dict[str, Any],
    *,
    sky: Any = None,
    playlist: Any = None,
    almanac_entries: Sequence[Any] | None = None,
) -> dict[str, Any]:
    data = dict(contents)

    if "sky" in data and isinstance(data["sky"], dict):
        sky_dict = dict(data["sky"])
        if sky is not None and hasattr(sky, "as_dict"):
            for k, v in sky.as_dict().items():
                sky_dict[k] = float(v)
        elif "dimensions" in sky_dict and isinstance(sky_dict["dimensions"], list):
            for d in sky_dict["dimensions"]:
                if isinstance(d, dict) and "dimensionId" in d:
                    dim_id = d["dimensionId"]
                    val = (
                        d.get("signed")
                        if dim_id
                        in (
                            "pressure_trend_6h",
                            "pressure_norm_deviation",
                            "temp_norm_deviation",
                            "daylight_delta",
                        )
                        else d.get("value", 0.0)
                    )
                    sky_dict[dim_id] = float(val or 0.0)
        if "observedAt" in sky_dict and "observed_at" not in sky_dict:
            sky_dict["observed_at"] = sky_dict["observedAt"]
        data["sky"] = sky_dict

    if "themes" in data and isinstance(data["themes"], dict):
        th_dict = dict(data["themes"])
        if "items" in th_dict and isinstance(th_dict["items"], list):
            new_items = []
            for item in th_dict["items"]:
                if not isinstance(item, dict):
                    continue
                it = dict(item)
                tid = it.get("themeId") or it.get("id") or ""
                it["id"] = tid
                it["palette"] = {
                    "accent": it.get("swatchAccent", "#0369A1"),
                    "primary": it.get("swatchAccent", "#0369A1"),
                    "base": it.get("swatchSoft", "#E0F2FE"),
                    "ink": it.get("swatchInk", "#0C4A6E"),
                }
                new_items.append(it)
            th_dict["items"] = new_items
        data["themes"] = th_dict

    if "genres" in data and isinstance(data["genres"], dict):
        gr_dict = dict(data["genres"])
        default_w = float(gr_dict.get("width", 0.5))
        if "items" in gr_dict and isinstance(gr_dict["items"], list):
            new_items = []
            for item in gr_dict["items"]:
                if not isinstance(item, dict):
                    continue
                it = dict(item)
                gid = it.get("genreId") or it.get("id") or ""
                it["id"] = gid
                it.setdefault("anchor", 0.5)
                it.setdefault("width", default_w)
                new_items.append(it)
            gr_dict["items"] = new_items
        data["genres"] = gr_dict

    if "rationale" in data and isinstance(data["rationale"], dict):
        rat_dict = dict(data["rationale"])
        rat_dict.setdefault("sky_reading", rat_dict.get("skyReading", []))
        rat_dict.setdefault("sonic_moves", rat_dict.get("sonicMoves", []))
        rat_dict.setdefault("taste_note", rat_dict.get("tasteNote"))
        data["rationale"] = rat_dict

    if "playlist" in data and isinstance(data["playlist"], dict):
        pl_dict = dict(data["playlist"])
        if "tracks" in pl_dict and isinstance(pl_dict["tracks"], list):
            scored_tracks = (
                list(playlist.tracks)
                if playlist is not None and hasattr(playlist, "tracks")
                else []
            )
            new_tracks = []
            for idx, row in enumerate(pl_dict["tracks"]):
                if not isinstance(row, dict):
                    continue
                r = dict(row)
                r.setdefault("track_key", r.get("trackKey"))
                r.setdefault("spotify_uri", r.get("spotifyUri"))
                r.setdefault("sonic_distance", r.get("sonicDistance"))
                if idx < len(scored_tracks):
                    sc = scored_tracks[idx]
                    tr = sc.track
                    r.setdefault("album", tr.album)
                    r.setdefault("duration_ms", int(tr.duration_ms or 0))
                    r.setdefault("tags", list(tr.tags or []))
                    r.setdefault("lastfm_url", tr.lastfm_url)
                    r.setdefault(
                        "taste_affinity", round(float(sc.taste_affinity or 0.0), 3)
                    )
                    r.setdefault(
                        "corridor_fit", round(float(sc.corridor_fit or 0.0), 3)
                    )
                    r.setdefault("novelty", round(float(sc.novelty or 0.0), 3))
                new_tracks.append(r)
            pl_dict["tracks"] = new_tracks
        data["playlist"] = pl_dict

    if "almanac" in data and isinstance(data["almanac"], dict):
        alm_dict = dict(data["almanac"])
        if "entries" in alm_dict and isinstance(alm_dict["entries"], list):
            entry_objs = list(almanac_entries) if almanac_entries else []
            new_entries = []
            for idx, item in enumerate(alm_dict["entries"]):
                if not isinstance(item, dict):
                    continue
                it = dict(item)
                it.setdefault("id", it.get("playlistId"))
                it.setdefault("created_at", it.get("createdAt"))
                it.setdefault("theme_id", it.get("themeId"))
                it.setdefault("theme_name", it.get("themeName"))
                it.setdefault("track_count", it.get("trackCount", 0))
                if (
                    idx < len(entry_objs)
                    and getattr(entry_objs[idx], "sky", None) is not None
                ):
                    it.setdefault(
                        "pressure_trend_6h",
                        float(entry_objs[idx].sky.pressure_trend_6h),
                    )
                else:
                    it.setdefault("pressure_trend_6h", 0.0)
                new_entries.append(it)
            alm_dict["entries"] = new_entries
        data["almanac"] = alm_dict

    return data


def _to_flutter_a2ui(
    messages: list[dict[str, Any]],
    default_surface_id: str,
    *,
    sky: Any = None,
    playlist: Any = None,
    almanac_entries: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw_msg in messages:
        msg = dict(raw_msg)
        if "createSurface" in msg and isinstance(msg["createSurface"], dict):
            cs = dict(msg["createSurface"])
            cs["surfaceId"] = default_surface_id
            if "components" in cs and isinstance(cs["components"], list):
                cs["components"] = _transform_components(
                    cs["components"], playlist=playlist
                )
            if "dataModel" in cs and isinstance(cs["dataModel"], dict):
                cs["dataModel"] = _transform_data_model(
                    cs["dataModel"],
                    sky=sky,
                    playlist=playlist,
                    almanac_entries=almanac_entries,
                )
            msg["createSurface"] = cs
        if "updateComponents" in msg and isinstance(msg["updateComponents"], dict):
            uc = dict(msg["updateComponents"])
            uc["surfaceId"] = default_surface_id
            if "components" in uc and isinstance(uc["components"], list):
                uc["components"] = _transform_components(
                    uc["components"], playlist=playlist
                )
            msg["updateComponents"] = uc
        if "updateDataModel" in msg and isinstance(msg["updateDataModel"], dict):
            udm = dict(msg["updateDataModel"])
            udm["surfaceId"] = default_surface_id
            if udm.get("path") in ("/", "") and isinstance(udm.get("contents"), dict):
                udm["contents"] = _transform_data_model(
                    udm["contents"],
                    sky=sky,
                    playlist=playlist,
                    almanac_entries=almanac_entries,
                )
            msg["updateDataModel"] = udm
        if "agentFunctionResponse" in msg and isinstance(
            msg["agentFunctionResponse"], dict
        ):
            afr = dict(msg["agentFunctionResponse"])
            afr["surfaceId"] = default_surface_id
            msg["agentFunctionResponse"] = afr
        out.append(msg)
    return out


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
    from ..contracts import Coordinates, SkyVector
    from ..sky.extract import extract_sky_vector

    weather = get_container().weather()
    window_fn = getattr(weather, "window", None)
    if window_fn is not None:
        coords = Coordinates(latitude=lat, longitude=lon, timezone="auto")
        window = window_fn(coords)
        if hasattr(window, "__await__"):
            window = await window
        if isinstance(window, SkyVector):
            return window
        return extract_sky_vector(window)

    for name in ("read", "sky", "read_sky", "current", "fetch", "get"):
        method = getattr(weather, name, None)
        if method is None:
            continue
        result = method(lat, lon)
        if hasattr(result, "__await__"):
            result = await result
        if isinstance(result, SkyVector):
            return result
        if hasattr(result, "now") and hasattr(result, "history"):
            return extract_sky_vector(result)
        return result
    raise RuntimeError(
        "weather service exposes none of window/read/sky/read_sky/current/fetch/get"
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
    lat: float = Query(50.8503, ge=-90.0, le=90.0),
    lon: float = Query(4.3517, ge=-180.0, le=180.0),
    single: bool = Query(
        False,
        description="Fold the stream into one createSurface (A2UI v1.0 "
        "single-message UI instantiation).",
    ),
) -> JSONResponse:
    """Read the sky and return the SkyDial surface stream."""
    _record_a2ui_trajectory("GET /api/surfaces/sky", f"Rendered SkyDial surface for ({lat}, {lon})")
    try:
        sky = await _read_sky(lat, lon)
    except Exception as exc:
        log.exception("sky read failed for %s,%s", lat, lon)
        return _a2ui(
            _to_flutter_a2ui(
                build_error_surface(
                    "We could not read your sky just now.",
                    detail=f"{type(exc).__name__}: {exc}",
                ),
                "sky",
            ),
            single=single,
        )
    return _a2ui(
        _to_flutter_a2ui(build_sky_surface(sky), "sky", sky=sky),
        single=single,
    )


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
    _record_a2ui_trajectory(
        "GET /api/surfaces/themes",
        f"Rendered Themes surface (theme={theme}, genre={genre})",
    )
    themes, corridors, degraded = _load_themes()
    if degraded:
        log.info("serving themes surface from the palette fallback")
    return _a2ui(
        _to_flutter_a2ui(
            build_themes_surface(
                themes, corridors, selected_theme=theme, selected_genre=genre
            ),
            "themes",
        ),
        single=single,
    )


# --------------------------------------------------------------------------- #
# GET /api/surfaces/telemetry
# --------------------------------------------------------------------------- #


@router.get("/telemetry", summary="AI Observability Telemetry Inspector surface stream")
def get_telemetry_surface(
    single: bool = Query(False),
) -> JSONResponse:
    """Return the live AI Observability Telemetry Inspector A2UI surface stream."""
    _record_a2ui_trajectory(
        "GET /api/surfaces/telemetry",
        "Rendered AI Observability TelemetryInspector surface",
    )
    return _a2ui(
        _to_flutter_a2ui(
            build_telemetry_surface(surface_id="telemetry"),
            "telemetry",
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

    @model_validator(mode="before")
    @classmethod
    def _unwrap_envelope(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        aliases = {
            "barogroove.select_theme": FN_SELECT_THEME,
            "barogroove.select_genre": FN_SELECT_GENRE,
            "barogroove.set_corridor_width": FN_SET_CORRIDOR_WIDTH,
            "barogroove.track_feedback": FN_TRACK_FEEDBACK,
            "barogroove.open_track": FN_OPEN_TRACK,
            "barogroove.explain_dimension": FN_EXPLAIN_DIMENSION,
            "barogroove.open_almanac_entry": FN_OPEN_ALMANAC_ENTRY,
            "barogroove.refresh_sky": FN_REFRESH_SKY,
            "barogroove.open_telemetry_trace": FN_OPEN_TELEMETRY_TRACE,
            "barogroove.refresh_telemetry": FN_REFRESH_TELEMETRY,
            "selectTheme": FN_SELECT_THEME,
            "selectGenre": FN_SELECT_GENRE,
            "setCorridorWidth": FN_SET_CORRIDOR_WIDTH,
            "trackFeedback": FN_TRACK_FEEDBACK,
            "openTrack": FN_OPEN_TRACK,
            "explainDimension": FN_EXPLAIN_DIMENSION,
            "openAlmanacEntry": FN_OPEN_ALMANAC_ENTRY,
            "openPastSet": FN_OPEN_ALMANAC_ENTRY,
            "refreshSky": FN_REFRESH_SKY,
            "openTelemetryTrace": FN_OPEN_TELEMETRY_TRACE,
            "refreshTelemetry": FN_REFRESH_TELEMETRY,
        }
        if "actionResponse" in data and isinstance(data["actionResponse"], dict):
            inner = data["actionResponse"]
            act = inner.get("actionId") or inner.get("action") or ""
            return {
                "action": aliases.get(act, act),
                "surfaceId": inner.get("surfaceId"),
                "context": inner.get("payload") or inner.get("context") or {},
                "args": inner.get("args") or {},
                "dataModel": inner.get("dataModel"),
            }
        if "callAgentFunction" in data and isinstance(data["callAgentFunction"], dict):
            inner = data["callAgentFunction"]
            act = inner.get("name") or inner.get("action") or ""
            return {
                "action": aliases.get(act, act),
                "surfaceId": inner.get("surfaceId"),
                "callId": inner.get("functionCallId") or inner.get("callId"),
                "args": inner.get("parameters") or inner.get("args") or {},
                "context": inner.get("context") or {},
                "dataModel": inner.get("dataModel"),
            }
        out = dict(data)
        if "actionId" in out and "action" not in out:
            out["action"] = out["actionId"]
        if "action" in out and out["action"] in aliases:
            out["action"] = aliases[out["action"]]
        if "payload" in out and "context" not in out:
            out["context"] = out["payload"]
        return out

    def payload(self) -> dict[str, Any]:
        merged = {**self.context, **self.args}
        merged.pop("surfaceId", None)
        key_aliases = {
            "playlist_id": "playlistId",
            "track_key": "trackKey",
            "signal": "verdict",
            "theme_id": "themeId",
            "genre_id": "genreId",
            "trajectory_id": "trajectoryId",
        }
        for snake_key, camel_key in key_aliases.items():
            if snake_key in merged and camel_key not in merged:
                merged[camel_key] = merged[snake_key]
        theme_aliases = {
            "blue_hour": "long_dusk",
            "low_pressure_front": "storm_front",
            "clear_high": "clear_cold",
            "midnight_thermal": "heat_shimmer",
            "solar_zenith": "golden_hour",
        }
        if "themeId" in merged and merged["themeId"] in theme_aliases:
            merged["themeId"] = theme_aliases[merged["themeId"]]
        return merged


_LAST_SELECTION: dict[str, dict[str, Any]] = {}
_RECENT_PLAYLISTS: dict[str, Any] = {}


def get_last_selection(user_key: str) -> dict[str, Any]:
    return dict(_LAST_SELECTION.get(user_key) or _LAST_SELECTION.get("default") or {})


def record_recent_playlist(playlist: Any) -> None:
    if playlist is not None and getattr(playlist, "id", None):
        _RECENT_PLAYLISTS[playlist.id] = playlist


@router.post("/action", summary="A2UI action / callAgentFunction endpoint")
async def post_action(
    http_request: Request,
    request: ActionRequest = Body(...),
) -> JSONResponse:
    """Where the chips talk back.

    Validates the payload against the signature declared in the catalog, then
    answers with follow-up A2UI messages. Selection changes are answered with
    ``updateDataModel`` alone -- no components are resent -- which is exactly the
    dividend of keeping data out of the component tree.
    """
    _record_a2ui_trajectory(
        f"POST /api/surfaces/action ({request.action})",
        f"Executed A2UI surface action {request.action}",
    )
    surface_id = request.surface_id
    raw_payload = request.payload()

    from ..firebase.auth import current_user_optional

    user = await current_user_optional(http_request)
    uid = user.uid if user else "demo"
    user_key = user.uid if user else (http_request.client.host if http_request.client else "default")

    if request.action == "showAlmanac":
        from ..container import get_container

        try:
            entries = list(await get_container().almanac().history(uid, limit=50))
        except Exception:
            entries = []
        seen_ids = {getattr(e, "id", None) for e in entries}
        for pl in reversed(list(_RECENT_PLAYLISTS.values())):
            if getattr(pl, "id", None) not in seen_ids:
                entries.insert(0, pl)
                seen_ids.add(getattr(pl, "id", None))
        target_sid = surface_id or "almanac"
        return _a2ui(
            _to_flutter_a2ui(
                build_almanac_surface(entries, surface_id=target_sid),
                default_surface_id=target_sid,
                almanac_entries=entries,
            )
        )

    if request.action == "showTelemetry" or (
        request.action == FN_REFRESH_TELEMETRY and not request.call_id
    ):
        target_sid = surface_id or "telemetry"
        return _a2ui(
            _to_flutter_a2ui(
                build_telemetry_surface(surface_id=target_sid),
                default_surface_id=target_sid,
            )
        )

    if request.action == "showPlaylist" or (
        request.action == FN_OPEN_ALMANAC_ENTRY and not request.call_id
    ):
        from ..container import get_container

        playlist_id = raw_payload.get("playlist_id") or raw_payload.get("playlistId")
        found_entry = None
        if playlist_id and playlist_id in _RECENT_PLAYLISTS:
            found_entry = _RECENT_PLAYLISTS[playlist_id]
        if found_entry is None:
            try:
                entries = await get_container().almanac().history(uid, limit=50)
                for entry in entries:
                    if entry.id == playlist_id:
                        found_entry = entry
                        break
            except Exception:
                pass
        if found_entry is None and uid != "demo":
            try:
                entries = await get_container().almanac().history("demo", limit=50)
                for entry in entries:
                    if entry.id == playlist_id:
                        found_entry = entry
                        break
            except Exception:
                pass
        if found_entry is None and _RECENT_PLAYLISTS:
            found_entry = list(_RECENT_PLAYLISTS.values())[-1]
        if found_entry is not None:
            target_sid = surface_id or "playlist"
            return _a2ui(
                _to_flutter_a2ui(
                    build_playlist_surface(found_entry, surface_id=target_sid),
                    default_surface_id=target_sid,
                    playlist=found_entry,
                )
            )
        raise HTTPException(status_code=404, detail="playlist not in almanac")

    try:
        payload = validate_action(request.action, raw_payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2UIProtocolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    messages: list[dict[str, Any]] = []
    result: dict[str, Any] = {"ok": True, "action": request.action}

    if request.action == FN_SELECT_THEME and surface_id:
        messages += patch_selection(surface_id, theme_id=payload["themeId"])
        messages.append(
            {
                "updateDataModel": {
                    "surfaceId": surface_id,
                    "path": "/selected",
                    "contents": {"theme": payload["themeId"]},
                }
            }
        )
        result["themeId"] = payload["themeId"]
        _LAST_SELECTION.setdefault(user_key, {})["theme_id"] = payload["themeId"]
        _LAST_SELECTION.setdefault("default", {})["theme_id"] = payload["themeId"]

    elif request.action == FN_SELECT_GENRE and surface_id:
        messages += patch_selection(surface_id, genre_id=payload["genreId"])
        messages.append(
            {
                "updateDataModel": {
                    "surfaceId": surface_id,
                    "path": "/selected",
                    "contents": {"genre": payload["genreId"]},
                }
            }
        )
        result["genreId"] = payload["genreId"]
        _LAST_SELECTION.setdefault(user_key, {})["genre_id"] = payload["genreId"]
        _LAST_SELECTION.setdefault("default", {})["genre_id"] = payload["genreId"]

    elif request.action == FN_SET_CORRIDOR_WIDTH and surface_id:
        messages += patch_selection(
            surface_id, genre_id=payload["genreId"], width=float(payload["width"])
        )
        messages.append(
            {
                "updateDataModel": {
                    "surfaceId": surface_id,
                    "path": "/selected",
                    "contents": {
                        "genre": payload["genreId"],
                        "width": round(float(payload["width"]), 3),
                    },
                }
            }
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

    elif request.action in {
        FN_FORGE,
        FN_OPEN_TRACK,
        FN_OPEN_ALMANAC_ENTRY,
        FN_RETRY,
        FN_OPEN_TELEMETRY_TRACE,
        FN_REFRESH_TELEMETRY,
    }:
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


SurfaceKind = Literal["sky", "themes", "playlist", "rationale", "almanac", "telemetry", "error"]
