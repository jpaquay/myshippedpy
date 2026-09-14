"""Data Visualization Telemetry & Gemini Live 2.5 QnA Engine.

Aggregates the Sonic Almanac scrobble corpus and its cached summary into the
dashboard models behind ``GET /api/dataviz/dashboard``, and powers the Gemini
Live 2.5 Flash Data Viz QnA studio.

WHAT THIS MODULE MAY AND MAY NOT DO
-----------------------------------
Every number it emits is read or derived from the corpus. Where the corpus has
no answer, it emits ``None`` or an empty list and the renderer says so.

It did not use to. Four builders returned hand-written constants that the
dashboard presented as measurements:

* ``_build_weather_affinity`` returned six fixed rows (Petrichor 24.0% /
  38,572 plays, "High Pressure Clarity" 13.0% / 20,893 ...). The corpus summary
  sitting on disk beside it says something else entirely -- seven themes, top
  row ``warm_front_haze`` at 15.6% / 25,090 -- and disagrees on every row and
  every id. The table was not stale data; it was never data.
* ``_build_hourly_solar_heatmap`` returned 24 fixed buckets while
  ``hourly_histogram_utc`` in the same summary held the real per-hour counts.
* ``_build_pressure_vs_bpm_points`` held 18 ``baseline_templates`` tuples and
  overwrote only the title and artist of the first ``len(scrobbles)`` of them
  from the catalog, keeping the invented pressure, BPM and energy, and emitting
  the remaining rows whole. That is padding a thin result, not a shape for real
  data to fill.
* ``_build_decade_sonic_dna`` returned six fixed decades.

``get_dashboard`` then did ``analytics.total_scrobbles or 160717`` and
``analytics.avg_bpm or 102.4``. The first happened to match the corpus; the
second had drifted -- the corpus says 104.6.

The templates also originated four retired theme ids (``low_pressure_front``,
``midnight_thermal``, ``solar_zenith``, and ``clear_high``, which is retired
with no successor at all -- see ``contracts.RETIRED_THEME_IDS``).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from backend.app.almanac.scrobbles import ScrobbleEntry, search_scrobbles

logger = logging.getLogger(__name__)

VALID_HIGHLIGHT_SECTIONS = {
    "pressure_vs_bpm",
    "weather_affinity",
    "hourly_solar",
    "decade_dna",
}


class SummaryStats(BaseModel):
    """High-level KPI summary metrics across the user's Sonic Almanac.

    Every field is nullable, and ``None`` means *the corpus does not answer
    this*. The renderer shows an em-dash rather than a number, which is what
    ``UX_IA_SPEC.md`` §2 rule 4 requires of an empty state.
    """

    total_scrobbles_analyzed: int | None = Field(
        default=None,
        description="Total scrobbles analyzed, or null when nothing is synced.",
    )
    avg_bpm: float | None = Field(
        default=None,
        description="Weighted average tempo across all scrobbles, or null when unknown.",
    )
    dominant_weather_theme: str | None = Field(
        default=None,
        description="Most frequent barometric weather theme, or null when unknown.",
    )
    dominant_genre: str | None = Field(
        default=None,
        description="Top sonic corridor / genre tag, or null when unknown.",
    )
    # Was a hardcoded coefficient, emitted on every response and rendered as
    # "84% CORR" in the KPI ribbon. Nothing measured it.
    pressure_sensitivity_index: float | None = Field(
        default=None,
        description=(
            "Correlation between barometric shift and tempo selection. Always "
            "null: no pressure reading is recorded against a scrobble anywhere "
            "in this system, so there is nothing to correlate."
        ),
    )


class PressureVsBpmPoint(BaseModel):
    """Single data point mapping barometric pressure (hPa) against sonic BPM and track energy."""

    pressure_hpa: float = Field(..., description="Barometric pressure in hectopascals (hPa).")
    bpm: int = Field(..., description="Track tempo in beats per minute.")
    energy: float = Field(..., description="Normalized track energy score (0.0 to 1.0).")
    track_title: str = Field(..., description="Representative track title.")
    artist: str = Field(..., description="Representative artist name.")
    theme_id: str = Field(..., description="Associated BaroGroove weather theme ID.")


class WeatherAffinityItem(BaseModel):
    """One row of the real weather-affinity breakdown from the corpus summary."""

    theme_id: str = Field(..., description="Sky theme identifier, as recorded in the corpus.")
    theme_name: str = Field(..., description="Human-readable atmospheric theme name.")
    scrobble_count: int = Field(..., description="Number of scrobbles logged under this weather regime.")
    percentage: float = Field(..., description="Percentage share of total listening.")
    avg_bpm: int | None = Field(
        default=None,
        description="Play-weighted mean BPM of catalog tracks in this theme, or null when none are held.",
    )
    top_artist: str | None = Field(
        default=None,
        description="Most-played catalog artist in this theme, or null when none are held.",
    )


class HourlySolarBucket(BaseModel):
    """One hour bucket (0..23) of the real UTC play histogram."""

    hour: int = Field(..., ge=0, le=23, description="Hour of day (0-23, UTC).")
    label: str = Field(..., description="Formatted hour label (e.g. '06:00').")
    activity_score: float = Field(..., description="Plays this hour / plays in the busiest hour (0.0 to 1.0).")
    scrobble_count: int = Field(default=0, description="Plays recorded in this hour.")
    avg_bpm: int | None = Field(
        default=None,
        description=(
            "Always null. The histogram counts plays per hour; it does not "
            "carry which tracks they were, so there is no tempo to average. "
            "This used to be a hand-written per-hour BPM curve."
        ),
    )
    dominant_mood: str | None = Field(
        default=None,
        description="Always null, for the same reason as avg_bpm.",
    )


class DecadeSonicDnaItem(BaseModel):
    """Decade-by-decade breakdown of musical eras in the user's Almanac."""

    decade: str = Field(..., description="Decade label (e.g. '1990s').")
    percentage: float = Field(..., description="Percentage share of catalog tracks.")
    track_count: int = Field(..., description="Total scrobbles/tracks from this decade.")
    signature_artists: list[str] = Field(
        default_factory=list,
        description="Representative artists anchoring this decade.",
    )
    vibe_summary: str = Field(..., description="Atmospheric narrative of this era's sonic DNA.")


class DataVizDashboardResponse(BaseModel):
    """Complete payload for `GET /api/dataviz/dashboard`."""

    summary_stats: SummaryStats
    pressure_vs_bpm: list[PressureVsBpmPoint]
    weather_affinity_breakdown: list[WeatherAffinityItem]
    hourly_solar_heatmap: list[HourlySolarBucket]
    decade_sonic_dna: list[DecadeSonicDnaItem]


class DataVizQnARequest(BaseModel):
    """Request payload for `POST /api/dataviz/qna`."""

    question: str = Field(..., description="Natural language or voice-transcribed question about the user's sonic telemetry.")
    voice_mode: bool = Field(default=True, description="Whether the user asked via voice orb / expects spoken TTS summary.")
    session_id: str | None = Field(default=None, description="Optional user session ID for multi-turn continuity.")
    conversation_id: str | None = Field(default=None, description="Optional conversation thread ID.")
    user_id: str | None = Field(default=None, description="Optional user identifier.")


class MatchingScrobbleItem(BaseModel):
    """Scrobble track matching a Gemini Live Data Viz insight, ready to seed into Forge."""

    id: str = Field(..., description="Unique catalog/scrobble ID.")
    artist: str = Field(..., description="Track artist.")
    track: str = Field(..., description="Track title.")
    album: str = Field(default="", description="Album title.")


class DataVizQnAResponse(BaseModel):
    """Structured insight returned by `POST /api/dataviz/qna`."""

    answer_text: str = Field(..., description="Detailed 2-3 sentence data-storytelling response.")
    spoken_summary: str = Field(..., description="Punchy 1-2 sentence DJ/Data-Scientist spoken answer for TTS.")
    highlight_section: str = Field(
        ...,
        description="Dashboard section to highlight: 'pressure_vs_bpm', 'weather_affinity', 'hourly_solar', or 'decade_dna'.",
    )
    key_metric_badge: str = Field(..., description="Headline metric badge summarizing the insight.")
    suggested_followups: list[str] = Field(
        default_factory=list,
        description="List of 3 natural follow-up questions.",
    )
    matching_scrobbles: list[MatchingScrobbleItem] = Field(
        default_factory=list,
        description="Up to 4 scrobble tracks that exemplify the insight.",
    )
    model_used: str = Field(
        default="gemini-2.5-flash (vertex-ai)",
        description="Model that generated the data storytelling insight.",
    )
    trajectory_id: str = Field(default="", description="Captured AI trajectory record ID.")
    session_id: str = Field(default="", description="Active user session ID.")
    conversation_id: str = Field(default="", description="Active multi-turn conversation ID.")
    user_id: str = Field(default="demo", description="User identifier.")
    latency_ms: float = Field(default=0.0, description="Turn latency in milliseconds.")
    token_usage: dict[str, Any] = Field(
        default_factory=dict,
        description="Token usage metrics (prompt_tokens, candidate_tokens, total_tokens, is_estimated).",
    )
    # --- BigQuery Data QnA provenance (UX_IA_SPEC.md §3.4 answer card) -------
    # The answer card needs three things the narrative alone cannot supply: the
    # SQL that was run (the `SOURCE QUERY` trust affordance), the chart geometry
    # to draw, and a row count so the client can tell "no rows" apart from
    # "error". All three come from the BigQuery Data QnA agent
    # (`backend/app/almanac/data_qna.py`), which already produces them; this
    # block just carries them on the Data Viz turn so the surface needs exactly
    # one round trip. Every field degrades to empty, never to a fabrication.
    generated_sql: str = Field(
        default="",
        description="SQL the Data QnA agent ran (or synthesised offline). Empty when no query was produced.",
    )
    chart_spec: dict[str, Any] | None = Field(
        default=None,
        description="QnAChartSpec for the answer card chart: chart_type/title/subtitle/x_label/y_label/series.",
    )
    row_count: int = Field(
        default=0,
        description="Rows the query returned. 0 with a non-empty generated_sql means a genuine no-rows answer.",
    )
    data_engine: str = Field(
        default="",
        description="Which engine produced the query: 'bigquery_data_qna_v1beta', 'local_olap_synthesizer', or ''.",
    )


def _source_query_payload(question: str) -> dict[str, Any]:
    """Run the BigQuery Data QnA agent for `question` and extract card provenance.

    Blocking and best-effort: any failure yields an empty payload so a Data Viz
    turn never fails because the source-query lookup did. Imported lazily to
    keep `backend.app.dataviz` free of an import-time dependency on the almanac
    QnA stack.
    """
    try:
        from backend.app.almanac.data_qna import DataQnARequest, ask_data_qna

        qna = ask_data_qna(DataQnARequest(question=question))
        spec = qna.chart_spec.model_dump(mode="json") if qna.chart_spec else None
        if spec is not None and not spec.get("series"):
            # An empty series is not a chart; let the client render its no-rows
            # state instead of an axis with nothing on it.
            spec = None
        return {
            "generated_sql": qna.sql_query or "",
            "chart_spec": spec,
            "row_count": len(qna.rows or []),
            "data_engine": qna.engine or "",
            "suggestions": list(qna.suggestions or []),
        }
    except Exception:  # noqa: BLE001 - provenance is additive; never fail the turn
        logger.debug("source-query lookup unavailable for Data Viz turn", exc_info=True)
        return {}


_DEFAULT_CURATED_SCROBBLES: list[MatchingScrobbleItem] = [
    MatchingScrobbleItem(
        id="scrobble_massive_teardrop",
        artist="Massive Attack",
        track="Teardrop",
        album="Mezzanine",
    ),
    MatchingScrobbleItem(
        id="scrobble_portishead_glorybox",
        artist="Portishead",
        track="Glory Box",
        album="Dummy",
    ),
    MatchingScrobbleItem(
        id="scrobble_gainsbourg_javanaise",
        artist="Serge Gainsbourg",
        track="La Javanaise",
        album="Gainsbourg Confidentiel",
    ),
    MatchingScrobbleItem(
        id="scrobble_chineseman_tune",
        artist="Chinese Man",
        track="I've Got That Tune",
        album="The Groove Sessions Vol. 2",
    ),
    MatchingScrobbleItem(
        id="scrobble_brassens_copains",
        artist="Georges Brassens",
        track="Les copains d'abord",
        album="Les copains d'abord",
    ),
    MatchingScrobbleItem(
        id="scrobble_stromae_formidable",
        artist="Stromae",
        track="Formidable",
        album="Racine Carrée",
    ),
]


def _get_vertex_token() -> tuple[str | None, str]:
    """Retrieve a Google Cloud bearer token and project ID via Application Default Credentials."""
    project_id = os.environ.get("BG_GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "netdev-firebase"
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("BG_WEATHER_OFFLINE") == "1":
        return None, project_id
    try:
        import google.auth
        import google.auth.transport.requests

        creds, detected_project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token, detected_project or project_id
    except Exception as exc:
        logger.debug("Vertex AI ADC token unavailable (%s); using deterministic DataViz fallback", exc)
        return None, project_id


def _catalog_theme_stats() -> dict[str, dict[str, Any]]:
    """Per-theme BPM mean and top artist, computed from the track catalog.

    The corpus summary knows how many plays each weather theme took but not
    what they sounded like; the catalog knows the tempo and artist of each
    track but not the summary totals. Joining them here is the only place the
    two meet, and it is a real join -- no row is emitted for a theme the
    catalog holds no tracks for.
    """
    from backend.app.almanac.scrobbles import _ensure_catalog_and_indexes

    stats: dict[str, dict[str, Any]] = {}
    try:
        catalog = _ensure_catalog_and_indexes()
    except Exception:  # noqa: BLE001 - a missing catalog means "no answer", not a 500
        logger.debug("track catalog unavailable; weather affinity will omit BPM and top artist")
        return stats

    for row in catalog:
        theme = str(row.get("weather_theme") or "").strip()
        if not theme:
            continue
        try:
            plays = int(row.get("play_count") or 0)
            bpm = int(row.get("bpm_estimate") or 0)
        except (TypeError, ValueError):
            continue
        if plays <= 0:
            continue
        bucket = stats.setdefault(theme, {"bpm_weighted": 0, "plays": 0, "artists": {}})
        if bpm > 0:
            bucket["bpm_weighted"] += bpm * plays
            bucket["plays"] += plays
        artist = str(row.get("artist") or "").strip()
        if artist:
            bucket["artists"][artist] = bucket["artists"].get(artist, 0) + plays

    out: dict[str, dict[str, Any]] = {}
    for theme, bucket in stats.items():
        plays = bucket["plays"]
        artists: dict[str, int] = bucket["artists"]
        out[theme] = {
            "avg_bpm": round(bucket["bpm_weighted"] / plays) if plays else None,
            "top_artist": max(artists, key=lambda a: artists[a]) if artists else None,
        }
    return out


def _build_pressure_vs_bpm_points(scrobbles: list[ScrobbleEntry]) -> list[PressureVsBpmPoint]:
    """Always empty. Nothing in this system records a pressure reading per play.

    This used to return 18 points from a ``baseline_templates`` table of
    invented ``(pressure, bpm, energy, title, artist, theme)`` tuples. Real
    scrobbles overwrote the title and artist of the first ``len(scrobbles)``
    rows and nothing else -- the pressure, the BPM and the energy stayed
    invented even for those -- and every remaining row shipped whole. So the
    templates were not a shape for real data to fill. They were the data, and
    the scrobbles were a veneer on top of it.

    To fill this chart honestly the corpus would have to carry the barometric
    pressure observed at each play. It does not: neither ``track_catalog.jsonl``
    nor ``summary_cache.json`` has a pressure field, and no join anywhere
    reconstructs one. An axis labelled hPa therefore cannot be populated, and
    the renderer says so instead of drawing a plausible curve.

    The signature keeps ``scrobbles`` so the call site reads the same and so
    this docstring sits where the padding used to.
    """
    del scrobbles
    return []


def _build_weather_affinity(analytics: Any) -> list[WeatherAffinityItem]:
    """The real per-theme listening split, from the corpus summary.

    ``analytics.weather_affinity`` is what the summary actually measured.
    Percentage and play count are passed through unchanged; BPM and top artist
    are joined in from the catalog and stay ``None`` where it holds nothing.
    """
    rows = list(getattr(analytics, "weather_affinity", None) or [])
    if not rows:
        return []

    catalog_stats = _catalog_theme_stats()
    items: list[WeatherAffinityItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        theme_id = str(row.get("theme_id") or "").strip()
        if not theme_id:
            continue
        try:
            plays = int(row.get("plays") or 0)
            percentage = float(row.get("percentage") or 0.0)
        except (TypeError, ValueError):
            continue
        joined = catalog_stats.get(theme_id, {})
        items.append(
            WeatherAffinityItem(
                theme_id=theme_id,
                theme_name=str(row.get("label") or theme_id.replace("_", " ").title()),
                scrobble_count=plays,
                percentage=round(percentage, 1),
                avg_bpm=joined.get("avg_bpm"),
                top_artist=joined.get("top_artist"),
            )
        )
    items.sort(key=lambda i: i.percentage, reverse=True)
    return items


def _build_hourly_solar_heatmap() -> list[HourlySolarBucket]:
    """The real 24-hour play histogram, from the corpus summary.

    ``activity_score`` is this hour's plays over the busiest hour's plays, so
    the tallest bar is 1.0 by construction and every other bar is a ratio of
    two counted numbers.

    This used to be 24 hand-written ``(score, bpm, mood)`` tuples -- "02:00 •
    Astral Stillness, 0.31, 84 BPM, Late-Night Vinyl & Lo-Fi Drift" -- while
    ``hourly_histogram_utc`` sat unread in the same summary file. The mood
    labels and the per-hour BPM have no source at all and are gone; the
    histogram carries counts, not tracks.
    """
    from backend.app.almanac.scrobbles import fetch_firestore_summary

    try:
        summary = fetch_firestore_summary() or {}
    except Exception:  # noqa: BLE001 - no summary means "no answer", not a 500
        logger.debug("corpus summary unavailable; hourly heatmap omitted")
        return []

    raw = summary.get("hourly_histogram_utc") or {}
    if not isinstance(raw, dict) or not raw:
        return []

    counts: dict[int, int] = {}
    for key, value in raw.items():
        try:
            hour = int(key)
            count = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23 and count >= 0:
            counts[hour] = count
    if not counts:
        return []

    busiest = max(counts.values()) or 1
    return [
        HourlySolarBucket(
            hour=hour,
            label=f"{hour:02d}:00",
            activity_score=round(counts.get(hour, 0) / busiest, 4),
            scrobble_count=counts.get(hour, 0),
        )
        for hour in range(24)
    ]


def _build_decade_sonic_dna() -> list[DecadeSonicDnaItem]:
    """Always empty. Nothing in this system records when a track was released.

    This used to return six decades, 1970s through 2020s, with shares, track
    counts, signature artists and a prose "vibe summary" apiece -- "1990s,
    26.5%, 42,590 tracks, the Bristol Trip-Hop golden era". None of it was
    measured.

    A release decade needs a release year. ``track_catalog.jsonl`` carries
    ``first_played_at`` and ``last_played_at``, which say when a track entered
    *this listener's* history, not when it was made, and nothing else in the
    corpus comes closer. ``summary_cache.json``'s ``yearly_counts`` are play
    years for the same reason. Deriving a decade from either would be a guess
    wearing a percentage sign, so the chart stays empty and the renderer names
    what is missing.
    """
    return []


#: What the prompt says where a figure does not exist. Spelled once.
_NOT_RECORDED = "not recorded in this corpus"


def _kpi_line(dashboard: DataVizDashboardResponse) -> str:
    """The one-line KPI preamble, with an absence named rather than filled."""
    s = dashboard.summary_stats
    parts = [
        f"{s.total_scrobbles_analyzed:,} scrobbles analyzed"
        if s.total_scrobbles_analyzed is not None
        else f"scrobble total {_NOT_RECORDED}",
        f"avg {s.avg_bpm} BPM"
        if s.avg_bpm is not None
        else f"average tempo {_NOT_RECORDED}",
    ]
    if s.dominant_genre:
        parts.append(f"top tag '{s.dominant_genre}'")
    return ", ".join(parts)


def _dashboard_facts_block(dashboard: DataVizDashboardResponse) -> str:
    """Render the dashboard's real contents as the model's only source of numbers.

    This block used to be a literal in the prompt: six weather-affinity rows,
    three pressure bands, an hourly BPM curve and a decade ranking, none of
    which came from the corpus and none of which matched it. The model quoted
    them back with total confidence, so a fabricated table became a spoken
    answer about the user's own listening. Now the prompt can only contain
    what ``get_dashboard`` measured, and says so where it measured nothing.
    """
    lines: list[str] = []

    lines.append("1. Barometric Pressure vs BPM (`pressure_vs_bpm`):")
    if dashboard.pressure_vs_bpm:
        for p in dashboard.pressure_vs_bpm[:20]:
            lines.append(
                f"   - {p.pressure_hpa} hPa: {p.bpm} BPM, energy {p.energy} "
                f"({p.artist} — {p.track_title}, theme {p.theme_id})"
            )
    else:
        lines.append(
            "   - No barometric pressure is recorded against any play, so there "
            "is no pressure-to-tempo relationship to report. Say so if asked."
        )

    lines.append("2. Weather Affinity (`weather_affinity`):")
    if dashboard.weather_affinity_breakdown:
        for a in dashboard.weather_affinity_breakdown:
            bpm = f"{a.avg_bpm} BPM" if a.avg_bpm is not None else f"BPM {_NOT_RECORDED}"
            artist = f"top artist {a.top_artist}" if a.top_artist else f"top artist {_NOT_RECORDED}"
            lines.append(
                f"   - {a.theme_name}: {a.percentage}% "
                f"({a.scrobble_count:,} plays, {bpm}, {artist})"
            )
    else:
        lines.append(f"   - Weather affinity {_NOT_RECORDED}.")

    lines.append("3. Hourly Chronology (`hourly_solar`, UTC play counts):")
    if dashboard.hourly_solar_heatmap:
        busiest = max(dashboard.hourly_solar_heatmap, key=lambda h: h.scrobble_count)
        quietest = min(dashboard.hourly_solar_heatmap, key=lambda h: h.scrobble_count)
        lines.append(
            f"   - Busiest hour {busiest.label} ({busiest.scrobble_count:,} plays); "
            f"quietest {quietest.label} ({quietest.scrobble_count:,} plays)."
        )
        lines.append(
            "   - Per-hour counts: "
            + ", ".join(f"{h.label} {h.scrobble_count:,}" for h in dashboard.hourly_solar_heatmap)
        )
        lines.append(
            "   - The histogram carries counts only. Per-hour tempo and mood are "
            f"{_NOT_RECORDED}."
        )
    else:
        lines.append(f"   - Hourly chronology {_NOT_RECORDED}.")

    lines.append("4. Decade Sonic DNA (`decade_dna`):")
    if dashboard.decade_sonic_dna:
        for d in dashboard.decade_sonic_dna:
            lines.append(f"   - {d.decade}: {d.percentage}% ({d.track_count:,} tracks)")
    else:
        lines.append(
            "   - No release year is recorded for any track, so the catalog "
            "cannot be split by decade at all. Say so if asked."
        )

    return "\n".join(lines)


def _build_qna_system_prompt(
    dashboard: DataVizDashboardResponse,
    scrobbles: list[ScrobbleEntry],
    recent_turns: list[Any] | None = None,
    user_memories: list[Any] | None = None,
) -> str:
    """Builds the system prompt for Gemini 2.5 Flash Data Viz QnA."""
    from ..telemetry.memory_extractor import (
        format_memories_for_prompt,
        format_recent_turns_for_prompt,
    )

    scrobble_lines = [
        f"- id: '{s.id}' | artist: '{s.artist}' | track: '{s.title}' | album: '{s.album or 'Single'}' | theme: {s.weather_theme} ({s.bpm_estimate} BPM)"
        for s in scrobbles[:30]
    ]
    mem_block = format_memories_for_prompt(user_memories or [])
    hist_block = format_recent_turns_for_prompt(recent_turns or [])
    context_addendum = ""
    if mem_block:
        context_addendum += f"\n\n{mem_block}"
    if hist_block:
        context_addendum += f"\n\n{hist_block}"

    facts_block = _dashboard_facts_block(dashboard)

    return f"""You are the **BaroGroove Gemini Live 2.5 Data Viz QnA Agent**, an charismatic sonic data scientist and atmospheric DJ.
The user is viewing their Sonic Almanac Dashboard ({_kpi_line(dashboard)}).

Key Dashboard Facts — these are the ONLY figures you may quote:
{facts_block}

GROUNDING RULE (non-negotiable): every number in your answer must appear
verbatim above. If the figures needed to answer the question are listed as not
recorded, say plainly that the data is not there and name what is missing. Do
NOT estimate, interpolate, or supply a typical value. An answer that invents a
measurement is worse than no answer.

Available Almanac Scrobbles to reference in `matching_scrobbles` (choose up to 4):
{chr(10).join(scrobble_lines)}{context_addendum}

INSTRUCTIONS:
Return ONLY valid JSON matching this exact schema:
{{
  "answer_text": "Detailed, insightful 2-3 sentence data-storytelling answer citing exact numbers/BPM/percentages from the facts above.",
  "spoken_summary": "Punchy 1-2 sentence DJ/Data-Scientist spoken summary written for text-to-speech synthesis.",
  "highlight_section": "MUST be exactly one of: 'pressure_vs_bpm', 'weather_affinity', 'hourly_solar', 'decade_dna'",
  "key_metric_badge": "Short punchy badge built from a figure in the facts above, e.g. 'Petrichor • 15.2% Share'",
  "suggested_followups": ["Follow-up question 1", "Follow-up question 2", "Follow-up question 3"],
  "matching_scrobble_ids": ["list of up to 4 scrobble IDs from the list above"]
}}"""


def _deterministic_qna_fallback(
    question: str,
    dashboard: DataVizDashboardResponse,
    scrobbles: list[ScrobbleEntry],
    recent_turns: list[Any] | None = None,
    user_memories: list[Any] | None = None,
) -> DataVizQnAResponse:
    """Intelligent deterministic QnA fallback when Vertex AI is unavailable or in test environments."""
    q_lower = (question or "").lower()
    if recent_turns and len(q_lower) < 35:
        prev_q = " ".join(getattr(t, "content", "") for t in recent_turns[-2:]).lower()
        q_lower = f"{q_lower} {prev_q}"

    # Map scrobble helpers
    def _pick_tracks(keywords: list[str], fallback_slice: slice) -> list[MatchingScrobbleItem]:
        picked: list[MatchingScrobbleItem] = []
        for s in scrobbles:
            haystack = f"{s.artist} {s.title} {s.weather_theme} {' '.join(s.tags)}".lower()
            if any(k in haystack for k in keywords):
                picked.append(
                    MatchingScrobbleItem(
                        id=s.id,
                        artist=s.artist,
                        track=s.title,
                        album=s.album or "Almanac Single",
                    )
                )
                if len(picked) >= 4:
                    break
        if not picked:
            for s in scrobbles[fallback_slice][:4]:
                picked.append(
                    MatchingScrobbleItem(
                        id=s.id,
                        artist=s.artist,
                        track=s.title,
                        album=s.album or "Almanac Single",
                    )
                )
        if not picked:
            picked = list(_DEFAULT_CURATED_SCROBBLES[:4])
        return picked[:4]

    # Each branch below answers from `dashboard`, which `get_dashboard` filled
    # from the corpus. They used to answer from prose literals instead:
    # "86 BPM below 1005 hPa", "Pressure Sensitivity Index of 0.84", "the
    # 1990s, 26.5%, 42,590 scrobbles", "Petrichor at 24.0%, 38,572 plays". None
    # of those figures existed in the corpus, and this is the path that runs
    # offline and under test — so the canned numbers were what most users and
    # every test actually saw. Where the corpus holds nothing, the branch now
    # says what is missing instead of reaching for a plausible number.
    stats = dashboard.summary_stats
    affinity = dashboard.weather_affinity_breakdown
    hourly = dashboard.hourly_solar_heatmap

    def _corpus_size() -> str:
        return (
            f"{stats.total_scrobbles_analyzed:,} analysed scrobbles"
            if stats.total_scrobbles_analyzed is not None
            else "your synced scrobbles"
        )

    if any(k in q_lower for k in ["1005", "pressure", "hpa", "baromet", "drop", "storm", "falling"]):
        section = "pressure_vs_bpm"
        badge = "No pressure readings"
        answer = (
            "I cannot answer that from your almanac. No barometric pressure is "
            "recorded against any play in this corpus, so there is nothing to "
            "set your tempo against — a pressure-versus-BPM figure would be a "
            "guess, not a reading. Weather themes are recorded per track, so a "
            "question about your themes I can answer."
        )
        spoken = (
            "There is no barometric pressure recorded against your plays, so I "
            "have nothing to correlate tempo with. Ask me about your weather "
            "themes instead."
        )
        followups = [
            "Which weather theme do I listen to most?",
            "What hour of the day do I listen most?",
            "Which artist leads my rain-front listening?",
        ]
        tracks = _pick_tracks(["massive", "portishead", "gainsbourg", "petrichor"], slice(0, 4))

    elif any(k in q_lower for k in ["night", "morning", "solar", "hour", "chronology", "time", "dawn", "zenith"]):
        section = "hourly_solar"
        if hourly:
            busiest = max(hourly, key=lambda h: h.scrobble_count)
            quietest = min(hourly, key=lambda h: h.scrobble_count)
            badge = f"{busiest.label} peak • {busiest.scrobble_count:,} plays"
            answer = (
                f"Your listening peaks at {busiest.label} UTC with "
                f"{busiest.scrobble_count:,} plays, and bottoms out at "
                f"{quietest.label} with {quietest.scrobble_count:,}. That is the "
                "shape of the hour histogram across " + _corpus_size() + ". "
                "The histogram counts plays only — it does not carry which "
                "tracks they were, so I have no tempo or mood to break down by "
                "hour."
            )
            spoken = (
                f"You listen most at {busiest.label} and least at "
                f"{quietest.label}. The histogram counts plays, not tempo, so I "
                "cannot give you a BPM by hour."
            )
        else:
            badge = "No hourly histogram"
            answer = (
                "I have no hourly breakdown for you — the corpus summary carries "
                "no play histogram, so there is no time-of-day shape to report."
            )
            spoken = "There is no hourly play histogram in your almanac yet."
        followups = [
            "Which weather theme do I listen to most?",
            "Which artist leads my rain-front listening?",
            "How many scrobbles are in my almanac?",
        ]
        tracks = _pick_tracks(["chinese man", "bonobo", "air", "stromae"], slice(2, 6))

    elif any(k in q_lower for k in ["1990", "90s", "bristol", "decade", "dna", "1970", "70s", "era", "history"]):
        section = "decade_dna"
        badge = "No release years"
        answer = (
            "I cannot break your catalog down by decade. No release year is "
            "recorded for any track — the corpus knows when you first and last "
            "played something, which is when it entered your history, not when "
            "it was made. Splitting that by decade would describe your listening "
            "history, not the music's era, so I would rather not."
        )
        spoken = (
            "Your catalog has no release years, so I cannot split it by decade. "
            "I would only be guessing."
        )
        followups = [
            "Which weather theme do I listen to most?",
            "What hour of the day do I listen most?",
            "How many scrobbles are in my almanac?",
        ]
        tracks = _pick_tracks(["massive attack", "portishead", "tricky", "brassens"], slice(1, 5))

    else:
        section = "weather_affinity"
        if affinity:
            top = affinity[0]
            badge = f"{top.theme_name} • {top.percentage}%"
            runner = affinity[1] if len(affinity) > 1 else None
            second = (
                f", ahead of {runner.theme_name} at {runner.percentage}%"
                if runner is not None
                else ""
            )
            artist = (
                f" Its most-played artist in your catalog is {top.top_artist}."
                if top.top_artist
                else ""
            )
            answer = (
                f"Across {_corpus_size()}, {top.theme_name} is your leading "
                f"weather affinity at {top.percentage}% "
                f"({top.scrobble_count:,} plays){second}.{artist}"
            )
            spoken = (
                f"{top.theme_name} is your top weather affinity at "
                f"{top.percentage} percent, on {top.scrobble_count:,} plays."
            )
        else:
            badge = "No weather affinity"
            answer = (
                "I have no weather breakdown for you yet — nothing in the corpus "
                "summary records plays against a weather theme."
            )
            spoken = "Your almanac has no weather affinity data yet."
        followups = [
            "What hour of the day do I listen most?",
            "Which artist leads my rain-front listening?",
            "How many scrobbles are in my almanac?",
        ]
        tracks = _pick_tracks(["stromae", "-m-", "khruangbin", "brassens"], slice(0, 4))

    return DataVizQnAResponse(
        answer_text=answer,
        spoken_summary=spoken,
        highlight_section=section,
        key_metric_badge=badge,
        suggested_followups=followups,
        matching_scrobbles=tracks,
        model_used="gemini-2.5-flash (deterministic-telemetry-agent)",
    )


def _call_vertex_gemini_qna(
    question: str,
    system_instruction: str,
    token: str,
    project_id: str,
) -> dict[str, Any] | None:
    """Calls Vertex AI Gemini 2.5 Flash in europe-west1 for structured Data Viz QnA JSON."""
    region = os.environ.get("BG_GCP_REGION", "europe-west1")
    url = (
        f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}"
        f"/locations/{region}/publishers/google/models/gemini-2.5-flash:generateContent"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
        },
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            if resp.status_code != 200:
                logger.warning("Vertex AI DataViz QnA status %s: %s", resp.status_code, resp.text[:250])
                return None
            data = resp.json()
            usage_meta = data.get("usageMetadata") or {}
            candidates = data.get("candidates") or []
            if not candidates:
                return None
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return None
            raw_text = parts[0].get("text", "")
            parsed = json.loads(raw_text)
            parsed["_usage_metadata"] = usage_meta
            parsed["_raw_text"] = raw_text
            parsed["_http_status"] = resp.status_code
            return parsed
    except Exception as exc:
        logger.warning("Vertex AI DataViz QnA call failed (%s); using deterministic fallback", exc)
        return None


class DataVizEngine:
    """Core engine serving BaroGroove Data Visualization telemetry and Gemini Live 2.5 QnA."""

    def get_dashboard(self, user_id: str = "jpaquay") -> DataVizDashboardResponse:
        """Aggregates the scrobble corpus for `GET /api/dataviz/dashboard`.

        Every KPI is read off the corpus or left null. It used to substitute
        `160717` scrobbles and `102.4` BPM when the analytics were missing, and
        state "petrichor" and "chanson-francaise & trip-hop" unconditionally —
        the first two as measurements, the last two as findings. The corpus
        summary in fact reports 104.6 BPM and a different leading theme, so the
        substitutes were not even a stale copy of the truth.
        """
        scrobble_res = search_scrobbles(user_id=user_id, limit=100)
        scrobbles = scrobble_res.scrobbles
        analytics = scrobble_res.analytics

        affinity = _build_weather_affinity(analytics)
        genres = list(getattr(analytics, "top_genres", None) or [])
        top_genre = None
        if genres and isinstance(genres[0], dict):
            top_genre = str(genres[0].get("tag") or "").strip() or None

        total = int(getattr(analytics, "total_scrobbles", 0) or 0)
        bpm = float(getattr(analytics, "avg_bpm", 0.0) or 0.0)

        summary = SummaryStats(
            total_scrobbles_analyzed=total if total > 0 else None,
            avg_bpm=round(bpm, 1) if bpm > 0 else None,
            # The leading row of the real breakdown, not a favourite.
            dominant_weather_theme=affinity[0].theme_id if affinity else None,
            dominant_genre=top_genre,
            # No pressure reading is recorded against a play, so there is
            # nothing to correlate. See the field description.
            pressure_sensitivity_index=None,
        )

        return DataVizDashboardResponse(
            summary_stats=summary,
            pressure_vs_bpm=_build_pressure_vs_bpm_points(scrobbles),
            weather_affinity_breakdown=affinity,
            hourly_solar_heatmap=_build_hourly_solar_heatmap(),
            decade_sonic_dna=_build_decade_sonic_dna(),
        )

    async def answer_question(
        self,
        req: DataVizQnARequest,
        user_id: str = "jpaquay",
    ) -> DataVizQnAResponse:
        """Answers a natural-language or voice question about the user's Sonic Almanac telemetry."""
        import time
        import uuid
        from ..telemetry import (
            TokenUsageMetrics,
            ToolExecutionStep,
            TrajectoryRecord,
            emit_telemetry_log,
            extract_memories_from_turn,
            get_current_trace_context,
            get_telemetry_store,
        )

        t0 = time.perf_counter()
        uid = req.user_id or user_id or "demo"
        store = get_telemetry_store()

        sess = store.resolve_or_create_session(
            session_id=req.session_id,
            user_id=uid,
            client_surface="web-flutter",
            increment_turn=True,
        )
        conv = store.resolve_or_create_conversation(
            conversation_id=req.conversation_id,
            session_id=sess.session_id,
            user_id=uid,
            surface="dataviz",
        )
        recent_turns = list(conv.turns[-6:])
        user_memories, _ = store.list_memories(user_id=uid, limit=10)

        dashboard = self.get_dashboard(user_id=uid)
        scrobble_res = search_scrobbles(user_id=uid, limit=100)
        scrobbles = scrobble_res.scrobbles
        scrobble_map = {s.id: s for s in scrobbles}

        sys_prompt = _build_qna_system_prompt(
            dashboard,
            scrobbles,
            recent_turns=recent_turns,
            user_memories=user_memories,
        )

        token, project_id = _get_vertex_token()
        vertex_plan: dict[str, Any] | None = None
        usage_meta: dict[str, Any] = {}
        raw_text = ""
        http_status = 200
        execution_path = "deterministic-fallback"

        if token:
            res_call = _call_vertex_gemini_qna(
                req.question, sys_prompt, token, project_id
            )
            if isinstance(res_call, tuple):
                vertex_plan, usage_meta, raw_text, http_status = res_call
            elif isinstance(res_call, dict):
                vertex_plan = dict(res_call)
                usage_meta = vertex_plan.pop("_usage_metadata", None) or vertex_plan.get("usageMetadata") or {}
                raw_text = vertex_plan.pop("_raw_text", None) or json.dumps(vertex_plan)
                http_status = vertex_plan.pop("_http_status", 200)
            if vertex_plan:
                execution_path = "vertex-ai"

        if vertex_plan:
            section = str(vertex_plan.get("highlight_section") or "pressure_vs_bpm")
            if section not in VALID_HIGHLIGHT_SECTIONS:
                section = "pressure_vs_bpm"

            matched_ids = vertex_plan.get("matching_scrobble_ids") or []
            matched_items: list[MatchingScrobbleItem] = []
            for sid in matched_ids:
                if sid in scrobble_map:
                    s = scrobble_map[sid]
                    matched_items.append(
                        MatchingScrobbleItem(
                            id=s.id,
                            artist=s.artist,
                            track=s.title,
                            album=s.album or "Almanac Single",
                        )
                    )
            if not matched_items:
                for s in scrobbles[:4]:
                    matched_items.append(
                        MatchingScrobbleItem(
                            id=s.id,
                            artist=s.artist,
                            track=s.title,
                            album=s.album or "Almanac Single",
                        )
                    )
            if not matched_items:
                matched_items = list(_DEFAULT_CURATED_SCROBBLES[:4])

            followups = list(vertex_plan.get("suggested_followups") or [])[:3]
            while len(followups) < 3:
                followups.append("What do I listen to when barometric pressure drops below 1005 hPa?")

            res = DataVizQnAResponse(
                answer_text=str(vertex_plan.get("answer_text") or ""),
                spoken_summary=str(vertex_plan.get("spoken_summary") or ""),
                highlight_section=section,
                key_metric_badge=str(vertex_plan.get("key_metric_badge") or "Sonic Telemetry Insight"),
                suggested_followups=followups,
                matching_scrobbles=matched_items[:4],
                model_used="gemini-2.5-flash (vertex-ai)",
            )
        else:
            res = _deterministic_qna_fallback(
                req.question,
                dashboard,
                scrobbles,
                recent_turns=recent_turns,
                user_memories=user_memories,
            )
            raw_text = res.model_dump_json()
            http_status = 200
            execution_path = "deterministic-fallback"

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        tok_metrics = TokenUsageMetrics.from_vertex_or_estimate(
            usage_meta,
            prompt_text=f"{sys_prompt}\n{req.question}",
            response_text=raw_text,
        )
        trajectory_id = f"traj_{uuid.uuid4().hex[:12]}"
        t_id, s_id = get_current_trace_context()

        extracted_mems = extract_memories_from_turn(
            user_id=uid,
            prompt=req.question,
            conversation_id=conv.conversation_id,
            trajectory_id=trajectory_id,
        )

        # ``user_id`` is only consulted if the conversation went missing between
        # resolve and append; passing it means such a turn stays attributed to
        # this caller instead of minting a demo-owned conversation.
        store.append_conversation_turn(
            conversation_id=conv.conversation_id,
            role="user",
            content=req.question,
            trajectory_id=trajectory_id,
            user_id=uid,
        )
        store.append_conversation_turn(
            conversation_id=conv.conversation_id,
            role="assistant",
            content=res.answer_text,
            spoken_summary=res.spoken_summary,
            actions_executed=[{"tool": "highlight_section", "section": res.highlight_section, "badge": res.key_metric_badge}],
            trajectory_id=trajectory_id,
            user_id=uid,
        )

        traj = TrajectoryRecord(
            trajectory_id=trajectory_id,
            session_id=sess.session_id,
            conversation_id=conv.conversation_id,
            user_id=uid,
            surface="dataviz",
            endpoint="POST /api/dataviz/qna",
            latency_ms=latency_ms,
            trace_id=t_id,
            span_id=s_id,
            requested_model="gemini-2.5-flash",
            execution_path=execution_path,
            http_status=http_status,
            token_usage=tok_metrics,
            system_instruction=sys_prompt,
            user_prompt=req.question,
            raw_model_response=raw_text,
            parsed_plan={
                "highlight_section": res.highlight_section,
                "key_metric_badge": res.key_metric_badge,
            },
            tool_steps=[
                ToolExecutionStep(
                    tool_name="highlight_section",
                    label=f"Highlight Section: {res.highlight_section}",
                    detail=res.key_metric_badge,
                    status="SUCCESS",
                    latency_ms=latency_ms,
                )
            ],
            extracted_memory_ids=[m.memory_id for m in extracted_mems],
        )
        store.record_trajectory_sync(traj)
        emit_telemetry_log(traj)

        res.trajectory_id = trajectory_id
        res.session_id = sess.session_id
        res.conversation_id = conv.conversation_id
        res.user_id = uid
        res.latency_ms = latency_ms
        res.token_usage = tok_metrics.model_dump(mode="json")

        # Attach SOURCE QUERY / chart geometry / row count from the BigQuery
        # Data QnA agent so the Data Viz answer card is one round trip. Runs
        # off the event loop because `ask_data_qna` is blocking.
        import asyncio

        provenance = await asyncio.to_thread(_source_query_payload, req.question)
        if provenance:
            res.generated_sql = provenance.get("generated_sql", "")
            res.chart_spec = provenance.get("chart_spec")
            res.row_count = int(provenance.get("row_count", 0) or 0)
            res.data_engine = provenance.get("data_engine", "")
            if not res.suggested_followups:
                res.suggested_followups = list(provenance.get("suggestions") or [])[:3]
        return res


_ENGINE = DataVizEngine()


def get_dataviz_engine() -> DataVizEngine:
    """Singleton accessor for DataVizEngine."""
    return _ENGINE
