# BAROGROOVE Documentation Hub (`docs/`)

Welcome to the official technical documentation for **BAROGROOVE** (`bg.netdev.be`) — the derivative-first atmospheric soundtracking engine, 15-year musical Almanac warehouse, and conversational AI data studio.

---

## 📚 Architecture & Deep-Dive Guides

| Document | Scope & Highlights | Key Endpoints & Modules |
| :--- | :--- | :--- |
| **[15-Year Scrobble Dual-Store & Two-Tier OLAP Cache](./ALMANAC_DUAL_STORE_AND_CACHE.md)** | Full 15-year scrobble hydration (`160,717` plays), Firestore OLTP + BigQuery OLAP (`netdev-firebase.barogroove_almanac.scrobbles`) Dual-Store architecture, Two-Tier L1/L2 caching (`0.4ms` latency), and `$0.00` query cost guardrails. | `backend/app/almanac/scrobbles.py`<br/>`GET /api/almanac/scrobbles`<br/>`GET /api/almanac/scrobbles/cache/stats` |
| **[Playlist & Song Cohort Analysis Cross-Check Engine](./PLAYLIST_COHORT_ANALYSIS.md)** | Universal playlist/song input parser (Spotify URLs, Last.fm URLs, M3U, raw tracklists), 4-tier scrobble cohort classification (`Obsession`, `Heavy Rotation`, `Discovery`, `Unheard`), Sonic DNA affinity scoring, and custom-painted Donut & 15-Year Timeline charts. | `POST /api/almanac/playlist-cohort-check`<br/>`frontend/lib/screens/almanac_screen.dart` |
| **[BigQuery Conversational Data QnA Agent & On-Demand Graph Studio](./BIGQUERY_DATA_QNA_AGENT.md)** | Integration with Google Cloud `geminidataanalytics.googleapis.com/v1beta` Conversational Analytics API over BigQuery, Two-Tier QnA caching, Local OLAP fallback synthesizer, On-Demand Graph Studio (`horizontal_bar`, `bar`, `donut`, `line`), and interactive Flutter canvas charts. | `backend/app/almanac/data_qna.py`<br/>`POST /api/almanac/qna/ask`<br/>`POST /api/almanac/qna/stream`<br/>`POST /api/almanac/qna/graph-on-demand` |
| **[A2UI v1.0 Single-Source UI & Telemetry Inspector](./A2UI_ARCHITECTURE.md)** | Single-source Python-to-Flutter/MCP UI catalog (`backend/app/a2ui/`), custom renderers (`SkyDial`, `AtmosphericCursorsConsole`, `TelemetryInspector`), and real-time AI observability tracing. | `backend/app/a2ui/catalog.py`<br/>`backend/app/telemetry/`<br/>`frontend/lib/a2ui/` |

---

## 🏛️ High-Level System Architecture

```mermaid
flowchart TB
    subgraph Upstreams["External Upstreams & Warehouses"]
        OM["Open-Meteo API<br/><i>Hourly pressure derivatives (past_days=7)</i>"]
        LFM["Last.fm API<br/><i>110+ Tag Lexicon & Taste Graph Oracle</i>"]
        SPOT["Spotify OAuth PKCE<br/><i>Identity & Playlist Write Sink</i>"]
        FS[("Firestore OLTP<br/>scrobbles_jerome<br/>scrobbles_meta/jerome_summary")]
        BQ[("BigQuery OLAP Warehouse<br/>netdev-firebase.barogroove_almanac.scrobbles<br/>160,717 rows · DATE Partitioned")]
        GDA["Google Cloud Gemini Data Analytics API<br/>geminidataanalytics.googleapis.com/v1beta"]
    end

    subgraph Engine["BAROGROOVE Core Engine (FastAPI)"]
        SKY["SkyVector (9-dim)<br/>Pressure 6h Trend & Norm Deviations"]
        MTX["Sonic Transfer Matrix (9×7)<br/>Tunable Atmospheric-to-Sonic Mapping"]
        FORGE["Forge Engine<br/>Candidate Rerank · Arc Shaping · Rationale"]
        CACHE["Two-Tier OLAP & QnA Cache<br/>L1 Memory (TTL) + L2 Disk JSON"]
        COHORT["Playlist Cohort Cross-Check Engine<br/>Obsession · Heavy Rotation · Discovery · Unheard"]
        QNA["Conversational Data QnA & Graph Synthesizer<br/>Live SQL + Auto Chart Spec Generator"]
    end

    subgraph Surfaces["Unified Client Surfaces"]
        FLUT["Flutter Web & PWA App<br/>4-Tab Almanac · 3-Mode Atmospheric Console<br/>Custom Canvas Charts · Gemini Live 2.5 Voice"]
        MCP["Streamable HTTP MCP Server<br/>5 Native Tools Emitting Identical A2UI Surfaces"]
    end

    OM --> SKY --> MTX --> FORGE
    LFM --> FORGE
    FORGE --> SPOT
    FS <--> CACHE
    BQ <--> CACHE
    GDA <--> QNA
    CACHE <--> COHORT
    CACHE <--> QNA
    FORGE --> FLUT
    COHORT --> FLUT
    QNA --> FLUT
    FORGE --> MCP
```

---

## ⚡ Quick Verification & Test Commands

```bash
# Run full backend unit & integration test suite (861 tests, 0 network dependency)
pytest

# Check BigQuery QnA Agent & OLAP Cache status
curl -s http://localhost:8000/api/almanac/qna/status | jq

# Ask a natural language question with auto-generated chart spec
curl -s -X POST http://localhost:8000/api/almanac/qna/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are my top 10 most played artists of all time?"}' | jq

# Synthesize an on-demand chart (donut, horizontal_bar, bar, line)
curl -s -X POST http://localhost:8000/api/almanac/qna/graph-on-demand \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Show my scrobble breakdown by decade", "chart_type": "donut"}' | jq

# Cross-check a playlist or song list against the 15-year scrobble cohort
curl -s -X POST http://localhost:8000/api/almanac/playlist-cohort-check \
  -H "Content-Type: application/json" \
  -d '{"playlist_input": "Radiohead - Weird Fishes/Arpeggi\nBoards of Canada - Roygbiv\nAphex Twin - Xtal"}' | jq
```
