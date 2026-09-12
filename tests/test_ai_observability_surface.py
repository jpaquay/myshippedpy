"""Comprehensive E2E Requirement-Driven Test Suite for BaroGroove AI Observability Surface.

Covers Requirements R1–R5 and Features F1–F16 across 4 progressive verification tiers:
- Tier 1: Category-Partition Functional Requirement Coverage (R1, R2, R3, R4, R5)
- Tier 2: Boundary Value Analysis & Negative/Adversarial Corner Cases
- Tier 3: Pairwise Combinatorial & Cross-Surface Integration Testing
- Tier 4: Real-World End-to-End Listener Workload & A2UI Inspector Verification

All tests execute deterministically offline via FastAPI TestClient against dual-sink
in-memory/Firestore telemetry stores and controlled Vertex AI mocks.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


# ==============================================================================
# Helper Utilities & Opaque-Box Extractors
# ==============================================================================


def _extract_list(data: Any, *candidate_keys: str) -> list[dict[str, Any]]:
    """Extract a list of records from either a top-level list or a JSON envelope."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in candidate_keys:
            if k in data and isinstance(data[k], list):
                return data[k]
        for k in ("items", "trajectories", "sessions", "conversations", "memories", "entries", "results", "data"):
            if k in data and isinstance(data[k], list):
                return data[k]
    raise AssertionError(f"Unable to extract list from response payload: {type(data)} -> {data}")


def _extract_tool_names(traj: dict[str, Any]) -> set[str]:
    """Extract all tool identifiers from a TrajectoryRecord's tool_steps or action badges."""
    tools: set[str] = set()
    for field in ("tool_steps", "actions_executed", "steps", "tool_calls", "tool_badges", "badges"):
        items = traj.get(field)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    t_name = item.get("tool_name") or item.get("tool") or item.get("name") or item.get("action")
                    if t_name:
                        tools.add(str(t_name))
                elif isinstance(item, str):
                    tools.add(item)
    return tools


def _get_token_usage(traj: dict[str, Any]) -> dict[str, Any]:
    """Return normalized token usage dictionary from TrajectoryRecord."""
    tu = traj.get("token_usage")
    if isinstance(tu, dict):
        return tu
    return {
        "prompt_tokens": traj.get("prompt_tokens", 0),
        "candidate_tokens": traj.get("candidate_tokens", traj.get("candidates_tokens", 0)),
        "total_tokens": traj.get("total_tokens", 0),
        "is_estimated": traj.get("is_estimated", True),
    }


def _get_is_estimated(traj: dict[str, Any]) -> bool:
    """Return boolean is_estimated flag from TrajectoryRecord or its nested token_usage."""
    tu = traj.get("token_usage")
    if isinstance(tu, dict) and "is_estimated" in tu:
        return bool(tu["is_estimated"])
    if "is_estimated" in traj:
        return bool(traj["is_estimated"])
    return False


@pytest.fixture(autouse=True)
def _clean_telemetry_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the in-memory telemetry store and pin Vertex token getters offline before each test."""
    try:
        monkeypatch.setattr("backend.app.advisor.engine._get_vertex_token", lambda: (None, "test-project"))
    except Exception:
        pass
    try:
        monkeypatch.setattr("backend.app.dataviz.engine._get_vertex_token", lambda: (None, "test-project"))
    except Exception:
        pass
    try:
        from backend.app.telemetry.store import get_telemetry_store, reset_telemetry_store

        reset_telemetry_store()
    except ImportError:
        try:
            from backend.app.telemetry.store import get_telemetry_store

            store = get_telemetry_store()
            if hasattr(store, "clear"):
                store.clear()
            elif hasattr(store, "reset"):
                store.reset()
        except ImportError:
            pass


@pytest.fixture
def client() -> TestClient:
    """Create a fresh TestClient with MCP mounted for full-surface testing."""
    app = create_app()
    try:
        from backend.app.mcp.server import mount_mcp

        mount_mcp(app)
    except Exception:
        pass
    return TestClient(app)


# ==============================================================================
# TIER 1 — Requirement R1: Full-Surface Trajectory Capture
# ==============================================================================


def test_r1_advisor_live_records_full_trajectory_and_tool_badges(client: TestClient) -> None:
    """R1: POST /api/advisor/live records a complete TrajectoryRecord with tool badges and W3C/GCP trace."""
    resp = client.post(
        "/api/advisor/live",
        json={
            "prompt": "Teleport to Shimokitazawa in Tokyo and forge a late-night trip-hop set with Massive Attack.",
            "auto_forge": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_geocache"]["id"] == "shimokitazawa_tokyo"

    traj_resp = client.get("/api/telemetry/trajectories", params={"surface": "advisor"})
    assert traj_resp.status_code == 200
    trajectories = _extract_list(traj_resp.json(), "trajectories")
    assert len(trajectories) >= 1

    # Locate the advisor live trajectory
    traj = next((t for t in trajectories if "Shimokitazawa" in (t.get("user_prompt") or "")), trajectories[0])

    assert traj["surface"] == "advisor"
    assert isinstance(traj["trajectory_id"], str) and len(traj["trajectory_id"]) >= 5
    assert isinstance(traj["session_id"], str) and len(traj["session_id"]) >= 5
    assert isinstance(traj["conversation_id"], str) and len(traj["conversation_id"]) >= 5
    assert float(traj["latency_ms"]) >= 0.0

    # Verify W3C 32-char hex trace_id, 16-char hex span_id, and GCP trace format
    assert re.match(r"^[0-9a-f]{32}$", traj["trace_id"]), f"Invalid trace_id: {traj.get('trace_id')}"
    assert re.match(r"^[0-9a-f]{16}$", traj["span_id"]), f"Invalid span_id: {traj.get('span_id')}"
    assert re.match(r"^projects/[^/]+/traces/[0-9a-f]{32}$", traj["gcp_trace"]), (
        f"Invalid gcp_trace: {traj.get('gcp_trace')}"
    )

    assert traj["requested_model"] == "gemini-2.5-flash"
    assert traj["execution_path"] in {"vertex-ai", "semantic-fallback", "deterministic-fallback"}

    # Verify token usage metrics
    tu = _get_token_usage(traj)
    assert int(tu["prompt_tokens"]) > 0
    assert int(tu["candidate_tokens"]) > 0
    assert int(tu["total_tokens"]) > 0
    assert int(tu["total_tokens"]) == int(tu["prompt_tokens"]) + int(tu["candidate_tokens"])

    # Verify prompts & parsed plan
    assert isinstance(traj["system_instruction"], str) and len(traj["system_instruction"]) > 20
    assert "Shimokitazawa" in traj["user_prompt"]
    assert isinstance(traj["parsed_plan"], dict) and len(traj["parsed_plan"]) > 0

    # Verify autonomous tool step badges
    recorded_tools = _extract_tool_names(traj)
    expected_tools = {"teleport_geocache", "select_sonic_parameters", "seed_from_almanac", "execute_forge"}
    assert expected_tools.issubset(recorded_tools), (
        f"Missing expected advisor tools. Found: {recorded_tools}, expected subset: {expected_tools}"
    )


def test_r1_advisor_suggestions_records_trajectory(client: TestClient) -> None:
    """R1: GET /api/advisor/suggestions records a TrajectoryRecord with surface='advisor'."""
    resp = client.get("/api/advisor/suggestions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    traj_resp = client.get("/api/telemetry/trajectories", params={"surface": "advisor"})
    assert traj_resp.status_code == 200
    trajectories = _extract_list(traj_resp.json(), "trajectories")
    assert len(trajectories) >= 1
    assert any(t["surface"] == "advisor" for t in trajectories)


def test_r1_dataviz_qna_records_trajectory_with_highlight_section_and_tokens(client: TestClient) -> None:
    """R1: POST /api/dataviz/qna records a TrajectoryRecord with highlight_section tool step and token usage."""
    resp = client.post(
        "/api/dataviz/qna",
        json={
            "question": "What do I listen to when barometric pressure drops below 1005 hPa?",
            "voice_mode": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["highlight_section"] == "pressure_vs_bpm"

    traj_resp = client.get("/api/telemetry/trajectories", params={"surface": "dataviz"})
    assert traj_resp.status_code == 200
    trajectories = _extract_list(traj_resp.json(), "trajectories")
    assert len(trajectories) >= 1

    traj = trajectories[0]
    assert traj["surface"] == "dataviz"

    tu = _get_token_usage(traj)
    assert int(tu["prompt_tokens"]) > 0
    assert int(tu["candidate_tokens"]) > 0
    assert int(tu["total_tokens"]) > 0

    # Verify highlight_section tool step badge or parsed plan metadata
    tools = _extract_tool_names(traj)
    has_highlight_badge = (
        "highlight_section" in tools
        or any("highlight" in t for t in tools)
        or traj.get("parsed_plan", {}).get("highlight_section") == "pressure_vs_bpm"
    )
    assert has_highlight_badge, f"Expected highlight_section badge in trajectory: {traj}"


def test_r1_forge_and_explain_record_trajectories_and_return_trajectory_id(client: TestClient) -> None:
    """R1: POST /api/forge and POST /api/forge/explain record TrajectoryRecords (surface='forge') and return trajectory_id."""
    forge_resp = client.post(
        "/api/forge",
        json={
            "lat": 50.8503,
            "lon": 4.3517,
            "theme_id": "blue_hour",
            "genre_id": "trip-hop",
        },
    )
    assert forge_resp.status_code == 200
    forge_data = forge_resp.json()

    forge_traj_id = (
        forge_data.get("trajectory_id")
        or forge_data.get("playlist", {}).get("trajectory_id")
        or forge_resp.headers.get("X-Trajectory-Id")
    )
    assert forge_traj_id, f"POST /api/forge did not return trajectory_id in body or header: {forge_data.keys()}"

    # Call POST /api/forge/explain
    playlist_payload = forge_data["playlist"]
    explain_resp = client.post("/api/forge/explain", json=playlist_payload)
    assert explain_resp.status_code == 200
    explain_data = explain_resp.json()

    explain_traj_id = (
        explain_data.get("trajectory_id")
        or explain_resp.headers.get("X-Trajectory-Id")
    )
    assert explain_traj_id, f"POST /api/forge/explain did not return trajectory_id: {explain_data.keys()}"

    # Verify both trajectories are persisted under surface='forge'
    traj_resp = client.get("/api/telemetry/trajectories", params={"surface": "forge"})
    assert traj_resp.status_code == 200
    forge_trajs = _extract_list(traj_resp.json(), "trajectories")
    recorded_ids = {t["trajectory_id"] for t in forge_trajs}
    assert forge_traj_id in recorded_ids
    assert explain_traj_id in recorded_ids


def test_r1_a2ui_surfaces_record_trajectories(client: TestClient) -> None:
    """R1: /api/surfaces/sky, /themes, /telemetry, and POST /action record TrajectoryRecords (surface='a2ui')."""
    r_sky = client.get("/api/surfaces/sky", params={"lat": 50.8503, "lon": 4.3517})
    assert r_sky.status_code == 200

    r_themes = client.get("/api/surfaces/themes")
    assert r_themes.status_code == 200

    r_telemetry = client.get("/api/surfaces/telemetry")
    assert r_telemetry.status_code == 200

    r_action = client.post(
        "/api/surfaces/action",
        json={
            "action": "selectTheme",
            "surfaceId": "themes",
            "args": {"themeId": "blue_hour"},
        },
    )
    assert r_action.status_code == 200

    traj_resp = client.get("/api/telemetry/trajectories", params={"surface": "a2ui"})
    assert traj_resp.status_code == 200
    a2ui_trajs = _extract_list(traj_resp.json(), "trajectories")
    assert len(a2ui_trajs) >= 4, f"Expected at least 4 a2ui trajectories, got {len(a2ui_trajs)}"


def test_r1_mcp_server_tool_invocations_record_trajectories(client: TestClient) -> None:
    """R1: MCP tool invocations (get_sky_vector, list_themes, forge_playlist, explain_playlist) record TrajectoryRecords (surface='mcp')."""
    # Initialize MCP session over streamable HTTP if /mcp is mounted
    mcp_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": "Bearer dev:test-listener",
    }
    init_resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "e2e-test-suite", "version": "1.0"},
            },
        },
        headers=mcp_headers,
    )

    if init_resp.status_code == 200:
        # 1. get_sky_vector
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_sky_vector", "arguments": {"lat": 50.8503, "lon": 4.3517, "label": "Brussels"}},
            },
            headers=mcp_headers,
        )
        # 2. list_themes
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_themes", "arguments": {}},
            },
            headers=mcp_headers,
        )
        # 3. forge_playlist
        forge_mcp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "forge_playlist",
                    "arguments": {"lat": 50.8503, "lon": 4.3517, "theme": "blue_hour", "length": 18},
                },
            },
            headers=mcp_headers,
        )
        # 4. explain_playlist
        # First forge a playlist via REST to get a guaranteed playlist ID in almanac/recent
        pl_resp = client.post("/api/forge", json={"lat": 50.8503, "lon": 4.3517, "theme_id": "blue_hour"})
        pl_obj = pl_resp.json()["playlist"]
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "explain_playlist",
                    "arguments": {"playlist": pl_obj},
                },
            },
            headers=mcp_headers,
        )
    else:
        # Direct invocation of MCP tool runners if /mcp route is not mounted
        import asyncio
        from backend.app.mcp.manifest import (
            ExplainPlaylistInput,
            ForgePlaylistInput,
            GetSkyVectorInput,
            ListThemesInput,
        )
        from backend.app.mcp.server import (
            _run_explain_playlist,
            _run_forge_playlist,
            _run_get_sky_vector,
            _run_list_themes,
        )

        pl_resp = client.post("/api/forge", json={"lat": 50.8503, "lon": 4.3517, "theme_id": "blue_hour"})
        pl_obj = pl_resp.json()["playlist"]

        asyncio.run(_run_get_sky_vector(GetSkyVectorInput(lat=50.8503, lon=4.3517, label="Brussels")))
        asyncio.run(_run_list_themes(ListThemesInput()))
        asyncio.run(_run_forge_playlist(ForgePlaylistInput(lat=50.8503, lon=4.3517, theme="blue_hour", length=18)))
        asyncio.run(_run_explain_playlist(ExplainPlaylistInput(playlist=pl_obj)))

    traj_resp = client.get("/api/telemetry/trajectories", params={"surface": "mcp"})
    assert traj_resp.status_code == 200
    mcp_trajs = _extract_list(traj_resp.json(), "trajectories")
    assert len(mcp_trajs) >= 4, f"Expected at least 4 MCP trajectories, got {len(mcp_trajs)}"


# ==============================================================================
# TIER 1 — Requirement R2: Stateful Multi-Turn Conversations & User Sessions
# ==============================================================================


def test_r2_omitting_session_and_conversation_id_creates_new_records(client: TestClient) -> None:
    """R2: Omitting session_id and conversation_id automatically creates SessionRecord and ConversationRecord."""
    resp = client.post(
        "/api/advisor/live",
        json={"prompt": "Teleport to Wall Poetry Grandi in Reykjavík and play Nordic ambient."},
    )
    assert resp.status_code == 200
    data = resp.json()

    session_id = data.get("session_id")
    conversation_id = data.get("conversation_id")
    assert session_id, f"Expected session_id in AdvisorLiveResponse: {data.keys()}"
    assert conversation_id, f"Expected conversation_id in AdvisorLiveResponse: {data.keys()}"

    # Verify SessionRecord exists via GET /api/telemetry/sessions/{session_id}
    sess_resp = client.get(f"/api/telemetry/sessions/{session_id}")
    assert sess_resp.status_code == 200
    sess_data = sess_resp.json()
    assert sess_data["session_id"] == session_id
    assert int(sess_data["turn_count"]) >= 1

    # Verify ConversationRecord exists via GET /api/telemetry/conversations/{conversation_id}
    conv_resp = client.get(f"/api/telemetry/conversations/{conversation_id}")
    assert conv_resp.status_code == 200
    conv_data = conv_resp.json()
    assert conv_data["conversation_id"] == conversation_id
    turns = conv_data.get("turns") or []
    assert len(turns) >= 2  # user turn + assistant turn


def test_r2_sequential_multi_turn_conversation_maintains_state_and_injects_context(client: TestClient) -> None:
    """R2: Sequential turns with same session_id & conversation_id increment turn_count, append turns, and inject context into system_instruction."""
    # Turn 1
    r1 = client.post(
        "/api/advisor/live",
        json={
            "prompt": "Teleport to Shimokitazawa Tokyo and play trip-hop with Massive Attack.",
            "auto_forge": True,
        },
    )
    assert r1.status_code == 200
    d1 = r1.json()
    session_id = d1["session_id"]
    conversation_id = d1["conversation_id"]

    # Turn 2 with same session_id and conversation_id
    r2 = client.post(
        "/api/advisor/live",
        json={
            "prompt": "Now shift the mood to Blue Hour with Portishead.",
            "session_id": session_id,
            "conversation_id": conversation_id,
            "auto_forge": True,
        },
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["session_id"] == session_id
    assert d2["conversation_id"] == conversation_id

    # Verify SessionRecord turn_count incremented
    sess_resp = client.get(f"/api/telemetry/sessions/{session_id}")
    assert sess_resp.status_code == 200
    assert int(sess_resp.json()["turn_count"]) >= 2

    # Verify ConversationRecord has ordered user/assistant turns with trajectory_id links
    conv_resp = client.get(f"/api/telemetry/conversations/{conversation_id}")
    assert conv_resp.status_code == 200
    turns = conv_resp.json()["turns"]
    assert len(turns) >= 4
    roles = [t["role"] for t in turns]
    assert roles[:4] == ["user", "assistant", "user", "assistant"]
    assert all(t.get("trajectory_id") for t in turns if t["role"] == "assistant")

    # Verify Turn 2's TrajectoryRecord.system_instruction contains prior turn context from Turn 1
    turn2_traj_id = d2.get("trajectory_id") or turns[-1].get("trajectory_id")
    assert turn2_traj_id
    traj_resp = client.get(f"/api/telemetry/trajectories/{turn2_traj_id}")
    assert traj_resp.status_code == 200
    turn2_traj = traj_resp.json()
    sys_inst = turn2_traj["system_instruction"]
    assert any(kw in sys_inst for kw in ["Shimokitazawa", "Massive Attack", "trip-hop", "Tokyo"]), (
        f"Turn 1 context was not injected into Turn 2 system_instruction: {sys_inst}"
    )


# ==============================================================================
# TIER 1 — Requirement R3: Semantic Memory Lifecycle & Almanac Integration
# ==============================================================================


def test_r3_conversational_turn_extracts_and_persists_semantic_memories(client: TestClient) -> None:
    """R3: Conversational turn expressing preferences automatically extracts and persists MemoryRecord items."""
    resp = client.post(
        "/api/advisor/live",
        json={
            "prompt": "I love dark rainy low-pressure trip-hop in Shimokitazawa Tokyo with Massive Attack",
            "auto_forge": False,
        },
    )
    assert resp.status_code == 200

    mem_resp = client.get("/api/telemetry/memories")
    assert mem_resp.status_code == 200
    memories = _extract_list(mem_resp.json(), "memories")
    assert len(memories) >= 1

    combined_content = " ".join(
        f"{m.get('content', '')} {' '.join(m.get('tags', []))}" for m in memories
    ).lower()
    assert any(kw in combined_content for kw in ["massive attack", "trip-hop", "shimokitazawa", "tokyo", "rain"]), (
        f"Expected extracted preference in memories: {memories}"
    )


def test_r3_almanac_feedback_creates_memories_with_almanac_feedback_source(client: TestClient) -> None:
    """R3: POST /api/almanac/feedback (loved and skipped) creates MemoryRecord items with source_type='almanac_feedback'."""
    r_loved = client.post(
        "/api/almanac/feedback",
        json={
            "playlist_id": "pl_test_loved_01",
            "track_key": "Massive Attack - Teardrop",
            "signal": "loved",
        },
    )
    assert r_loved.status_code == 200

    r_skipped = client.post(
        "/api/almanac/feedback",
        json={
            "playlist_id": "pl_test_skip_01",
            "track_key": "Noisy Pop - Commercial Track",
            "signal": "skipped",
        },
    )
    assert r_skipped.status_code == 200

    mem_resp = client.get("/api/telemetry/memories")
    assert mem_resp.status_code == 200
    memories = _extract_list(mem_resp.json(), "memories")

    feedback_memories = [m for m in memories if m.get("source_type") == "almanac_feedback"]
    assert len(feedback_memories) >= 2, f"Expected at least 2 almanac_feedback memories, got: {memories}"

    loved_mem = next((m for m in feedback_memories if "Teardrop" in m.get("content", "")), None)
    skipped_mem = next((m for m in feedback_memories if "Commercial Track" in m.get("content", "")), None)
    assert loved_mem is not None
    assert skipped_mem is not None


def test_r3_extracted_memories_injected_into_subsequent_ai_system_prompt(client: TestClient) -> None:
    """R3: Extracted semantic memories are surfaced into TrajectoryRecord.system_instruction of subsequent AI calls."""
    # Create a distinctive semantic memory for the user
    create_resp = client.post(
        "/api/telemetry/memories",
        json={
            "user_id": "demo",
            "content": "Listener adores Boards of Canada analog synths during 994 hPa cyclonic storms",
            "category": "artist_affinity",
            "tags": ["boards-of-canada", "storm"],
            "confidence": 0.95,
        },
    )
    assert create_resp.status_code in (200, 201)

    # Trigger a subsequent AI advisor turn
    adv_resp = client.post(
        "/api/advisor/live",
        json={"prompt": "What music should I play right now?", "auto_forge": False},
    )
    assert adv_resp.status_code == 200
    adv_data = adv_resp.json()

    traj_id = adv_data.get("trajectory_id")
    if traj_id:
        traj = client.get(f"/api/telemetry/trajectories/{traj_id}").json()
    else:
        trajs = _extract_list(client.get("/api/telemetry/trajectories", params={"surface": "advisor"}).json(), "trajectories")
        traj = trajs[0]

    assert "Boards of Canada" in traj["system_instruction"] or "994 hPa" in traj["system_instruction"], (
        f"Semantic memory was not injected into system_instruction: {traj['system_instruction']}"
    )


def test_r3_manual_memory_crud_creation_deduplication_and_deletion(client: TestClient) -> None:
    """R3: Manual memory CRUD: POST creation, deduplication reinforcement count increment, and DELETE removal."""
    payload = {
        "user_id": "demo",
        "content": "Prefers Basic Channel dub techno vinyl mixes at midnight",
        "category": "genre_affinity",
        "tags": ["dub-techno", "basic-channel"],
        "confidence": 0.80,
    }
    r1 = client.post("/api/telemetry/memories", json=payload)
    assert r1.status_code in (200, 201)
    m1 = r1.json()
    mem_id = m1["memory_id"]
    assert int(m1.get("reinforcement_count", 1)) == 1

    # Post identical memory content again -> should deduplicate and increment reinforcement_count
    r2 = client.post("/api/telemetry/memories", json=payload)
    assert r2.status_code in (200, 201)
    m2 = r2.json()
    assert m2["memory_id"] == mem_id
    assert int(m2["reinforcement_count"]) >= 2

    # Delete memory
    del_resp = client.delete(f"/api/telemetry/memories/{mem_id}")
    assert del_resp.status_code in (200, 204)

    # Verify memory is gone
    list_after = _extract_list(client.get("/api/telemetry/memories").json(), "memories")
    assert all(m["memory_id"] != mem_id for m in list_after)


def test_r3_dislike_does_not_trigger_positive_like_and_canonical_landmark_id_preserved(client: TestClient) -> None:
    """R3 Regression: Dislike prompt does not extract contradictory sentiment_like and preserves canonical street-art landmark ID."""
    uid = "verify_user_r3_regression"
    r1 = client.post(
        "/api/advisor/live",
        json={
            "prompt": "I dislike harsh noise at wall_poetry_reykjavik",
            "current_geocache_id": "wall_poetry_reykjavik",
            "auto_forge": False,
            "user_id": uid,
        },
    )
    assert r1.status_code == 200
    d1 = r1.json()
    session_id = d1.get("session_id")
    conversation_id = d1.get("conversation_id")

    mems = _extract_list(client.get(f"/api/telemetry/memories?user_id={uid}").json(), "memories")
    categories = [m["category"] for m in mems]
    subjects = [m["subject"] for m in mems]

    assert "sentiment_dislike" in categories, f"Missing sentiment_dislike in {categories}"
    assert "sentiment_like" not in categories, f"Contradictory sentiment_like extracted from dislike prompt: {categories}"
    assert "landmark:wall_poetry_reykjavik" in subjects, f"Expected landmark:wall_poetry_reykjavik in {subjects}"

    # Trigger subsequent turn and inspect TrajectoryRecord.system_instruction
    r2 = client.post(
        "/api/advisor/live",
        json={
            "prompt": "What music would you recommend next?",
            "session_id": session_id,
            "conversation_id": conversation_id,
            "auto_forge": False,
            "user_id": uid,
        },
    )
    assert r2.status_code == 200
    traj_id2 = r2.json().get("trajectory_id")
    assert traj_id2
    traj2 = client.get(f"/api/telemetry/trajectories/{traj_id2}").json()
    sys_inst = traj2["system_instruction"]

    assert "wall_poetry_reykjavik" in sys_inst, f"Expected wall_poetry_reykjavik in system_instruction: {sys_inst}"
    assert "Explicitly likes: I dislike" not in sys_inst, (
        f"Contradictory 'Explicitly likes: I dislike' found in system_instruction: {sys_inst}"
    )


# ==============================================================================
# TIER 1 — Requirement R4: Dual-Sink Persistence & GCP Observability Logging
# ==============================================================================


def test_r4_w3c_traceparent_and_cloud_trace_context_header_propagation(client: TestClient) -> None:
    """R4: W3C traceparent and GCP X-Cloud-Trace-Context propagate into TrajectoryRecord and HTTP response headers."""
    w3c_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    w3c_span_id = "00f067aa0ba902b7"
    traceparent_hdr = f"00-{w3c_trace_id}-{w3c_span_id}-01"

    r1 = client.post(
        "/api/advisor/live",
        json={"prompt": "Test W3C traceparent propagation", "auto_forge": False},
        headers={"traceparent": traceparent_hdr},
    )
    assert r1.status_code == 200
    assert w3c_trace_id in (r1.headers.get("traceparent", "") + r1.headers.get("x-cloud-trace-context", ""))

    traj_id = r1.json().get("trajectory_id")
    traj1 = client.get(f"/api/telemetry/trajectories/{traj_id}").json()
    assert traj1["trace_id"] == w3c_trace_id
    assert traj1["span_id"] == w3c_span_id
    assert traj1["gcp_trace"].endswith(f"/traces/{w3c_trace_id}")

    # Test GCP X-Cloud-Trace-Context header propagation
    gcp_trace_id = "8899aabbccddeeff0011223344556677"
    r2 = client.post(
        "/api/advisor/live",
        json={"prompt": "Test GCP X-Cloud-Trace-Context propagation", "auto_forge": False},
        headers={"X-Cloud-Trace-Context": f"{gcp_trace_id}/12345;o=1"},
    )
    assert r2.status_code == 200
    traj_id2 = r2.json().get("trajectory_id")
    traj2 = client.get(f"/api/telemetry/trajectories/{traj_id2}").json()
    assert traj2["trace_id"] == gcp_trace_id


def test_r4_gcp_antigravity_observability_structured_json_logging(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """R4: Structured JSON log emission on logger 'barogroove.telemetry' adheres to gcp-antigravity-observability schema."""
    from backend.app.telemetry.tracing import GCPJSONFormatter

    formatter = GCPJSONFormatter(project_id="netdev-firebase")
    with caplog.at_level(logging.INFO, logger="barogroove.telemetry"):
        resp = client.post(
            "/api/advisor/live",
            json={"prompt": "Verify structured GCP observability JSON logging", "auto_forge": False},
        )
        assert resp.status_code == 200

    telemetry_records = [r for r in caplog.records if r.name == "barogroove.telemetry" or hasattr(r, "telemetry")]
    assert len(telemetry_records) >= 1, "No log records emitted on logger 'barogroove.telemetry'"

    formatted_json_str = formatter.format(telemetry_records[-1])
    parsed = json.loads(formatted_json_str)

    # Verify top-level required GCP keys
    assert parsed["severity"] in {"INFO", "WARNING", "ERROR"}
    assert isinstance(parsed["message"], str) and len(parsed["message"]) > 0
    assert "time" in parsed
    assert re.match(r"^projects/[^/]+/traces/[0-9a-f]{32}$", parsed["logging.googleapis.com/trace"])
    assert re.match(r"^[0-9a-f]{16}$", parsed["logging.googleapis.com/spanId"])

    source_loc = parsed["logging.googleapis.com/sourceLocation"]
    assert isinstance(source_loc, dict)
    assert "file" in source_loc and "line" in source_loc and "function" in source_loc

    # Verify nested telemetry object
    tel = parsed["telemetry"]
    assert isinstance(tel, dict)
    assert "trajectory_id" in tel
    assert "session_id" in tel
    assert float(tel["latency_ms"]) >= 0.0
    assert float(tel["turn_latency_sec"]) >= 0.0
    assert "token_usage" in tel
    assert int(tel["token_usage"]["prompt_tokens"]) > 0
    assert int(tel["token_usage"]["candidate_tokens"]) > 0
    assert int(tel["token_usage"]["total_tokens"]) > 0


def test_r4_vertex_ai_mocked_path_exact_token_usage(client: TestClient) -> None:
    """R4: Mocking Vertex AI HTTP response with usageMetadata records execution_path='vertex-ai', is_estimated=False, and exact tokens 123/45/168."""
    fake_vertex_plan = {
        "transcript": "Teleport to Shimokitazawa",
        "geocache_id": "shimokitazawa_tokyo",
        "theme_id": "blue_hour",
        "genre_id": "trip-hop",
        "scrobble_ids": [],
        "should_forge": False,
        "spoken_summary": "Teleporting to Tokyo Blue Hour.",
        "reply_text": "Detailed Tokyo commentary.",
    }
    fake_http_response_json = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps(fake_vertex_plan)}]
                }
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 123,
            "candidatesTokenCount": 45,
            "totalTokenCount": 168,
        },
    }

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_http_response_json
    mock_resp.text = json.dumps(fake_http_response_json)

    with (
        patch("backend.app.advisor.engine._get_vertex_token", return_value=("fake-vertex-token", "test-project")),
        patch("httpx.Client.post", return_value=mock_resp),
    ):
        resp = client.post(
            "/api/advisor/live",
            json={"prompt": "Teleport to Shimokitazawa", "auto_forge": False},
        )
        assert resp.status_code == 200
        traj_id = resp.json().get("trajectory_id")

    traj_resp = client.get(f"/api/telemetry/trajectories/{traj_id}")
    assert traj_resp.status_code == 200
    traj = traj_resp.json()

    assert traj["execution_path"] == "vertex-ai"
    assert _get_is_estimated(traj) is False
    tu = _get_token_usage(traj)
    assert int(tu["prompt_tokens"]) == 123
    assert int(tu["candidate_tokens"]) == 45
    assert int(tu["total_tokens"]) == 168


def test_r4_deterministic_semantic_fallback_path_estimated_tokens(client: TestClient) -> None:
    """R4: Offline fallback path records execution_path in {'semantic-fallback', 'deterministic-fallback'} and is_estimated=True."""
    resp = client.post(
        "/api/advisor/live",
        json={"prompt": "Fallback token estimation check", "auto_forge": False},
    )
    assert resp.status_code == 200
    traj_id = resp.json().get("trajectory_id")

    traj = client.get(f"/api/telemetry/trajectories/{traj_id}").json()
    assert traj["execution_path"] in {"semantic-fallback", "deterministic-fallback"}
    assert _get_is_estimated(traj) is True
    tu = _get_token_usage(traj)
    assert int(tu["prompt_tokens"]) > 0
    assert int(tu["candidate_tokens"]) > 0
    assert int(tu["total_tokens"]) > 0


# ==============================================================================
# TIER 1 — Requirement R5: REST Inspection API & A2UI Surface Contracts
# ==============================================================================


def test_r5_get_trajectories_filtering_and_detail_endpoint(client: TestClient) -> None:
    """R5: GET /api/telemetry/trajectories supports filtering by user_id, surface, session_id, and execution_path."""
    r_adv = client.post(
        "/api/advisor/live",
        json={"prompt": "Filter test advisor call", "session_id": "sess_filter_test", "auto_forge": False},
    )
    assert r_adv.status_code == 200
    adv_traj_id = r_adv.json()["trajectory_id"]

    r_dv = client.post(
        "/api/dataviz/qna",
        json={"question": "What happens below 1005 hPa?", "session_id": "sess_filter_test"},
    )
    assert r_dv.status_code == 200

    # Filter by surface='advisor'
    list_adv = _extract_list(
        client.get("/api/telemetry/trajectories", params={"surface": "advisor"}).json(),
        "trajectories",
    )
    assert all(t["surface"] == "advisor" for t in list_adv)
    assert any(t["trajectory_id"] == adv_traj_id for t in list_adv)

    # Filter by session_id='sess_filter_test'
    list_sess = _extract_list(
        client.get("/api/telemetry/trajectories", params={"session_id": "sess_filter_test"}).json(),
        "trajectories",
    )
    assert len(list_sess) >= 2
    assert all(t["session_id"] == "sess_filter_test" for t in list_sess)

    # Filter by execution_path
    list_path = _extract_list(
        client.get("/api/telemetry/trajectories", params={"execution_path": "semantic-fallback"}).json(),
        "trajectories",
    )
    assert all(t["execution_path"] == "semantic-fallback" for t in list_path)

    # Detail endpoint GET /api/telemetry/trajectories/{id}
    detail_resp = client.get(f"/api/telemetry/trajectories/{adv_traj_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["trajectory_id"] == adv_traj_id


def test_r5_get_sessions_and_conversations_and_memories_filtering(client: TestClient) -> None:
    """R5: GET /api/telemetry/sessions, /conversations, and /memories (filtering by tag, category, search query)."""
    r = client.post(
        "/api/advisor/live",
        json={"prompt": "Create session and conversation for R5 inspection", "auto_forge": False},
    )
    assert r.status_code == 200
    sess_id = r.json()["session_id"]
    conv_id = r.json()["conversation_id"]

    # Sessions list & detail
    sessions = _extract_list(client.get("/api/telemetry/sessions").json(), "sessions")
    assert any(s["session_id"] == sess_id for s in sessions)
    assert client.get(f"/api/telemetry/sessions/{sess_id}").status_code == 200

    # Conversations list & detail
    convs = _extract_list(client.get("/api/telemetry/conversations").json(), "conversations")
    assert any(c["conversation_id"] == conv_id for c in convs)
    assert client.get(f"/api/telemetry/conversations/{conv_id}").status_code == 200

    # Seed distinct memories for tag, category, and query filtering
    client.post(
        "/api/telemetry/memories",
        json={
            "content": "Loves Shibuya jazz bars on rainy nights",
            "category": "location_affinity",
            "tags": ["shibuya", "jazz"],
        },
    )
    client.post(
        "/api/telemetry/memories",
        json={
            "content": "Dislikes harsh industrial noise at dawn",
            "category": "sentiment_dislike",
            "tags": ["industrial", "dawn"],
        },
    )

    by_tag = _extract_list(client.get("/api/telemetry/memories", params={"tag": "shibuya"}).json(), "memories")
    assert len(by_tag) >= 1
    assert all("shibuya" in m.get("tags", []) for m in by_tag)

    by_cat = _extract_list(
        client.get("/api/telemetry/memories", params={"category": "sentiment_dislike"}).json(), "memories"
    )
    assert len(by_cat) >= 1
    assert all(m.get("category") == "sentiment_dislike" for m in by_cat)

    by_q = _extract_list(client.get("/api/telemetry/memories", params={"q": "Shibuya"}).json(), "memories")
    assert len(by_q) >= 1
    assert any("Shibuya" in m.get("content", "") for m in by_q)


def test_r5_telemetry_summary_and_observability_alias_and_health_integration(client: TestClient) -> None:
    """R5: GET /api/telemetry/summary, /api/observability/summary, and /api/health expose live telemetry counters."""
    client.post("/api/advisor/live", json={"prompt": "Summary counter test turn", "auto_forge": False})

    sum_resp = client.get("/api/telemetry/summary")
    assert sum_resp.status_code == 200
    summary = sum_resp.json()

    alias_resp = client.get("/api/observability/summary")
    assert alias_resp.status_code == 200
    alias_summary = alias_resp.json()

    assert int(summary["total_ai_calls"]) >= 1
    assert int(alias_summary["total_ai_calls"]) == int(summary["total_ai_calls"])
    assert int(summary["token_usage"]["total_tokens"]) > 0
    assert int(summary["active_sessions"]) >= 1
    assert "trajectory_counts_by_surface" in summary
    assert int(summary["trajectory_counts_by_surface"]["advisor"]) >= 1

    # Verify GET /api/health embeds live telemetry summary counters
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert "telemetry" in health_data
    h_tel = health_data["telemetry"]
    assert int(h_tel["total_ai_calls"]) >= 1
    assert "token_usage" in h_tel
    assert "active_sessions" in h_tel
    assert "stored_memories" in h_tel
    assert "trajectory_counts_by_surface" in h_tel


def test_r5_a2ui_telemetry_surface_returns_valid_v1_stream_with_inspector(client: TestClient) -> None:
    """R5: GET /api/surfaces/telemetry returns valid A2UI v1.0 stream with TelemetryInspector and preserves catalog invariants."""
    from backend.app.a2ui.catalog import CATALOG

    # Verify A2UI 6-item featureComponents invariant is untouched
    feature_comps = CATALOG["metadata"]["extensions"]["barogroove"]["featureComponents"]
    assert feature_comps == [
        "SkyDial",
        "ThemeChips",
        "GenreCorridor",
        "TrackList",
        "RationaleCard",
        "AlmanacTimeline",
    ]

    resp = client.get("/api/surfaces/telemetry")
    assert resp.status_code == 200
    assert "application/a2ui+json" in resp.headers.get("content-type", "")

    stream = resp.json()
    assert isinstance(stream, list) and len(stream) >= 1
    stream_str = json.dumps(stream)
    assert "TelemetryInspector" in stream_str or "telemetry" in stream_str.lower()


# ==============================================================================
# TIER 2 — Boundary & Corner Cases
# ==============================================================================


def test_tier2_nonexistent_ids_return_http_404(client: TestClient) -> None:
    """Tier 2 BVA: Requesting or deleting non-existent trajectory, session, conversation, or memory IDs returns HTTP 404."""
    assert client.get("/api/telemetry/trajectories/nonexistent_traj_99999").status_code == 404
    assert client.get("/api/telemetry/sessions/nonexistent_sess_99999").status_code == 404
    assert client.get("/api/telemetry/conversations/nonexistent_conv_99999").status_code == 404
    assert client.delete("/api/telemetry/memories/nonexistent_mem_99999").status_code == 404


def test_tier2_malformed_traceparent_falls_back_to_valid_32hex_trace_and_16hex_span(client: TestClient) -> None:
    """Tier 2 BVA: Malformed W3C traceparent header gracefully falls back to a valid 32-hex trace_id and 16-hex span_id."""
    resp = client.post(
        "/api/advisor/live",
        json={"prompt": "Malformed traceparent boundary test", "auto_forge": False},
        headers={"traceparent": "malformed-garbage-header-not-hex-at-all"},
    )
    assert resp.status_code == 200
    traj_id = resp.json().get("trajectory_id")
    traj = client.get(f"/api/telemetry/trajectories/{traj_id}").json()

    assert re.match(r"^[0-9a-f]{32}$", traj["trace_id"])
    assert re.match(r"^[0-9a-f]{16}$", traj["span_id"])


def test_tier2_memory_reinforcement_deduplication_boosts_confidence_and_count(client: TestClient) -> None:
    """Tier 2 BVA: Repeatedly posting duplicate memories increments reinforcement_count and boosts confidence <= 1.0."""
    mem_payload = {
        "user_id": "demo",
        "content": "Obsessed with 1990s Bristol trip-hop vinyl crackle",
        "category": "musical_preference",
        "confidence": 0.65,
    }
    r1 = client.post("/api/telemetry/memories", json=mem_payload).json()
    initial_conf = float(r1["confidence"])
    mem_id = r1["memory_id"]

    for _ in range(3):
        r_next = client.post("/api/telemetry/memories", json=mem_payload).json()

    assert r_next["memory_id"] == mem_id
    assert int(r_next["reinforcement_count"]) >= 4
    final_conf = float(r_next["confidence"])
    assert final_conf >= initial_conf
    assert final_conf <= 1.0


# ==============================================================================
# TIER 3 — Pairwise Combinatorial & Cross-Feature Integration
# ==============================================================================


def test_tier3_cross_surface_shared_session_and_memory_propagation(client: TestClient) -> None:
    """Tier 3 Combinatorial: Shared session across Advisor, Forge, Almanac Feedback, and DataViz QnA with memory propagation."""
    shared_session_id = "sess_tier3_combinatorial_01"

    # Step 1: Advisor turn expressing preference
    r_adv = client.post(
        "/api/advisor/live",
        json={
            "prompt": "I love dub techno in Berlin during low pressure storm fronts with Basic Channel",
            "session_id": shared_session_id,
            "auto_forge": False,
        },
    )
    assert r_adv.status_code == 200

    # Step 2: Forge playlist under same session
    r_forge = client.post(
        "/api/forge",
        json={
            "lat": 52.5200,
            "lon": 13.4050,
            "theme_id": "low_pressure_front",
            "genre_id": "dub-techno",
            "session_id": shared_session_id,
        },
    )
    assert r_forge.status_code == 200

    # Step 3: Almanac feedback (loved track)
    r_fb = client.post(
        "/api/almanac/feedback",
        json={
            "playlist_id": r_forge.json()["playlist"]["id"],
            "track_key": "Basic Channel - Phylyps Trak II",
            "signal": "loved",
        },
    )
    assert r_fb.status_code == 200

    # Step 4: DataViz QnA under same session
    r_qna = client.post(
        "/api/dataviz/qna",
        json={
            "question": "How does my low pressure taste connect to my favorite tracks?",
            "session_id": shared_session_id,
        },
    )
    assert r_qna.status_code == 200
    qna_traj_id = r_qna.json().get("trajectory_id")

    # Verify SessionRecord tracks multi-surface trajectories
    sess = client.get(f"/api/telemetry/sessions/{shared_session_id}").json()
    assert int(sess["turn_count"]) >= 2

    session_trajs = _extract_list(
        client.get("/api/telemetry/trajectories", params={"session_id": shared_session_id}).json(),
        "trajectories",
    )
    surfaces_seen = {t["surface"] for t in session_trajs}
    assert {"advisor", "dataviz"}.issubset(surfaces_seen)

    # Verify cross-surface semantic memories were injected into DataViz QnA system_instruction
    if qna_traj_id:
        qna_traj = client.get(f"/api/telemetry/trajectories/{qna_traj_id}").json()
        sys_inst = qna_traj["system_instruction"]
        assert any(kw in sys_inst for kw in ["Basic Channel", "Phylyps Trak", "dub techno", "Berlin"]), (
            f"Cross-surface memories not found in DataViz QnA system_instruction: {sys_inst}"
        )


# ==============================================================================
# TIER 4 — Real-World End-to-End Application Scenarios
# ==============================================================================


def test_tier4_full_user_journey_e2e_observability_lifecycle(client: TestClient) -> None:
    """Tier 4 E2E Workload: Complete listener journey from discovery -> multi-turn advisor -> forge & explain -> feedback -> dataviz -> inspector."""
    trace_id = "99887766554433221100ffeeddccbbaa"
    headers = {"traceparent": f"00-{trace_id}-1122334455667788-01"}

    # 1. Discovery: GET /api/advisor/suggestions
    sugg_resp = client.get("/api/advisor/suggestions", headers=headers)
    assert sugg_resp.status_code == 200

    # 2. Multi-turn Advisor Consultation (Turn 1)
    turn1_resp = client.post(
        "/api/advisor/live",
        json={
            "prompt": "Teleport to Wall Poetry Grandi in Reykjavík and forge a low pressure ambient set with Sigur Rós.",
            "auto_forge": True,
        },
        headers=headers,
    )
    assert turn1_resp.status_code == 200
    t1_data = turn1_resp.json()
    session_id = t1_data["session_id"]
    conversation_id = t1_data["conversation_id"]
    forged_playlist = t1_data["forge_result"]["playlist"]

    # 3. Multi-turn Advisor Consultation (Turn 2 - refinement)
    turn2_resp = client.post(
        "/api/advisor/live",
        json={
            "prompt": "Keep Wall Poetry Grandi in Reykjavík but shift the theme to Petrichor rain.",
            "session_id": session_id,
            "conversation_id": conversation_id,
            "auto_forge": True,
        },
        headers=headers,
    )
    assert turn2_resp.status_code == 200

    # 4. Playlist Explainability
    explain_resp = client.post("/api/forge/explain", json=forged_playlist, headers=headers)
    assert explain_resp.status_code == 200

    # 5. Almanac Track Feedback
    fb_resp = client.post(
        "/api/almanac/feedback",
        json={
            "playlist_id": forged_playlist["id"],
            "track_key": "Sigur Rós - Svefn-g-englar",
            "signal": "loved",
        },
        headers=headers,
    )
    assert fb_resp.status_code == 200

    # 6. DataViz QnA Consultation
    qna_resp = client.post(
        "/api/dataviz/qna",
        json={
            "question": "Compare my low pressure vs high pressure BPM sensitivity",
            "session_id": session_id,
            "conversation_id": conversation_id,
        },
        headers=headers,
    )
    assert qna_resp.status_code == 200

    # 7. Final Telemetry Audit & A2UI Inspector Verification
    summary = client.get("/api/telemetry/summary").json()
    assert int(summary["total_ai_calls"]) >= 5
    assert int(summary["stored_memories"]) >= 1
    assert int(summary["active_sessions"]) >= 1

    counts = summary["trajectory_counts_by_surface"]
    assert counts.get("advisor", 0) >= 3
    assert counts.get("forge", 0) >= 1
    assert counts.get("dataviz", 0) >= 1

    inspector_resp = client.get("/api/surfaces/telemetry")
    assert inspector_resp.status_code == 200
    assert "application/a2ui+json" in inspector_resp.headers.get("content-type", "")
