"""Tests for the Gemini Live Forge Advisor & Executor endpoints and engine."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app

app = create_app()


def test_advisor_suggestions_endpoint() -> None:
    client = TestClient(app)
    resp = client.get("/api/advisor/suggestions")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) == 4
    assert items[0]["id"] == "tokyo_night_triphop"
    assert "Tokyo" in items[0]["title"]


def test_advisor_live_turn_executes_forge_and_teleports() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/advisor/live",
        json={
            "prompt": "Teleport to Shimokitazawa in Tokyo and forge a late-night trip-hop set with Massive Attack.",
            "auto_forge": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_geocache"]["id"] == "shimokitazawa_tokyo"
    assert data["selected_theme_id"] in {"blue_hour", "midnight_thermal", "low_pressure_front"}
    assert data["selected_genre_id"] == "trip-hop"
    assert len(data["actions_executed"]) >= 3
    assert data["forge_result"] is not None
    assert len(data["forge_result"]["playlist"]["tracks"]) == 18
    assert len(data["spoken_summary"]) > 15
