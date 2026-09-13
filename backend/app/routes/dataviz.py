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
from backend.app.identity import ANONYMOUS_USER_ID

router = APIRouter(prefix="/api/dataviz", tags=["dataviz"])

_engine = get_dataviz_engine()


async def _resolve_uid(request: Request) -> str:
    """Return the authenticated caller's uid, or the reserved anonymous scope.

    TENANCY. This used to fall back to the literal uid ``"jpaquay"`` -- a real,
    named human being -- so every signed-out visitor read and wrote dataviz
    telemetry as him. The advisor route fell back to ``"demo"`` instead, and
    the telemetry store's ``demo`` <-> ``jpaquay`` alias (audit finding 7)
    papered over the disagreement. Both now name the same reserved, empty
    scope. See ``identity.ANONYMOUS_USER_ID``.
    """
    user = await current_user_optional(request)
    return user.uid if user and user.uid else ANONYMOUS_USER_ID


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
