"""Dual-sink persistence store (thread-safe In-Memory + lazy Firestore) for AI Telemetry."""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any

from ..config import Settings, get_settings
from ..firebase.firestore import _guard, firestore_safe, get_client, safe_doc_id
from .models import (
    ConversationRecord,
    ConversationTurn,
    MemoryRecord,
    SessionRecord,
    TelemetrySummary,
    TrajectoryRecord,
    _utc_now,
)

COL_AI_TRAJECTORIES = "ai_trajectories"
COL_AI_SESSIONS = "ai_sessions"
COL_AI_CONVERSATIONS = "ai_conversations"
COL_AI_MEMORIES = "ai_memories"


class DualSinkTelemetryStore:
    """Thread-safe In-Memory primary store + lazy Firestore persistent dual sink."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._lock = threading.RLock()
        self._trajectories: dict[str, TrajectoryRecord] = {}
        self._sessions: dict[str, SessionRecord] = {}
        self._conversations: dict[str, ConversationRecord] = {}
        self._memories: dict[str, MemoryRecord] = {}
        self._structured_logs: list[dict[str, Any]] = []

    def _schedule_firestore_persist(self, collection: str, doc_id: str, model: Any) -> None:
        """Fire-and-forget Firestore write if an event loop is running and Firestore is enabled."""
        if not getattr(self._settings, "has_firestore", False):
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist_firestore(collection, doc_id, model))
        except RuntimeError:
            pass

    async def _persist_firestore(self, collection: str, doc_id: str, model: Any) -> bool:
        if not getattr(self._settings, "has_firestore", False):
            return False
        try:
            raw = model.model_dump(mode="python") if hasattr(model, "model_dump") else dict(model)
            doc_data = firestore_safe(raw)
        except Exception:
            return False

        async def _op() -> bool:
            client = await get_client(self._settings)
            await client.collection(collection).document(safe_doc_id(doc_id)).set(doc_data, merge=True)
            return True

        return await _guard(_op, what=f"telemetry.{collection}.set({doc_id})", default=False)

    async def _delete_firestore(self, collection: str, doc_id: str) -> bool:
        if not getattr(self._settings, "has_firestore", False):
            return False

        async def _op() -> bool:
            client = await get_client(self._settings)
            await client.collection(collection).document(safe_doc_id(doc_id)).delete()
            return True

        return await _guard(_op, what=f"telemetry.{collection}.delete({doc_id})", default=False)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def resolve_or_create_session(
        self,
        session_id: str | None = None,
        user_id: str = "demo",
        client_surface: str = "web-flutter",
        geocache_id: str | None = None,
        theme_id: str | None = None,
        genre_id: str | None = None,
        increment_turn: bool = True,
    ) -> SessionRecord:
        uid = user_id or "demo"
        with self._lock:
            sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
            existing = self._sessions.get(sid)
            if existing is not None:
                updates: dict[str, Any] = {
                    "last_active_at": _utc_now(),
                    "turn_count": existing.turn_count + (1 if increment_turn else 0),
                }
                if geocache_id is not None:
                    updates["active_geocache_id"] = geocache_id
                if theme_id is not None:
                    updates["active_theme_id"] = theme_id
                if genre_id is not None:
                    updates["active_genre_id"] = genre_id
                updated = existing.model_copy(update=updates)
                self._sessions[sid] = updated
                self._schedule_firestore_persist(COL_AI_SESSIONS, sid, updated)
                return updated
            else:
                created = SessionRecord(
                    session_id=sid,
                    user_id=uid,
                    client_surface=client_surface or "web-flutter",
                    started_at=_utc_now(),
                    last_active_at=_utc_now(),
                    turn_count=1 if increment_turn else 0,
                    active_geocache_id=geocache_id,
                    active_theme_id=theme_id,
                    active_genre_id=genre_id,
                )
                self._sessions[sid] = created
                self._schedule_firestore_persist(COL_AI_SESSIONS, sid, created)
                return created

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            return self._sessions.get(session_id)

    def _match_user(self, target_user_id: str, record_user_id: str) -> bool:
        if target_user_id in ("demo", "jpaquay"):
            return record_user_id in ("demo", "jpaquay")
        return target_user_id == record_user_id

    def list_sessions(
        self,
        user_id: str | None = None,
        surface: str | None = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> tuple[list[SessionRecord], int]:
        with self._lock:
            items = list(self._sessions.values())
        if user_id:
            items = [s for s in items if self._match_user(user_id, s.user_id)]
        if surface:
            items = [s for s in items if surface.lower() in s.client_surface.lower()]
        if active_only:
            items = [s for s in items if s.turn_count > 0]
        items.sort(key=lambda s: s.last_active_at, reverse=True)
        total = len(items)
        return items[:limit], total

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------
    def resolve_or_create_conversation(
        self,
        conversation_id: str | None = None,
        session_id: str = "",
        user_id: str = "demo",
        surface: str = "advisor",
        title: str | None = None,
    ) -> ConversationRecord:
        uid = user_id or "demo"
        with self._lock:
            cid = conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
            existing = self._conversations.get(cid)
            if existing is not None:
                updates: dict[str, Any] = {"updated_at": _utc_now()}
                if session_id and not existing.session_id:
                    updates["session_id"] = session_id
                if title:
                    updates["title"] = title
                updated = existing.model_copy(update=updates)
                self._conversations[cid] = updated
                if session_id and session_id in self._sessions:
                    sess = self._sessions[session_id]
                    if cid not in sess.conversation_ids:
                        sess.conversation_ids.append(cid)
                self._schedule_firestore_persist(COL_AI_CONVERSATIONS, cid, updated)
                return updated
            else:
                created = ConversationRecord(
                    conversation_id=cid,
                    session_id=session_id,
                    user_id=uid,
                    surface=surface,
                    title=title or f"{surface.capitalize()} Session",
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                    turns=[],
                )
                self._conversations[cid] = created
                if session_id and session_id in self._sessions:
                    sess = self._sessions[session_id]
                    if cid not in sess.conversation_ids:
                        sess.conversation_ids.append(cid)
                self._schedule_firestore_persist(COL_AI_CONVERSATIONS, cid, created)
                return created

    def append_conversation_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        spoken_summary: str | None = None,
        audio_transcript: str | None = None,
        actions_executed: list[dict[str, Any]] | None = None,
        trajectory_id: str | None = None,
    ) -> ConversationTurn:
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv is None:
                conv = self.resolve_or_create_conversation(conversation_id=conversation_id)
            turn_idx = len(conv.turns)
            turn = ConversationTurn(
                turn_id=f"turn_{uuid.uuid4().hex[:8]}",
                turn_index=turn_idx,
                role="assistant" if role == "assistant" else "user",
                timestamp=_utc_now(),
                content=content or "",
                audio_transcript=audio_transcript,
                spoken_summary=spoken_summary,
                actions_executed=actions_executed or [],
                trajectory_id=trajectory_id,
            )
            new_turns = list(conv.turns) + [turn]
            summary = conv.summary
            if role == "user" and not summary and content:
                summary = content[:100]
            updated = conv.model_copy(
                update={
                    "turns": new_turns,
                    "updated_at": _utc_now(),
                    "summary": summary,
                }
            )
            self._conversations[conversation_id] = updated
            self._schedule_firestore_persist(COL_AI_CONVERSATIONS, conversation_id, updated)
            return turn

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._lock:
            return self._conversations.get(conversation_id)

    def list_conversations(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> tuple[list[ConversationRecord], int]:
        with self._lock:
            items = list(self._conversations.values())
        if user_id:
            items = [c for c in items if self._match_user(user_id, c.user_id)]
        if session_id:
            items = [c for c in items if c.session_id == session_id]
        items.sort(key=lambda c: c.updated_at, reverse=True)
        total = len(items)
        return items[:limit], total

    # ------------------------------------------------------------------
    # Trajectories
    # ------------------------------------------------------------------
    def record_trajectory_sync(self, record: TrajectoryRecord) -> TrajectoryRecord:
        with self._lock:
            self._trajectories[record.trajectory_id] = record
            if len(self._trajectories) > 1000:
                oldest_key = min(self._trajectories, key=lambda k: self._trajectories[k].created_at)
                self._trajectories.pop(oldest_key, None)

            if record.session_id:
                if record.session_id not in self._sessions:
                    self.resolve_or_create_session(
                        session_id=record.session_id,
                        user_id=record.user_id,
                        client_surface=record.surface,
                        increment_turn=True,
                    )
                sess = self._sessions[record.session_id]
                if record.trajectory_id not in sess.trajectory_ids:
                    sess.trajectory_ids.append(record.trajectory_id)
                if record.conversation_id and record.conversation_id not in sess.conversation_ids:
                    sess.conversation_ids.append(record.conversation_id)
                sess.last_active_at = _utc_now()

        self._schedule_firestore_persist(COL_AI_TRAJECTORIES, record.trajectory_id, record)
        return record

    def save_trajectory_sync(self, record: TrajectoryRecord) -> TrajectoryRecord:
        return self.record_trajectory_sync(record)

    def get_or_create_session_sync(
        self,
        session_id: str | None = None,
        user_id: str = "demo",
        client_surface: str = "web-flutter",
    ) -> SessionRecord:
        return self.resolve_or_create_session(
            session_id=session_id,
            user_id=user_id,
            client_surface=client_surface,
            increment_turn=False,
        )

    def save_session_sync(self, session: SessionRecord) -> SessionRecord:
        with self._lock:
            self._sessions[session.session_id] = session
        self._schedule_firestore_persist(COL_AI_SESSIONS, session.session_id, session)
        return session

    async def record_trajectory(self, record: TrajectoryRecord) -> TrajectoryRecord:
        self.record_trajectory_sync(record)
        await self._persist_firestore(COL_AI_TRAJECTORIES, record.trajectory_id, record)
        return record

    def get_trajectory(self, trajectory_id: str) -> TrajectoryRecord | None:
        with self._lock:
            return self._trajectories.get(trajectory_id)

    def list_trajectories(
        self,
        user_id: str | None = None,
        surface: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        model_path: str | None = None,
        execution_path: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TrajectoryRecord], int]:
        with self._lock:
            items = list(self._trajectories.values())
        if user_id:
            items = [t for t in items if self._match_user(user_id, t.user_id)]
        if surface:
            items = [t for t in items if t.surface.lower() == surface.lower()]
        if session_id:
            items = [t for t in items if t.session_id == session_id]
        if conversation_id:
            items = [t for t in items if t.conversation_id == conversation_id]
        path_filter = execution_path or model_path
        if path_filter:
            items = [t for t in items if t.execution_path.lower() == path_filter.lower()]
        items.sort(key=lambda t: t.created_at, reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    # ------------------------------------------------------------------
    # Memories
    # ------------------------------------------------------------------
    def upsert_memory_sync(self, memory: MemoryRecord) -> MemoryRecord:
        with self._lock:
            existing: MemoryRecord | None = None
            for m in self._memories.values():
                if (
                    self._match_user(memory.user_id, m.user_id)
                    and m.subject.lower() == memory.subject.lower()
                    and m.category == memory.category
                    and m.sentiment == memory.sentiment
                ):
                    existing = m
                    break
            if existing is not None:
                updated_tags = sorted(set(existing.tags) | set(memory.tags))
                reinforced = existing.model_copy(
                    update={
                        "reinforcement_count": existing.reinforcement_count + 1,
                        "last_reinforced_at": _utc_now(),
                        "confidence": min(0.99, round(existing.confidence + 0.03, 2)),
                        "tags": updated_tags,
                        "conversation_id": memory.conversation_id or existing.conversation_id,
                        "trajectory_id": memory.trajectory_id or existing.trajectory_id,
                        "content": memory.content or existing.content,
                    }
                )
                self._memories[existing.memory_id] = reinforced
                self._schedule_firestore_persist(COL_AI_MEMORIES, reinforced.memory_id, reinforced)
                return reinforced
            else:
                self._memories[memory.memory_id] = memory
                self._schedule_firestore_persist(COL_AI_MEMORIES, memory.memory_id, memory)
                return memory

    async def upsert_memory(self, memory: MemoryRecord) -> MemoryRecord:
        stored = self.upsert_memory_sync(memory)
        await self._persist_firestore(COL_AI_MEMORIES, stored.memory_id, stored)
        return stored

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._memories.get(memory_id)

    def delete_memory(self, memory_id: str) -> bool:
        with self._lock:
            removed = self._memories.pop(memory_id, None)
        if removed is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._delete_firestore(COL_AI_MEMORIES, memory_id))
            except RuntimeError:
                pass
            return True
        return False

    def list_memories(
        self,
        user_id: str | None = None,
        tag: str | None = None,
        category: str | None = None,
        q: str | None = None,
        search: str | None = None,
        min_confidence: float | None = None,
        limit: int = 50,
    ) -> tuple[list[MemoryRecord], int]:
        with self._lock:
            items = list(self._memories.values())
        if user_id:
            items = [m for m in items if self._match_user(user_id, m.user_id)]
        if category:
            items = [m for m in items if m.category.lower() == category.lower()]
        if tag:
            tl = tag.lower()
            items = [m for m in items if any(tl in t.lower() for t in m.tags)]
        query = q or search
        if query:
            ql = query.lower()
            items = [
                m
                for m in items
                if ql in m.content.lower()
                or ql in m.subject.lower()
                or ql in m.category.lower()
                or any(ql in t.lower() for t in m.tags)
            ]
        if min_confidence is not None:
            items = [m for m in items if m.confidence >= min_confidence]
        items.sort(key=lambda m: (m.confidence, m.reinforcement_count, m.last_reinforced_at), reverse=True)
        total = len(items)
        return items[:limit], total

    # ------------------------------------------------------------------
    # Summary & Logs
    # ------------------------------------------------------------------
    def get_summary(self, user_id: str | None = None) -> TelemetrySummary:
        with self._lock:
            trajs = list(self._trajectories.values())
            sessions = list(self._sessions.values())
            convs = list(self._conversations.values())
            mems = list(self._memories.values())

        if user_id:
            trajs = [t for t in trajs if t.user_id == user_id]
            sessions = [s for s in sessions if s.user_id == user_id]
            convs = [c for c in convs if c.user_id == user_id]
            mems = [m for m in mems if m.user_id == user_id]

        total_calls = len(trajs)
        p_tokens = sum(t.token_usage.prompt_tokens for t in trajs)
        c_tokens = sum(t.token_usage.candidate_tokens for t in trajs)
        t_tokens = sum(t.token_usage.total_tokens for t in trajs)
        avg_lat = round(sum(t.latency_ms for t in trajs) / total_calls, 2) if total_calls > 0 else 0.0
        err_cnt = sum(1 for t in trajs if t.http_status >= 400 or t.error_state)

        by_surface: dict[str, int] = {
            "advisor": 0,
            "dataviz": 0,
            "forge": 0,
            "a2ui": 0,
            "mcp": 0,
        }
        for t in trajs:
            key = t.surface.lower()
            by_surface[key] = by_surface.get(key, 0) + 1

        by_path: dict[str, int] = {
            "vertex-ai": 0,
            "semantic-fallback": 0,
            "deterministic-fallback": 0,
        }
        for t in trajs:
            pkey = t.execution_path.lower()
            by_path[pkey] = by_path.get(pkey, 0) + 1

        active_sess = sum(1 for s in sessions if s.turn_count > 0)

        return TelemetrySummary(
            total_ai_calls=total_calls,
            token_usage={
                "prompt_tokens": p_tokens,
                "candidate_tokens": c_tokens,
                "candidates_tokens": c_tokens,
                "total_tokens": t_tokens,
            },
            active_sessions=active_sess,
            total_sessions=len(sessions),
            total_conversations=len(convs),
            stored_memories=len(mems),
            avg_latency_ms=avg_lat,
            trajectory_counts_by_surface=by_surface,
            trajectory_counts_by_path=by_path,
            error_count=err_cnt,
        )

    def append_structured_log(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._structured_logs.append(entry)
            if len(self._structured_logs) > 500:
                self._structured_logs = self._structured_logs[-500:]

    def get_recent_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._structured_logs[-limit:]))


_TELEMETRY_STORE_SINGLETON: DualSinkTelemetryStore | None = None
_SINGLETON_LOCK = threading.RLock()


def get_telemetry_store(settings: Settings | None = None) -> DualSinkTelemetryStore:
    """Return process-wide DualSinkTelemetryStore singleton."""
    global _TELEMETRY_STORE_SINGLETON
    with _SINGLETON_LOCK:
        if _TELEMETRY_STORE_SINGLETON is None:
            _TELEMETRY_STORE_SINGLETON = DualSinkTelemetryStore(settings)
        return _TELEMETRY_STORE_SINGLETON


def reset_telemetry_store(settings: Settings | None = None) -> DualSinkTelemetryStore:
    """Reset the telemetry store singleton (useful for isolated tests)."""
    global _TELEMETRY_STORE_SINGLETON
    with _SINGLETON_LOCK:
        _TELEMETRY_STORE_SINGLETON = DualSinkTelemetryStore(settings)
        return _TELEMETRY_STORE_SINGLETON
