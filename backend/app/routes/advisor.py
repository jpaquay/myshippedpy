"""FastAPI routes for the Gemini Live Forge Advisor & Executor.

Three endpoints, and the last two are plan item 11 -- operating BAROGROOVE by
conversation, under the user's standing policy:

    read and select freely, CONFIRM before anything that writes.

``GET  /api/advisor/tools``
    The capability manifest, with a ``writes`` flag on every entry. This is why
    the Flutter app contains no list of write-function names: the
    classification is declared in Python (``ToolSpec.writes`` for MCP tools,
    ``AgentFunction.writes`` for agent functions, ``WRITE_FUNCTION_IDS`` in the
    A2UI catalog) and travels to the client.

``POST /api/advisor/act``
    Invoke one capability. A read or a select runs. A **write** does not: it
    comes back ``confirmation_required`` with a single-use, principal-bound
    ticket and the arguments the server would have used, so the overlay can
    draw an inline action card with every argument visible and editable
    (``docs/UX_IA_SPEC.md`` 6.5). Confirming re-posts with the ticket.

The refusal is not a UI convention. It is
:func:`backend.app.mcp.confirm.require_confirmation`, on the server, on the
path every transport shares. A client that never renders a card, or is patched
to skip one, gets ``confirmation_required`` and no write.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.app.advisor.engine import (
    AdvisorEngine,
    AdvisorLiveRequest,
    AdvisorLiveResponse,
    AdvisorSuggestionItem,
    get_advisor_suggestions,
)
from backend.app.firebase.auth import current_user_optional
from backend.app.mcp.gateway import capabilities, perform

router = APIRouter(prefix="/api/advisor", tags=["advisor"])

_engine = AdvisorEngine()


async def _resolve_uid(request: Request) -> str:
    """Return authenticated user UID or 'demo' fallback."""
    user = await current_user_optional(request)
    return user.uid if user and user.uid else "demo"


@router.get(
    "/suggestions",
    response_model=list[AdvisorSuggestionItem],
    summary="Get voice & tap quick-prompt suggestions grounded in world timezones and Almanac DNA",
)
async def advisor_suggestions(request: Request) -> list[AdvisorSuggestionItem]:
    uid = await _resolve_uid(request)
    return get_advisor_suggestions(user_id=uid)


@router.post(
    "/live",
    response_model=AdvisorLiveResponse,
    summary="Execute a conversational or voice turn with the Gemini Live Forge Advisor & Executor",
)
async def advisor_live_turn(
    request: Request,
    payload: AdvisorLiveRequest,
) -> AdvisorLiveResponse:
    uid = await _resolve_uid(request)
    return await _engine.execute_turn(req=payload, user_id=uid)


# ======================================================================
# Item 11 -- operating the app by conversation, with a write gate
# ======================================================================


class ActRequest(BaseModel):
    """Invoke one named capability.

    ``confirmation_token`` is the ONLY field that can turn a refused write into
    an executed one, and it cannot be invented: it is a value this process
    minted when it refused the same call a moment ago, bound to this function
    and this principal, good once, for five minutes.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    function: str = Field(description="Capability name, e.g. 'forge_playlist'.")
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmation_token: str | None = Field(default=None, alias="confirmationToken")
    surface_id: str | None = Field(default=None, alias="surfaceId")
    call_id: str | None = Field(default=None, alias="callId")


@router.get(
    "/tools",
    summary="Capabilities the assistant may invoke, and which of them write",
)
async def advisor_tools() -> dict[str, Any]:
    """The manifest the overlay reads to decide when to ask before acting.

    Unauthenticated on purpose: it describes the shape of the API and contains
    no user data. Knowing that ``forge_playlist`` writes buys a caller nothing
    -- the gate does not consult this response.
    """
    return {"capabilities": capabilities()}


@router.post(
    "/act",
    summary="Invoke an MCP capability by conversation (writes need confirmation)",
)
async def advisor_act(request: Request, payload: ActRequest) -> dict[str, Any]:
    """Run a capability, or refuse and hand back a confirmation ticket.

    The principal is resolved from the verified bearer token, exactly as
    ``/live`` does, and never from the request body -- a ticket bound to
    something the caller supplies would be a ticket the caller can forge.
    """
    uid = await _resolve_uid(request)
    result = await perform(
        payload.function,
        payload.arguments,
        principal=uid,
        confirmation_token=payload.confirmation_token,
        surface_id=payload.surface_id,
        call_id=payload.call_id,
    )
    # Always HTTP 200: `confirmation_required` is a normal step in a normal
    # conversation, not a transport error, and the renderer branches on
    # `status`. Errors carry a plain-language `error.message`.
    return result.as_payload()
