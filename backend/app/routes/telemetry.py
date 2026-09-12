"""REST API surface for BaroGroove AI Observability & Telemetry (`/api/telemetry` & `/api/observability`).

Exposes inspection, filtering, and CRUD endpoints for:
- AI Trajectories (`GET /trajectories`, `GET /trajectories/{trajectory_id}`)
- User Sessions (`GET /sessions`, `GET /sessions/{session_id}`)
- Multi-Turn Conversations (`GET /conversations`, `GET /conversations/{conversation_id}`)
- Semantic User Memories (`GET /memories`, `POST /memories`, `DELETE /memories/{memory_id}`)
- Live Telemetry Summary Metrics (`GET /summary`)
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..telemetry.models import MemoryCreateRequest, MemoryRecord
from ..telemetry.store import get_telemetry_store

router = APIRouter(tags=["telemetry"])


@router.get("/trajectories", summary="List and filter AI trajectories")
async def list_trajectories(
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    surface: str | None = Query(default=None, description="Filter by surface (advisor, dataviz, forge, a2ui, mcp)"),
    session_id: str | None = Query(default=None, description="Filter by session ID"),
    conversation_id: str | None = Query(default=None, description="Filter by conversation ID"),
    model_path: str | None = Query(default=None, description="Filter by execution path alias"),
    execution_path: str | None = Query(default=None, description="Filter by execution path (vertex-ai, semantic-fallback, deterministic-fallback)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    store = get_telemetry_store()
    items, total = store.list_trajectories(
        user_id=user_id,
        surface=surface,
        session_id=session_id,
        conversation_id=conversation_id,
        model_path=model_path,
        execution_path=execution_path,
        limit=limit,
        offset=offset,
    )
    serialized = [t.model_dump(mode="json") for t in items]
    return {
        "count": total,
        "trajectories": serialized,
        "items": serialized,
    }


@router.get("/trajectories/{trajectory_id}", summary="Get a single AI trajectory by ID")
async def get_trajectory_detail(trajectory_id: str) -> dict[str, Any]:
    store = get_telemetry_store()
    traj = store.get_trajectory(trajectory_id)
    if traj is None:
        raise HTTPException(status_code=404, detail=f"Trajectory '{trajectory_id}' not found")
    return traj.model_dump(mode="json")


@router.get("/sessions", summary="List active and historical AI user sessions")
async def list_sessions(
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    surface: str | None = Query(default=None, description="Filter by client surface"),
    active_only: bool = Query(default=False, description="Only sessions with turn_count > 0"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    store = get_telemetry_store()
    items, total = store.list_sessions(
        user_id=user_id,
        surface=surface,
        active_only=active_only,
        limit=limit,
    )
    serialized = [s.model_dump(mode="json") for s in items]
    return {
        "count": total,
        "sessions": serialized,
        "items": serialized,
    }


@router.get("/sessions/{session_id}", summary="Get a single AI user session by ID")
async def get_session_detail(session_id: str) -> dict[str, Any]:
    store = get_telemetry_store()
    sess = store.get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return sess.model_dump(mode="json")


@router.get("/conversations", summary="List multi-turn AI conversation threads")
async def list_conversations(
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    session_id: str | None = Query(default=None, description="Filter by session ID"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    store = get_telemetry_store()
    items, total = store.list_conversations(
        user_id=user_id,
        session_id=session_id,
        limit=limit,
    )
    serialized = [c.model_dump(mode="json") for c in items]
    return {
        "count": total,
        "conversations": serialized,
        "items": serialized,
    }


@router.get("/conversations/{conversation_id}", summary="Get a single conversation thread with all turns")
async def get_conversation_detail(conversation_id: str) -> dict[str, Any]:
    store = get_telemetry_store()
    conv = store.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found")
    return conv.model_dump(mode="json")


@router.get("/memories", summary="List and search extracted user semantic memories")
async def list_memories(
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    tag: str | None = Query(default=None, description="Filter by memory tag"),
    category: str | None = Query(default=None, description="Filter by memory category"),
    q: str | None = Query(default=None, description="Search query in content, subject, or tags"),
    search: str | None = Query(default=None, description="Alias for search query q"),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    store = get_telemetry_store()
    items, total = store.list_memories(
        user_id=user_id,
        tag=tag,
        category=category,
        q=q,
        search=search,
        min_confidence=min_confidence,
        limit=limit,
    )
    serialized = [m.model_dump(mode="json") for m in items]
    return {
        "count": total,
        "memories": serialized,
        "items": serialized,
    }


@router.post("/memories", summary="Create or reinforce a semantic user memory")
async def create_memory(body: MemoryCreateRequest) -> dict[str, Any]:
    store = get_telemetry_store()
    mem = MemoryRecord(
        memory_id=f"mem_{uuid.uuid4().hex[:12]}",
        user_id=body.user_id or "demo",
        conversation_id=body.conversation_id,
        trajectory_id=body.trajectory_id,
        source_type="manual",
        category=body.category or "musical_preference",
        subject=body.subject or "",
        content=body.content,
        sentiment=body.sentiment or "positive",
        confidence=body.confidence,
        tags=body.tags or [],
    )
    stored = store.upsert_memory_sync(mem)
    return stored.model_dump(mode="json")


@router.delete("/memories/{memory_id}", summary="Delete a semantic user memory by ID")
async def delete_memory(memory_id: str) -> dict[str, Any]:
    store = get_telemetry_store()
    deleted = store.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")
    return {"deleted": True, "memory_id": memory_id}


@router.get("/summary", summary="Aggregate telemetry counters, token usage, and surface distribution")
async def get_telemetry_summary(
    user_id: str | None = Query(default=None, description="Optional user ID filter"),
) -> dict[str, Any]:
    store = get_telemetry_store()
    summary = store.get_summary(user_id=user_id)
    return summary.model_dump(mode="json")
