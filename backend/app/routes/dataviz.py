"""FastAPI routes for the BaroGroove Data Viz Dashboard & Gemini Live 2.5 QnA Agent."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.dataviz.engine import (
    DataVizDashboardResponse,
    DataVizQnARequest,
    DataVizQnAResponse,
    get_dataviz_engine,
)
from backend.app.firebase.auth import current_user_optional

router = APIRouter(prefix="/api/dataviz", tags=["dataviz"])

_engine = get_dataviz_engine()


async def _resolve_uid(request: Request) -> str:
    """Return authenticated user UID or 'jpaquay' fallback."""
    user = await current_user_optional(request)
    return user.uid if user and user.uid else "jpaquay"


@router.get(
    "/dashboard",
    response_model=DataVizDashboardResponse,
    summary="Get aggregated BaroGroove Sonic Almanac telemetry and atmospheric correlation charts",
)
async def dataviz_dashboard(request: Request) -> DataVizDashboardResponse:
    uid = await _resolve_uid(request)
    return _engine.get_dashboard(user_id=uid)


@router.post(
    "/qna",
    response_model=DataVizQnAResponse,
    summary="Ask the Gemini Live 2.5 Flash Data Viz QnA Agent a question about your sonic telemetry",
)
async def dataviz_qna(
    request: Request,
    payload: DataVizQnARequest,
) -> DataVizQnAResponse:
    uid = await _resolve_uid(request)
    return await _engine.answer_question(req=payload, user_id=uid)
