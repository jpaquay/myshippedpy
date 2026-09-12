"""FastAPI routes for the Gemini Live Forge Advisor & Executor."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.advisor.engine import (
    AdvisorEngine,
    AdvisorLiveRequest,
    AdvisorLiveResponse,
    AdvisorSuggestionItem,
    get_advisor_suggestions,
)
from backend.app.firebase.auth import current_user_optional

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
