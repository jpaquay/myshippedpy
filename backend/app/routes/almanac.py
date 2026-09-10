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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..firebase.auth import AuthUser, current_user

logger = logging.getLogger("barogroove.routes.almanac")

router = APIRouter(prefix="/api/almanac", tags=["almanac"])


# --------------------------------------------------------------------------
# Wire models
# --------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    """One thumb, up or down, on one track in one forge."""

    playlist_id: str = Field(min_length=1, max_length=200)
    track_key: str = Field(min_length=1, max_length=512)
    signal: Literal["loved", "skipped"]


class FeedbackResponse(BaseModel):
    """Always 200 when the request was well-formed.

    ``recorded`` is advisory: the almanac is best-effort, and the client should
    not un-highlight a heart because Firestore hiccuped.
    """

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


class HistoryResponse(BaseModel):
    count: int
    entries: list[HistoryEntry]
    degraded: bool = False
    notes: list[str] = Field(default_factory=list)


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
    degraded: bool = False
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------


def _store() -> Any:
    """Resolve the almanac store from the container.

    Kept as a function rather than a module-level lookup so importing this
    module never constructs a container, and so tests can override it.
    """
    from ..container import get_container  # noqa: PLC0415 - lazy by design

    return get_container().almanac()


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@router.get("/history", response_model=HistoryResponse, summary="Your past forges")
async def get_history(
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthUser = Depends(current_user),
) -> HistoryResponse:
    """Every sky you have turned into sound, newest first.

    Degrades to an empty list with ``degraded: true`` if the store is
    unreachable. The client renders "nothing here yet" either way; the flag
    lets it say "we could not reach your almanac" instead of implying you have
    never used the app.
    """
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
    user: AuthUser = Depends(current_user),
) -> RetrospectiveResponse:
    """Named memories drawn out of your listening history.

    Delegates to the Almanac worker's retrospective module when it is present.
    When it is not, falls back to :func:`_fallback_retrospective`, which builds
    a handful of honest highlights out of the history rows alone -- no weather
    reasoning, no cleverness, just counting.
    """
    store = _store()
    notes: list[str] = []

    builder = _load_retrospective_builder()
    if builder is not None:
        try:
            # build_retrospective takes the flattened records, not the store:
            # it is a pure function so it can be tested and replayed without a
            # database. Prefer the store's native record/feedback accessors and
            # fall back to converting the Playlist history when a store (like
            # the Firestore one) only offers that.
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
    user: AuthUser = Depends(current_user),
) -> FeedbackResponse:
    """Tell the almanac what landed.

    Signals feed the Almanac worker's fit, which eventually shows up as the
    9x7 delta returned by ``nudge()``. Validation of ``signal`` happens in the
    model, so anything reaching the store is already one of two literals.
    """
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
    return FeedbackResponse(recorded=True)


@router.get("/nudge", summary="Debug: the stored 9x7 transfer-matrix delta")
async def get_nudge(user: AuthUser = Depends(current_user)) -> dict[str, Any]:
    """Expose the stored personalisation matrix for inspection.

    Not a product surface -- a debugging one. Returns ``{"nudge": null}`` when
    nothing has been learned yet, which is the honest answer for a new user and
    for an unreachable store alike.
    """
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
    """Find the Almanac worker's retrospective entry point, if it shipped.

    Tries a couple of plausible names because the two modules are being written
    in parallel. Anything found must be callable as
    ``builder(store=..., user_id=...)``.
    """
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
    """Accept whatever shape the other worker returns, within reason.

    Handles: a list of dicts/models, or a mapping with a ``highlights`` key.
    Anything unparseable is dropped rather than raised.
    """
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
    """Pull a total count out of the other worker's payload, else 0."""
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
    return HistoryEntry(
        id=str(getattr(playlist, "id", "") or ""),
        title=str(getattr(playlist, "title", "") or "untitled forge"),
        subtitle=_opt_str(getattr(playlist, "subtitle", None)),
        theme_id=_opt_str(getattr(playlist, "theme_id", None)),
        genre_id=_opt_str(getattr(playlist, "genre_id", None)),
        track_count=len(tracks),
        created_at=getattr(playlist, "created_at", None),
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
