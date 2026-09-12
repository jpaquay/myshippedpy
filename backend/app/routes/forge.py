"""HTTP surface for THE FORGE.

Three endpoints, one of which matters more than the other two:
``GET /api/forge/demo`` is the sixty-second demo. It takes no arguments, needs
no credentials, and must work against a completely empty environment. If that
route is slow, awkward or capable of returning a 500, the product does not
have a first impression.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..container import get_container
from ..contracts import Coordinates, ForgeRequest, ForgeResult, Playlist, Rationale
from ..errors import BarogrooveError
from .pairing import current_user_id, get_raw_token_vault

router = APIRouter(prefix="/api", tags=["forge"])

# Brussels. The demo's fixed location, so the demo is reproducible and the
# screenshot in the README always says the same thing.
DEMO_COORDINATES = Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels")

# Fixed seed so two people running the demo a minute apart can compare notes.
DEMO_SEED = 1958  # the year the Van Doorne barograph in the office was made.


@router.post("/forge", response_model=ForgeResult)
async def forge(
    request: ForgeRequest,
    response: Response = None,  # type: ignore[assignment]
    user_id: str | None = Depends(current_user_id),
) -> ForgeResult:
    """Forge a playlist.

    The engine is internally failure-tolerant, so a 500 from here means
    something genuinely unexpected happened rather than "Last.fm is down".
    Partial failures come back as a normal 200 with a populated ``degraded``
    list -- that is the contract, and clients render it.
    """
    from .surfaces import get_last_selection

    uid = user_id if isinstance(user_id, str) and user_id else None
    sel = get_last_selection(uid or "default")
    updates: dict[str, Any] = {}
    if not request.theme_id and sel.get("theme_id"):
        updates["theme_id"] = sel["theme_id"]
    if (not request.genre_id or request.genre_id == "any") and sel.get("genre_id"):
        updates["genre_id"] = sel["genre_id"]

    effective_uid = uid or request.user_id or "demo"
    if not request.user_id:
        updates["user_id"] = effective_uid

    if uid and not request.lastfm_user:
        from .pairing import _get_paired_account

        handle = await _get_paired_account(uid, "lastfm")
        if handle:
            updates["lastfm_user"] = str(handle)
    if not request.lastfm_user and "lastfm_user" not in updates:
        updates["lastfm_user"] = "jpaquay"
    if updates:
        request = request.model_copy(update=updates)

    try:
        result = await get_container().forge().forge(request)
        from .surfaces import record_recent_playlist

        record_recent_playlist(result.playlist)
        if response is not None and getattr(result, "trajectory_id", None):
            response.headers["X-Trajectory-Id"] = str(result.trajectory_id)
        return result
    except BarogrooveError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"forge failed: {exc}",
        ) from exc


@router.get("/forge/demo", response_model=ForgeResult)
async def forge_demo(
    length: int = 18,
    theme_id: str | None = None,
    response: Response = None,  # type: ignore[assignment]
    user_id: str | None = Depends(current_user_id),
) -> ForgeResult:
    """Zero-argument forge over Brussels. The demo endpoint.

    Sink is pinned to ``m3u``: the demo must never depend on an OAuth session,
    and an M3U payload is something a reviewer can actually play. Everything
    else is left to the sky.
    """
    request = ForgeRequest(
        coordinates=DEMO_COORDINATES,
        theme_id=theme_id,
        genre_id="any",
        length=max(4, min(60, length)),
        sink="m3u",
        seed=DEMO_SEED,
    )
    return await forge(request, response=response, user_id=user_id)


@router.post("/forge/explain", response_model=Rationale)
async def explain(
    playlist: Playlist,
    response: Response = None,  # type: ignore[assignment]
) -> Rationale:
    """Re-explain a playlist that already exists.

    Rebuilds the reasoning against the current transfer matrix and rationale
    writer without touching the tracklist, so improving the explanation layer
    retroactively improves every stored playlist.
    """
    try:
        rat = await get_container().forge().explain(playlist)
        if response is not None and getattr(rat, "trajectory_id", None):
            response.headers["X-Trajectory-Id"] = str(rat.trajectory_id)
        return rat
    except BarogrooveError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"explain failed: {exc}",
        ) from exc
