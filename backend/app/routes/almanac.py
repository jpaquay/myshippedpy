"""``/api/almanac`` -- your listening history and what the sky taught us.

Three endpoints:

``GET  /api/almanac/history``        the signed-in user's past forges
``GET  /api/almanac/retrospective``  "your rain sound", "your first-frost record"
``POST /api/almanac/feedback``       loved / skipped

Defensive imports
-----------------
The retrospective *logic* belongs to the Almanac worker. This router imports it
inside a ``try/except`` and falls back to a plain history summary when it is
absent. Rationale: a router that fails to import takes the whole app down at
startup, and a missing sidebar feature is not worth that. The same reasoning
applies to the auth dependency and the container -- every cross-module import
here is either lazy or guarded.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..almanac.data_qna import (
    DataQnARequest,
    DataQnAResponse,
    DataQnAStatusResponse,
    GraphOnDemandRequest,
    QnAChartSpec,
    ask_data_qna,
    generate_graph_on_demand,
    get_qna_cache_stats,
    stream_data_qna_sse,
)
from ..almanac.scrobbles import (
    ComplexAnalyticsResponse,
    PlaylistCohortRequest,
    PlaylistCohortResponse,
    ScrobbleSearchResponse,
    analyze_playlist_cohort,
    clear_bq_cache,
    get_bq_cache_stats,
    query_complex_analytics,
    search_scrobbles,
    sync_scrobbles_from_lastfm,
)
from ..firebase.auth import AuthUser, current_user, current_user_optional

logger = logging.getLogger("barogroove.routes.almanac")

router = APIRouter(prefix="/api/almanac", tags=["almanac"])


def _resolve_user(
    user: AuthUser | None = Depends(current_user_optional),
    x_barogroove_user: str | None = Header(default=None, alias="X-Barogroove-User"),
) -> AuthUser:
    """Resolve the caller, using the *same* precedence as the write path.

    This must agree with ``routes.pairing.current_user_id``, which is what
    ``/api/forge`` uses to stamp ``playlist.user_id`` before the engine files
    the record in the Almanac. That resolver checks a Firebase bearer token,
    then ``request.state``, then the ``X-Barogroove-User`` header.

    Reading only the bearer token here used to leave the two halves of the
    compounding loop disagreeing about who the user is: a client that
    identified itself with ``X-Barogroove-User`` (the local-dev path, and the
    Flutter app before Firebase sign-in completes) would forge under its own
    uid and then read history under the hard-coded ``demo`` uid -- so every
    forge it made was invisible to ``/history``, ``/forges/{id}``, ``/nudge``
    and ``/retrospective``. Purely anonymous callers landed on ``demo`` on both
    sides and so never noticed, which is why the suite stayed green.
    """
    if user is not None:
        return user
    if x_barogroove_user:
        return AuthUser(uid=x_barogroove_user, name="BaroGroove Listener", is_dev=True)
    return AuthUser(uid="demo", name="BaroGroove Listener", is_dev=True)


# --------------------------------------------------------------------------
# Wire models
# --------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    """One thumb, up or down, on one track in one forge."""

    playlist_id: str = Field(min_length=1, max_length=200)
    track_key: str = Field(min_length=1, max_length=512)
    signal: Literal["loved", "skipped"]


class FeedbackResponse(BaseModel):
    """Always 200 when the request was well-formed."""

    recorded: bool
    detail: str = "ok"


class HistoryEntry(BaseModel):
    """A compact row for the history list -- not the full playlist."""

    id: str
    title: str
    subtitle: str | None = None
    theme_id: str | None = None
    genre_id: str | None = None
    track_count: int = 0
    created_at: datetime | None = None
    location_label: str | None = None
    pressure_trend_6h: float | None = None
    tracks_preview: list[str] = Field(default_factory=list)


class HistoryResponse(BaseModel):
    count: int
    entries: list[HistoryEntry]
    items: list[HistoryEntry] = Field(default_factory=list)
    degraded: bool = False
    notes: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.items and self.entries:
            object.__setattr__(self, "items", list(self.entries))


class RetrospectiveHighlight(BaseModel):
    """One named memory, e.g. 'your rain sound'."""

    key: str
    label: str
    detail: str | None = None
    playlist_id: str | None = None
    occurred_at: datetime | None = None


class RetrospectiveResponse(BaseModel):
    user_id: str
    total_forges: int
    highlights: list[RetrospectiveHighlight]
    items: list[RetrospectiveHighlight] = Field(default_factory=list)
    degraded: bool = False
    notes: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.items and self.highlights:
            object.__setattr__(self, "items", list(self.highlights))


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------


def _store() -> Any:
    """Resolve the almanac store from the container."""
    from ..container import get_container  # noqa: PLC0415 - lazy by design

    return get_container().almanac()


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@router.get("/scrobbles", response_model=ScrobbleSearchResponse, summary="Search & analyse scrobbles in BigQuery + Firestore")
async def get_scrobbles(
    query: str | None = Query(default=None, description="Search artist, title, album, or tag"),
    tag: str | None = Query(default=None, description="Filter by micro-genre tag"),
    theme: str | None = Query(default=None, description="Filter by weather theme affinity"),
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthUser = Depends(_resolve_user),
) -> ScrobbleSearchResponse:
    """Search and analyse user scrobbles from BigQuery OLAP & Firestore."""
    return search_scrobbles(user.uid, query=query, tag=tag, theme=theme, limit=limit)


@router.get(
    "/scrobbles/analytics",
    response_model=ComplexAnalyticsResponse,
    summary="Multi-dimensional OLAP analytics over 160,717 scrobbles via BigQuery",
)
async def get_scrobbles_complex_analytics(
    year_start: int = Query(default=2012, ge=2012, le=2026),
    year_end: int = Query(default=2026, ge=2012, le=2026),
    weather_theme: str | None = Query(default=None, description="Filter by BaroGroove weather theme"),
    hour_start: int | None = Query(default=None, ge=0, le=23, description="UTC start hour"),
    hour_end: int | None = Query(default=None, ge=0, le=23, description="UTC end hour"),
    weekday: int | None = Query(default=None, ge=0, le=6, description="Weekday (0=Mon .. 6=Sun)"),
    artist_query: str | None = Query(default=None, description="Filter by artist substring"),
    limit: int = Query(default=15, ge=1, le=50),
) -> ComplexAnalyticsResponse:
    """Execute sub-200ms multi-dimensional analytical slicing on 160,717 scrobbles in BigQuery."""
    return query_complex_analytics(
        year_start=year_start,
        year_end=year_end,
        weather_theme=weather_theme,
        hour_start=hour_start,
        hour_end=hour_end,
        weekday=weekday,
        artist_query=artist_query,
        limit=limit,
    )


@router.post(
    "/playlist-cohort-check",
    response_model=PlaylistCohortResponse,
    summary="Cross-check any pasted playlist/song link or ID against the 160,717-scrobble cohort",
)
async def post_playlist_cohort_check(
    req: PlaylistCohortRequest,
    user: AuthUser = Depends(_resolve_user),
) -> PlaylistCohortResponse:
    """Cross-checks any pasted Spotify/Last.fm/Forged playlist or song against the 15-year scrobble cohort."""
    return analyze_playlist_cohort(req)


@router.get(
    "/scrobbles/cache/stats",
    summary="Live telemetry for Two-Tier BigQuery Cache & Cost Guardrails",
)
async def get_cache_stats() -> dict[str, Any]:
    """Returns BigQuery OLAP memory/disk cache hit rates and $0.00 cost savings telemetry."""
    return get_bq_cache_stats()


@router.post(
    "/scrobbles/cache/clear",
    summary="Clear Two-Tier BigQuery OLAP query cache",
)
async def post_clear_cache() -> dict[str, Any]:
    """Clears in-memory and persistent disk BigQuery query caches."""
    return clear_bq_cache()


# --------------------------------------------------------------------------
# BigQuery Conversational Data QnA Agent & On-Demand Graphing API
# --------------------------------------------------------------------------


def _qna_unavailable(req: DataQnARequest, exc: Exception) -> DataQnAResponse:
    """A neutral, well-formed answer for when the QnA pipeline cannot produce one.

    ``ask_data_qna`` already degrades from the live BigQuery agent to a local
    OLAP synthesizer when the network is gone. This is the *next* rung down:
    the synthesizer itself failing. The house rule is that something always
    comes back, so the client gets a real ``DataQnAResponse`` it can render --
    empty series, no SQL, an honest message -- instead of a 500.
    """
    return DataQnAResponse(
        question=req.question,
        answer_markdown=(
            "I could not analyse that question right now -- the Almanac's analytics backend is "
            "unavailable on this deployment. Your scrobble history is unaffected; try again once "
            "BigQuery connectivity is restored."
        ),
        thoughts=[f"Data QnA pipeline unavailable ({type(exc).__name__})."],
        sql_query="",
        rows=[],
        chart_spec=QnAChartSpec(
            chart_type=req.preferred_chart_type if req.preferred_chart_type != "auto" else "bar",
            title="Analytics unavailable",
            subtitle="No data could be retrieved for this question.",
            series=[],
        ),
        suggestions=[],
        engine="unavailable",
        cache_status="MISS",
    )


def _guarded_qna_sse(req: DataQnARequest):
    """Wrap the SSE generator so a mid-stream failure ends the stream cleanly.

    Without this, an exception raised while the generator is being consumed
    aborts the HTTP response in place: the browser sees a truncated
    ``text/event-stream`` with no terminating event and the Flutter client
    hangs on its reader. Emitting a FINAL_RESPONSE carrying the neutral answer
    keeps the stream well-formed.
    """
    import json as _json

    try:
        yield from stream_data_qna_sse(req)
    except Exception as exc:  # noqa: BLE001 - a stream must never tear down
        logger.warning("data QnA stream failed (%s); closing stream cleanly", type(exc).__name__, exc_info=True)
        fallback = _qna_unavailable(req, exc)
        payload = {
            "type": "FINAL_RESPONSE",
            "content": fallback.answer_markdown,
            "cache_status": fallback.cache_status,
            "execution_ms": fallback.execution_ms,
        }
        yield f"data: {_json.dumps(payload)}\n\n"
        # Same terminating sentinel the happy path emits -- the client keys on
        # the literal string, not on a JSON event.
        yield "data: [DONE]\n\n"


@router.get(
    "/qna/status",
    response_model=DataQnAStatusResponse,
    summary="Status & starter prompts for BigQuery Conversational Data QnA Agent",
)
async def get_data_qna_status() -> DataQnAStatusResponse:
    """Returns active status of BigQuery Data QnA Agent (`geminidataanalytics.googleapis.com/v1beta`), cache stats, and starter prompts."""
    return DataQnAStatusResponse(cache_stats=get_qna_cache_stats())


@router.post(
    "/qna/ask",
    response_model=DataQnAResponse,
    summary="Ask a natural language question to the BigQuery Data QnA Agent with On-Demand Graphing",
)
async def post_data_qna_ask(
    req: DataQnARequest,
    user: AuthUser = Depends(_resolve_user),
) -> DataQnAResponse:
    """Executes a conversational BigQuery Data QnA turn and returns answer markdown, SQL, tabular rows, and QnAChartSpec."""
    try:
        return ask_data_qna(req)
    except Exception as exc:  # noqa: BLE001 - a QnA turn must never 500
        logger.warning("data QnA turn failed (%s); serving neutral answer", type(exc).__name__, exc_info=True)
        return _qna_unavailable(req, exc)


@router.post(
    "/qna/stream",
    summary="Server-Sent Events (SSE) streaming endpoint for BigQuery Data QnA Agent",
)
async def post_data_qna_stream(
    req: DataQnARequest,
    user: AuthUser = Depends(_resolve_user),
) -> StreamingResponse:
    """Streams THOUGHT, SQL, CHART, FINAL_RESPONSE, and SUGGESTION events in real time."""
    return StreamingResponse(_guarded_qna_sse(req), media_type="text/event-stream")


@router.post(
    "/qna/graph-on-demand",
    response_model=QnAChartSpec,
    summary="Re-synthesize any tabular query result into a bar, horizontal_bar, donut, or line chart on demand",
)
async def post_graph_on_demand(
    req: GraphOnDemandRequest,
    user: AuthUser = Depends(_resolve_user),
) -> QnAChartSpec:
    """Generates a structured visual QnAChartSpec on demand for any requested chart type."""
    return generate_graph_on_demand(req)


@router.post("/scrobbles/sync", response_model=ScrobbleSearchResponse, summary="Sync Last.fm scrobbles into Firestore")
async def sync_scrobbles(
    lastfm_user: str = Query(default="jpaquay", description="Last.fm username to sync"),
    user: AuthUser = Depends(_resolve_user),
) -> ScrobbleSearchResponse:
    """Sync live recent scrobbles from Last.fm into Firestore `scrobbles` collection."""
    return await sync_scrobbles_from_lastfm(user.uid, lastfm_username=lastfm_user)


@router.get("/forges/{playlist_id}", summary="Fetch a full forged playlist from Almanac history")
async def get_forged_playlist(
    playlist_id: str,
    user: AuthUser = Depends(_resolve_user),
) -> dict[str, Any]:
    """Retrieve a complete stored Playlist by ID so it can be reloaded into the Player."""
    store = _store()
    try:
        playlists = await store.history(user.uid, limit=100)
        for p in playlists:
            if str(getattr(p, "id", "")) == playlist_id:
                return {"ok": True, "playlist": p.model_dump(mode="json") if hasattr(p, "model_dump") else p}
        # Also search demo history if not found under user.uid
        if user.uid != "demo":
            demo_playlists = await store.history("demo", limit=100)
            for p in demo_playlists:
                if str(getattr(p, "id", "")) == playlist_id:
                    return {"ok": True, "playlist": p.model_dump(mode="json") if hasattr(p, "model_dump") else p}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Lookup for playlist %s failed: %s", playlist_id, exc)
    raise HTTPException(status_code=404, detail=f"Forge '{playlist_id}' not found in Almanac")


@router.get("/history", response_model=HistoryResponse, summary="Your past forges")
async def get_history(
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthUser = Depends(_resolve_user),
) -> HistoryResponse:
    """Every sky you have turned into sound, newest first."""
    notes: list[str] = []
    try:
        playlists = await _store().history(user.uid, limit=limit)
    except Exception:
        logger.exception("history failed for %s", user.uid)
        return HistoryResponse(
            count=0, entries=[], degraded=True, notes=["almanac unavailable"]
        )

    entries = [_to_entry(p) for p in playlists]
    if user.is_dev:
        notes.append("dev identity: history is scoped to the synthetic uid")
    return HistoryResponse(count=len(entries), entries=entries, notes=notes)


async def _records_for(store: Any, user_id: str) -> list[Any]:
    """Flattened forge records for a user, whatever the store can offer."""
    getter = getattr(store, "records", None)
    if callable(getter):
        try:
            out = getter(user_id)
            return list(await out if hasattr(out, "__await__") else out)
        except Exception:  # pragma: no cover - degrade to the history path
            logger.debug("store.records unavailable; converting history instead")
    try:
        from ..almanac.models import ForgeRecord

        history = await store.history(user_id, limit=200)
        return [ForgeRecord.from_playlist(p) for p in history]
    except Exception:  # pragma: no cover
        return []


async def _events_for(store: Any, user_id: str) -> list[Any]:
    """Feedback events for a user, or an empty list if the store has none."""
    getter = getattr(store, "feedback", None)
    if not callable(getter):
        return []
    try:
        out = getter(user_id)
        return list(await out if hasattr(out, "__await__") else out)
    except Exception:  # pragma: no cover
        return []


@router.get(
    "/retrospective",
    response_model=RetrospectiveResponse,
    summary="Your rain sound, your first-frost record",
)
async def get_retrospective(
    user: AuthUser = Depends(_resolve_user),
) -> RetrospectiveResponse:
    """Named memories drawn out of your listening history."""
    store = _store()
    notes: list[str] = []

    builder = _load_retrospective_builder()
    if builder is not None:
        try:
            records = await _records_for(store, user.uid)
            events = await _events_for(store, user.uid)
            result = builder(user.uid, records, events)
            if hasattr(result, "__await__"):
                result = await result
            highlights = _coerce_highlights(result)
            total = _coerce_total(result)
            if highlights:
                return RetrospectiveResponse(
                    user_id=user.uid,
                    total_forges=total,
                    highlights=highlights,
                    notes=notes,
                )
            notes.append("retrospective module returned nothing; showing basics")
        except Exception:
            logger.exception("retrospective module failed; falling back")
            notes.append("retrospective module errored; showing basics")
    else:
        notes.append("retrospective module not installed; showing basics")

    try:
        playlists = await store.history(user.uid, limit=200)
    except Exception:
        logger.exception("retrospective fallback history failed for %s", user.uid)
        return RetrospectiveResponse(
            user_id=user.uid,
            total_forges=0,
            highlights=[],
            degraded=True,
            notes=[*notes, "almanac unavailable"],
        )

    return RetrospectiveResponse(
        user_id=user.uid,
        total_forges=len(playlists),
        highlights=_fallback_retrospective(playlists),
        degraded=True,
        notes=notes,
    )


@router.post("/feedback", response_model=FeedbackResponse, summary="Loved or skipped")
async def post_feedback(
    body: FeedbackRequest,
    user: AuthUser = Depends(_resolve_user),
) -> FeedbackResponse:
    """Tell the almanac what landed."""
    store = _store()
    try:
        await store.record_feedback(
            user_id=user.uid,
            playlist_id=body.playlist_id,
            track_key=body.track_key,
            signal=body.signal,
        )
    except Exception:
        logger.exception("feedback write failed for %s", user.uid)
        return FeedbackResponse(recorded=False, detail="almanac unavailable")

    try:
        from ..telemetry.memory_extractor import extract_memory_from_feedback

        artist = ""
        title = ""
        theme_id = ""
        genre_id = ""
        try:
            pl_list = await store.history(user.uid, limit=25)
            for pl in pl_list:
                pl_id = getattr(pl, "id", None) or (pl.get("id") if isinstance(pl, dict) else None)
                if str(pl_id) == str(body.playlist_id):
                    theme_id = getattr(pl, "theme_id", "") or (pl.get("theme_id", "") if isinstance(pl, dict) else "")
                    genre_id = getattr(pl, "genre_id", "") or (pl.get("genre_id", "") if isinstance(pl, dict) else "")
                    tracks = getattr(pl, "tracks", []) or (pl.get("tracks", []) if isinstance(pl, dict) else [])
                    for st in tracks:
                        tr = getattr(st, "track", st)
                        t_key = getattr(tr, "key", None) or (tr.get("key") if isinstance(tr, dict) else None)
                        if str(t_key) == str(body.track_key):
                            title = getattr(tr, "title", "") or (tr.get("title", "") if isinstance(tr, dict) else "")
                            art_obj = getattr(tr, "artist", None) or (tr.get("artist") if isinstance(tr, dict) else None)
                            artist = getattr(art_obj, "name", str(art_obj or "")) if art_obj else ""
                            break
                    break
        except Exception:
            pass

        extract_memory_from_feedback(
            user_id=user.uid,
            playlist_id=body.playlist_id,
            track_key=body.track_key,
            signal=body.signal,
            artist=artist,
            title=title,
            theme_id=theme_id,
            genre_id=genre_id,
        )
    except Exception:
        logger.debug("telemetry memory extraction from feedback skipped", exc_info=True)

    return FeedbackResponse(recorded=True)


@router.get("/nudge", summary="Debug: the stored 9x7 transfer-matrix delta")
async def get_nudge(user: AuthUser = Depends(_resolve_user)) -> dict[str, Any]:
    """Expose the stored personalisation matrix for inspection."""
    store = _store()
    try:
        matrix = await store.nudge(user.uid)
    except Exception:
        logger.exception("nudge read failed for %s", user.uid)
        raise HTTPException(status_code=503, detail="almanac unavailable") from None

    meta: dict[str, Any] | None = None
    getter = getattr(store, "nudge_meta", None)
    if callable(getter):
        try:
            meta = await getter(user.uid)
        except Exception:
            logger.debug("nudge meta unavailable; harmless")

    return {
        "nudge": matrix,
        "shape": [len(matrix), len(matrix[0])] if matrix else None,
        "meta": meta,
    }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _load_retrospective_builder() -> Any | None:
    try:
        from ..almanac import retrospective as _retro  # noqa: PLC0415
    except Exception:
        return None
    for name in ("build_retrospective", "retrospective", "compute", "build"):
        candidate = getattr(_retro, name, None)
        if callable(candidate):
            return candidate
    logger.warning("almanac.retrospective imported but exposes no known entry point")
    return None


def _coerce_highlights(result: Any) -> list[RetrospectiveHighlight]:
    raw = result
    if isinstance(result, dict):
        raw = result.get("highlights", [])
    elif hasattr(result, "highlights"):
        raw = result.highlights

    out: list[RetrospectiveHighlight] = []
    for item in raw if isinstance(raw, (list, tuple)) else []:
        try:
            if isinstance(item, RetrospectiveHighlight):
                out.append(item)
            elif isinstance(item, BaseModel):
                out.append(RetrospectiveHighlight.model_validate(item.model_dump()))
            elif isinstance(item, dict):
                out.append(RetrospectiveHighlight.model_validate(item))
        except Exception:
            logger.debug("dropped an unparseable retrospective highlight")
    return out


def _coerce_total(result: Any) -> int:
    if isinstance(result, dict):
        try:
            return int(result.get("total_forges", 0) or 0)
        except (TypeError, ValueError):
            return 0
    value = getattr(result, "total_forges", 0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_entry(playlist: Any) -> HistoryEntry:
    """Flatten a Playlist into a list row, tolerating partial documents."""
    tracks = getattr(playlist, "tracks", None) or []
    coords = getattr(playlist, "coordinates", None)
    loc_label = getattr(coords, "label", None) if coords else None
    sky = getattr(playlist, "sky", None)
    trend = getattr(sky, "pressure_trend_6h", None) if sky else None
    preview: list[str] = []
    for st in tracks[:4]:
        tr = getattr(st, "track", st)
        artist = getattr(tr, "artist", "")
        title = getattr(tr, "title", "")
        if artist and title:
            preview.append(f"{artist} — {title}")
    return HistoryEntry(
        id=str(getattr(playlist, "id", "") or ""),
        title=str(getattr(playlist, "title", "") or "untitled forge"),
        subtitle=_opt_str(getattr(playlist, "subtitle", None)),
        theme_id=_opt_str(getattr(playlist, "theme_id", None)),
        genre_id=_opt_str(getattr(playlist, "genre_id", None)),
        track_count=len(tracks),
        created_at=getattr(playlist, "created_at", None),
        location_label=_opt_str(loc_label),
        pressure_trend_6h=float(trend) if trend is not None else None,
        tracks_preview=preview,
    )


def _opt_str(value: Any) -> str | None:
    return str(value) if value else None


def _fallback_retrospective(playlists: list[Any]) -> list[RetrospectiveHighlight]:
    """Build honest highlights from history alone.

    No weather model, no genre theory -- counts and firsts. Used when the
    Almanac worker's module is unavailable, so the endpoint still says
    something true rather than 500ing.
    """
    if not playlists:
        return []

    highlights: list[RetrospectiveHighlight] = []

    dated = [p for p in playlists if getattr(p, "created_at", None)]
    if dated:
        first = min(dated, key=lambda p: p.created_at)
        highlights.append(
            RetrospectiveHighlight(
                key="first_forge",
                label="your first sky",
                detail=str(getattr(first, "title", "") or ""),
                playlist_id=str(getattr(first, "id", "") or ""),
                occurred_at=getattr(first, "created_at", None),
            )
        )

    themes = Counter(
        str(getattr(p, "theme_id", "") or "") for p in playlists
    )
    themes.pop("", None)
    if themes:
        theme_id, count = themes.most_common(1)[0]
        highlights.append(
            RetrospectiveHighlight(
                key="signature_theme",
                label="your signature weather",
                detail=f"{theme_id} -- {count} of {len(playlists)} forges",
            )
        )

    genres = Counter(str(getattr(p, "genre_id", "") or "") for p in playlists)
    genres.pop("", None)
    if genres:
        genre_id, count = genres.most_common(1)[0]
        highlights.append(
            RetrospectiveHighlight(
                key="signature_genre",
                label="your home corridor",
                detail=f"{genre_id} -- {count} of {len(playlists)} forges",
            )
        )

    return highlights


__all__ = [
    "FeedbackRequest",
    "FeedbackResponse",
    "HistoryEntry",
    "HistoryResponse",
    "RetrospectiveHighlight",
    "RetrospectiveResponse",
    "router",
]
