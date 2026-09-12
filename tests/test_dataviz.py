"""Comprehensive pytest unit tests for BaroGroove Data Viz & Gemini Live 2.5 QnA Agent."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.dataviz.engine import (
    VALID_HIGHLIGHT_SECTIONS,
    DataVizDashboardResponse,
    DataVizQnARequest,
    DataVizQnAResponse,
    get_dataviz_engine,
)
from backend.app.main import _OPTIONAL_ROUTERS, create_app


def test_dataviz_router_registered_in_optional_routers() -> None:
    """Verify 'backend.app.routes.dataviz' is listed in _OPTIONAL_ROUTERS."""
    assert "backend.app.routes.dataviz" in _OPTIONAL_ROUTERS


def test_get_dataviz_dashboard_endpoint() -> None:
    """Verify GET /api/dataviz/dashboard returns structured telemetry matching all specifications."""
    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/dataviz/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    # Validate summary_stats
    stats = data["summary_stats"]
    assert stats["total_scrobbles_analyzed"] > 0
    assert isinstance(stats["avg_bpm"], float)
    assert isinstance(stats["dominant_weather_theme"], str)
    assert isinstance(stats["dominant_genre"], str)
    assert 0.0 <= stats["pressure_sensitivity_index"] <= 1.0

    # Validate pressure_vs_bpm (18 items)
    pressure_pts = data["pressure_vs_bpm"]
    assert len(pressure_pts) == 18
    for pt in pressure_pts:
        assert "pressure_hpa" in pt and isinstance(pt["pressure_hpa"], float)
        assert "bpm" in pt and isinstance(pt["bpm"], int)
        assert "energy" in pt and isinstance(pt["energy"], float)
        assert "track_title" in pt and isinstance(pt["track_title"], str)
        assert "artist" in pt and isinstance(pt["artist"], str)
        assert "theme_id" in pt and isinstance(pt["theme_id"], str)

    # Verify low pressure correlates with lower BPM than high pressure ridge
    low_pressure_bpms = [p["bpm"] for p in pressure_pts if p["pressure_hpa"] < 1005.0]
    high_pressure_bpms = [p["bpm"] for p in pressure_pts if p["pressure_hpa"] > 1020.0]
    assert sum(low_pressure_bpms) / len(low_pressure_bpms) < sum(high_pressure_bpms) / len(high_pressure_bpms)

    # Validate weather_affinity_breakdown (6 items)
    affinity = data["weather_affinity_breakdown"]
    assert len(affinity) == 6
    for item in affinity:
        assert "theme_id" in item
        assert "theme_name" in item
        assert "scrobble_count" in item and isinstance(item["scrobble_count"], int)
        assert "percentage" in item and isinstance(item["percentage"], float)
        assert "avg_bpm" in item and isinstance(item["avg_bpm"], int)
        assert "top_artist" in item and isinstance(item["top_artist"], str)

    # Validate hourly_solar_heatmap (24 hours: 0..23)
    hourly = data["hourly_solar_heatmap"]
    assert len(hourly) == 24
    hours = [h["hour"] for h in hourly]
    assert hours == list(range(24))
    for h in hourly:
        assert "label" in h
        assert 0.0 <= h["activity_score"] <= 1.0
        assert isinstance(h["avg_bpm"], int)
        assert isinstance(h["dominant_mood"], str)

    # Validate decade_sonic_dna (6 decades: 1970s..2020s)
    decades = data["decade_sonic_dna"]
    assert len(decades) == 6
    decade_labels = [d["decade"] for d in decades]
    assert decade_labels == ["1970s", "1980s", "1990s", "2000s", "2010s", "2020s"]
    for d in decades:
        assert isinstance(d["percentage"], float)
        assert isinstance(d["track_count"], int)
        assert isinstance(d["signature_artists"], list)
        assert len(d["signature_artists"]) >= 2
        assert isinstance(d["vibe_summary"], str)


def test_post_dataviz_qna_pressure_question() -> None:
    """Verify POST /api/dataviz/qna with barometric pressure question highlights pressure_vs_bpm."""
    app = create_app()
    client = TestClient(app)

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
    assert len(data["answer_text"]) > 20
    assert len(data["spoken_summary"]) > 15
    assert "1005" in data["key_metric_badge"] or "BPM" in data["key_metric_badge"]
    assert len(data["suggested_followups"]) == 3
    assert 1 <= len(data["matching_scrobbles"]) <= 4
    for sc in data["matching_scrobbles"]:
        assert "id" in sc
        assert "artist" in sc
        assert "track" in sc
        assert "album" in sc


def test_post_dataviz_qna_solar_and_decade_questions() -> None:
    """Verify POST /api/dataviz/qna routes solar chronology and decade DNA questions accurately."""
    app = create_app()
    client = TestClient(app)

    # Solar chronology question
    resp_solar = client.post(
        "/api/dataviz/qna",
        json={
            "question": "Compare my late-night vs morning BPM and solar chronology",
            "voice_mode": False,
        },
    )
    assert resp_solar.status_code == 200
    data_solar = resp_solar.json()
    assert data_solar["highlight_section"] == "hourly_solar"
    assert len(data_solar["suggested_followups"]) == 3

    # Decade DNA question
    resp_decade = client.post(
        "/api/dataviz/qna",
        json={
            "question": "Break down my 1990s Bristol Trip-Hop & Dub Techno DNA",
            "voice_mode": True,
        },
    )
    assert resp_decade.status_code == 200
    data_decade = resp_decade.json()
    assert data_decade["highlight_section"] == "decade_dna"
    assert "1990s" in data_decade["key_metric_badge"]


def test_post_dataviz_qna_vertex_ai_mocked_path() -> None:
    """Verify Vertex AI Gemini 2.5 Flash response handling when ADC credentials and Vertex endpoint succeed."""
    app = create_app()
    client = TestClient(app)

    fake_vertex_json = {
        "answer_text": "When high pressure Solar Zenith arrives, your catalog surges to 124 BPM led by Stromae.",
        "spoken_summary": "Solar Zenith triggers your highest energy tracks at 124 BPM.",
        "highlight_section": "weather_affinity",
        "key_metric_badge": "Solar Zenith • 124 BPM Peak",
        "suggested_followups": [
            "What happens below 1005 hPa?",
            "Show my 1990s Bristol Trip-Hop DNA",
            "Compare late night vs morning BPM",
        ],
        "matching_scrobble_ids": [],
    }

    with (
        patch("backend.app.dataviz.engine._get_vertex_token", return_value=("fake-token", "test-project")),
        patch("backend.app.dataviz.engine._call_vertex_gemini_qna", return_value=fake_vertex_json),
    ):
        resp = client.post(
            "/api/dataviz/qna",
            json={"question": "Which weather theme triggers my highest energy tracks?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["highlight_section"] == "weather_affinity"
        assert data["model_used"] == "gemini-2.5-flash (vertex-ai)"
        assert data["key_metric_badge"] == "Solar Zenith • 124 BPM Peak"
        assert len(data["matching_scrobbles"]) > 0


def test_atmospheric_cursors_console_forge_overrides() -> None:
    """Verify POST /api/forge honors custom Temp, Light, Kelvin, Pressure, Trend, and Target BPM cursors."""
    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/forge",
        json={
            "lat": 50.8503,
            "lon": 4.3517,
            "custom_temp_c": 28.5,
            "custom_light_pct": 85.0,
            "custom_color_kelvin": 2400.0,
            "custom_pressure_hpa": 994.0,
            "custom_trend_hpa": -3.5,
            "custom_target_bpm": 128.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    playlist = body["playlist"]
    assert abs(playlist["sonic_target"]["tempo"] - (128.0 - 60.0) / (180.0 - 60.0)) < 0.01
    notes_joined = " ".join(playlist["rationale"]["sonic_moves"])
    assert "Atmospheric Console" in notes_joined
    assert "128 BPM" in notes_joined

