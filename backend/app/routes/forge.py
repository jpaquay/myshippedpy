"""HTTP surface for THE FORGE.

``GET /api/forge/demo`` is the sixty-second demo. It takes no arguments, needs
no credentials, and must work against a completely empty environment. If that
route is slow, awkward or capable of returning a 500, the product does not
have a first impression.

Two ways to forge
-----------------
``POST /api/forge``
    Synchronous. The playlist comes back in the response. Simple, and exactly
    as fragile as the connection: lose the socket and you lose the run.

``POST /api/forge/jobs`` -> ``GET /api/forge/jobs/{id}``
    The forge becomes a tracked server-side job (see ``app.forge.jobs``). It
    runs to completion whether or not the client is still listening, lands in
    recent playlists when it finishes, and can be polled or resumed rather
    than restarted. **Starting is idempotent** — pass the ``job_id`` you
    generated and a retried start returns the same job instead of forging
    twice. This is the endpoint a real client should use.

Both paths run the same ``_prepare_request`` / ``_execute_forge`` pair.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..almanac.seed_corpus import SEED_CORPUS_HANDLE
from ..container import get_container
from ..identity import ANONYMOUS_USER_ID
from ..contracts import Coordinates, ForgeRequest, ForgeResult, Playlist, Rationale
from ..errors import BarogrooveError
from ..forge.jobs import ForgeJobEnvelope, get_forge_jobs
from .pairing import current_user_id, get_raw_token_vault

router = APIRouter(prefix="/api", tags=["forge"])

# Brussels. The demo's fixed location, so the demo is reproducible and the
# screenshot in the README always says the same thing.
DEMO_COORDINATES = Coordinates(latitude=50.8503, longitude=4.3517, label="Brussels")

# Fixed seed so two people running the demo a minute apart can compare notes.
DEMO_SEED = 1958  # the year the Van Doorne barograph in the office was made.


# ===========================================================================
# Shared forge mechanics
#
# One preparation step and one execution step, used by BOTH the synchronous
# route and the background job runner. If these ever diverge, a job and a
# direct forge stop producing the same playlist for the same input, and the
# job path silently becomes a second, worse product.
# ===========================================================================


async def _prepare_request(request: ForgeRequest, user_id: str | None) -> ForgeRequest:
    """Fill in everything the caller left to the server: theme, genre, identity."""
    from .surfaces import get_last_selection

    uid = user_id if isinstance(user_id, str) and user_id else None
    # A signed-out caller gets the reserved anonymous scope, which owns
    # nothing, rather than the shared "default" bucket every other signed-out
    # caller was also reading from.
    sel = get_last_selection(uid or ANONYMOUS_USER_ID)
    updates: dict[str, Any] = {}
    if not request.theme_id and sel.get("theme_id"):
        updates["theme_id"] = sel["theme_id"]
    if (not request.genre_id or request.genre_id == "any") and sel.get("genre_id"):
        updates["genre_id"] = sel["genre_id"]

    # TENANCY. This used to be `uid or request.user_id or "demo"`, and
    # `request.user_id` is a field on the REQUEST BODY. An unauthenticated
    # caller could therefore name any uid they liked and have the forge
    # stamped as that person: the playlist landed in the victim's history, and
    # because SpotifySink resolves the refresh token from the *stamped* owner,
    # it published into the victim's Spotify account. Identity now comes from
    # the authenticated resolver alone; a body-supplied user_id is ignored, and
    # an unresolved caller gets the anonymous scope, never a real tenant.
    effective_uid = uid or ANONYMOUS_USER_ID
    updates["user_id"] = effective_uid

    if uid and not request.lastfm_user:
        from .pairing import _get_paired_account

        handle = await _get_paired_account(uid, "lastfm")
        if handle:
            updates["lastfm_user"] = str(handle)
    if not request.lastfm_user and "lastfm_user" not in updates:
        # No paired Last.fm account, so there is no personal taste to read.
        # Fall back to the DEMO SEED taste -- named as such, because this is a
        # real Last.fm handle and the audit found it doing duty as a fallback
        # *identity* in three other places (findings 5, 7, 9). Here it is only
        # ever a source of taste data: it is not written anywhere, and it never
        # becomes the forge's owner, which is stamped from `effective_uid`
        # above. A signed-in user's history and taste vector stay their own.
        updates["lastfm_user"] = SEED_CORPUS_HANDLE
    if updates:
        request = request.model_copy(update=updates)
    return request


async def _execute_forge(request: ForgeRequest) -> ForgeResult:
    """Run the engine and publish the playlist to the recent list.

    The publish step lives here rather than in the route handler precisely so
    that a job which finishes after its client has gone still lands in recent
    playlists. That is item 4's "runs to completion independently".
    """
    result = await get_container().forge().forge(request)
    from .surfaces import record_recent_playlist

    record_recent_playlist(result.playlist)
    return result


def _owner_of(user_id: str | None) -> str:
    """Job ownership key.

    Anonymous callers share the reserved anonymous scope, which is also what
    ``_prepare_request`` stamps onto the request itself -- the two must agree,
    because a job bucketed under one identity and a forge stamped with another
    is exactly the read/write split behind 9820091.

    They used to share ``"demo"``, which is a REAL tenant with real rows.
    """
    return user_id if isinstance(user_id, str) and user_id else ANONYMOUS_USER_ID


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

    Kept synchronous for back-compatibility and for the demo path. Clients
    that care about surviving a reconnect should use ``POST /api/forge/jobs``
    instead; both run the exact same code below.
    """
    request = await _prepare_request(request, user_id)

    try:
        result = await _execute_forge(request)
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


# ===========================================================================
# Forge jobs — item 4
#
# LIFETIME CAVEAT, stated where someone will actually read it: the registry
# behind these three endpoints is in-process. Jobs do NOT survive a restart, a
# crash, or a Cloud Run scale-to-zero, and with more than one instance a poll
# may hit a replica that never saw the job. A 404 from the poll endpoint
# therefore means "unknown here", not "never existed" — clients treat it as a
# cue to re-start rather than as an error. What does survive is the finished
# playlist, which the engine persists exactly as the synchronous route does.
# ===========================================================================


@router.post(
    "/forge/jobs",
    response_model=ForgeJobEnvelope,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_forge_job(
    request: ForgeRequest,
    response: Response = None,  # type: ignore[assignment]
    job_id: str | None = Query(
        default=None,
        max_length=64,
        description=(
            "Client-generated idempotency key. Send the same value on a retry "
            "and you get the same job back instead of a second forge."
        ),
    ),
    user_id: str | None = Depends(current_user_id),
) -> ForgeJobEnvelope:
    """Start a forge as a background job. Returns immediately with its id.

    Idempotent twice over: an already-known ``job_id`` short-circuits, and
    failing that an identical still-running request for the same owner is
    joined rather than duplicated. A transport-level retry of this call can
    never produce two playlists — which is what makes the retry policy in
    ``api/client.dart`` safe to apply to it.
    """
    prepared = await _prepare_request(request, user_id)
    owner = _owner_of(user_id)

    async def _runner() -> ForgeResult:
        return await _execute_forge(prepared)

    try:
        job, resumed = await get_forge_jobs().submit(
            owner=owner,
            request=prepared,
            runner=_runner,
            job_id=(job_id or None),
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that job id belongs to another session",
        ) from exc

    if response is not None and resumed:
        # 200 rather than 202: nothing new was accepted, you were handed the
        # run that was already in flight.
        response.status_code = status.HTTP_200_OK
    return job.envelope(resumed=resumed)


@router.get("/forge/jobs", response_model=list[ForgeJobEnvelope])
async def list_forge_jobs(
    limit: int = Query(default=5, ge=1, le=25),
    active_only: bool = Query(
        default=False,
        description="Only jobs that are still queued or running.",
    ),
    user_id: str | None = Depends(current_user_id),
) -> list[ForgeJobEnvelope]:
    """Recent jobs for the caller, newest first.

    This is the reconnect path for a client that lost its job id entirely —
    a hard page reload, say. It finds the run it started instead of starting
    another one.
    """
    owner = _owner_of(user_id)
    jobs = get_forge_jobs().list_for(owner, limit=limit)
    if active_only:
        jobs = [j for j in jobs if not j.terminal]
    return [j.envelope(resumed=True) for j in jobs]


@router.get("/forge/jobs/{job_id}", response_model=ForgeJobEnvelope)
async def get_forge_job(
    job_id: str,
    user_id: str | None = Depends(current_user_id),
) -> ForgeJobEnvelope:
    """Poll a job. Safe to call as often as you like; it touches nothing."""
    job = get_forge_jobs().get(job_id, owner=_owner_of(user_id))
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "no such forge job on this instance; it may have finished long "
                "ago or the process may have restarted"
            ),
        )
    return job.envelope(resumed=True)
