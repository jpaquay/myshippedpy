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
    """Every figure the dashboard reports is read off the corpus, or is null.

    This test used to pin the fabricated shape rather than the data: exactly 18
    pressure points, exactly 6 affinity rows, exactly 6 decades 1970s..2020s,
    and an asserted low-pressure/high-pressure BPM correlation. All of it came
    from hand-written tables in `dataviz/engine.py`, so the test passed by
    checking that the constants were still the constants.
    """
    from backend.app.almanac.scrobbles import get_15year_analytics

    analytics = get_15year_analytics()

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/dataviz/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    # --- summary_stats: the corpus's own numbers, not a stand-in ------------
    stats = data["summary_stats"]
    assert stats["total_scrobbles_analyzed"] == analytics.total_scrobbles
    assert stats["avg_bpm"] == round(analytics.avg_bpm, 1)
    # 102.4 was the hardcoded stand-in. The corpus says something else, which
    # is exactly how we know it was never a stale copy of the truth.
    assert stats["avg_bpm"] != 102.4

    # No pressure reading exists per play, so there is nothing to correlate.
    # This was a hardcoded 0.84 presented as a measured coefficient.
    assert stats["pressure_sensitivity_index"] is None

    # --- weather_affinity: passed through from the summary, row for row ----
    affinity = data["weather_affinity_breakdown"]
    assert len(affinity) == len(analytics.weather_affinity)
    by_id = {row["theme_id"]: row for row in affinity}
    for source in analytics.weather_affinity:
        row = by_id[source["theme_id"]]
        assert row["scrobble_count"] == source["plays"]
        assert row["percentage"] == round(source["percentage"], 1)
        # Joined in from the catalog, and null rather than guessed.
        assert row["avg_bpm"] is None or isinstance(row["avg_bpm"], int)
        assert row["top_artist"] is None or isinstance(row["top_artist"], str)

    # The leading row of the real breakdown, not a stated favourite.
    assert stats["dominant_weather_theme"] == affinity[0]["theme_id"]

    # None of the six invented rows survive. `clear_high` is retired with no
    # successor at all and must never be originated.
    invented = {"clear_high", "midnight_thermal", "solar_zenith"}
    assert invented.isdisjoint(by_id)

    # --- hourly_solar: the real UTC histogram ------------------------------
    hourly = data["hourly_solar_heatmap"]
    assert [h["hour"] for h in hourly] == list(range(24))
    busiest = max(hourly, key=lambda h: h["scrobble_count"])
    assert busiest["activity_score"] == 1.0
    for h in hourly:
        assert 0.0 <= h["activity_score"] <= 1.0
        # The histogram counts plays; it does not say what they were.
        assert h["avg_bpm"] is None
        assert h["dominant_mood"] is None

    # --- the two charts with no data source at all -------------------------
    # No pressure is recorded against a play, and no release year against a
    # track. Empty, and the renderer names what is missing.
    assert data["pressure_vs_bpm"] == []
    assert data["decade_sonic_dna"] == []


def test_dataviz_engine_originates_no_invented_figures() -> None:
    """Source guard: the literals that were fabricated do not come back.

    Same mechanism as `frontend/test/honest_empty_states_test.dart`, on the
    layer that owns the numbers. Comments are stripped first, because the fix
    for each of these is a comment naming the literal it removed.
    """
    import pathlib
    import re

    src = pathlib.Path("backend/app/dataviz/engine.py").read_text()
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    # Drop docstrings too, for the same reason.
    code = re.sub(r'""".*?"""', "", code, flags=re.S)

    for literal in (
        "160717",  # the stand-in scrobble total
        "102.4",  # the drifted average tempo
        "0.84",  # the "pressure sensitivity index"
        "38572",  # invented Petrichor plays
        "20893",  # invented "High Pressure Clarity" plays
        "42590",  # invented 1990s track count
        "clear_high",  # retired with no successor
        "midnight_thermal",
        "solar_zenith",
        "low_pressure_front",
    ):
        assert literal not in code, f"{literal!r} is back in dataviz/engine.py"


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
    assert len(data["suggested_followups"]) == 3

    # The answer refuses rather than invents. It used to reply "your tempo
    # decelerates by 18.4% to an average of 86 BPM ... Pressure Sensitivity
    # Index of 0.84" — none of which was measured anywhere, on the path that
    # runs offline and under test.
    assert "not recorded" in data["answer_text"].lower() or "no barometric" in data["answer_text"].lower()
    for invented in ("86 BPM", "18.4%", "0.84", "1005 hPa"):
        assert invented not in data["answer_text"]
        assert invented not in data["spoken_summary"]
        assert invented not in data["key_metric_badge"]
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
    # It used to answer "the 1990s, 26.5% of your catalog, 42,590 scrobbles".
    # No release year is recorded for any track, so that share was invented.
    assert "release year" in data_decade["answer_text"].lower()
    for invented in ("26.5%", "42,590", "42590"):
        assert invented not in data_decade["answer_text"]
        assert invented not in data_decade["key_metric_badge"]


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

