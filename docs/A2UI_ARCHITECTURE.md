# A2UI v1.0 Single-Source UI & AI Observability Architecture

**One UI definition, two surfaces.** The BAROGROOVE Flutter web/mobile application is an **A2UI v1.0 renderer** pointed at `frontend/a2ui/catalog.json`. The Streamable HTTP MCP server emits the identical JSON produced by `backend/app/a2ui/surfaces.py`.

---

## 1. Published Surface Modules & Catalog

| Path | Responsibility |
| :--- | :--- |
| `backend/app/a2ui/protocol.py` | Typed Pydantic v2 models for the A2UI v1.0 envelope (`createSurface`, `updateComponents`, `updateDataModel`) |
| `backend/app/a2ui/palette.py` | 8 narrative theme palettes (`Petrichor`, `Golden Hour`, `Nordic Fog`, `Storm Front`, `Heatwave Cruise`, `Blue Hour`, `First Frost`, `Sirocco`) + WCAG AA/AAA tokens |
| `backend/app/a2ui/catalog.py` | Complete component catalog (`CATALOG_ID = "https://bg.netdev.be/a2ui/catalogs/barogroove/v1"`) + function signatures |
| `backend/app/a2ui/surfaces.py` | **Single Source of UI Truth** — surface builders shared across Flutter and MCP |
| `backend/app/telemetry/` | AI Observability, Distributed Trace Span Collector (`tracing.py`), Long-Term Memory Extractor (`memory_extractor.py`), and Telemetry Store (`store.py`) |
| `frontend/lib/a2ui/renderer.dart` | Flutter A2UI v1.0 Component & Pointer Binding Renderer |
| `frontend/lib/screens/widgets/telemetry_inspector_panel.dart` | Interactive AI Observability & Telemetry Inspector Drawer (`TelemetryInspector`) |

---

## 2. Core Surface Builders (`backend/app/a2ui/surfaces.py`)

```python
from app.a2ui.surfaces import (
    build_sky_surface,              # (sky: SkyVector, *, surface_id=None) -> list[dict]
    build_themes_surface,           # (themes, corridors, *, selected_theme=None, selected_genre=None) -> list[dict]
    build_playlist_surface,         # (playlist: Playlist, *, surface_id=None) -> list[dict]
    build_rationale_surface,        # (rationale: Rationale, *, surface_id=None) -> list[dict]
    build_almanac_surface,          # (entries: Sequence[Playlist], *, surface_id=None) -> list[dict]
    build_telemetry_surface,        # (traces, memories, metrics, *, surface_id=None) -> list[dict]
    build_error_surface,            # (message: str, *, detail=None, surface_id=None) -> list[dict]
)
```

Every builder returns an ordered stream `[createSurface, updateComponents, updateDataModel]` (or a folded single-message payload via `single_message(stream)`).

---

## 3. Interactive Client Experiences

### 3.1 Three-Mode Atmospheric Synthesis Console (`atmospheric_cursors_console.dart`)
Allows users to steer the 9×7 Sonic Transfer Matrix across three progressive control tiers:
- **Guided Mode (Happy Path)**: One-click atmospheric presets (*Collapsing Front*, *Golden Hour Ridge*, *Nordic Fog*).
- **Adjustable Mode (Easy)**: Intuitive sliders for Temperature (°C), Daylight Intensity (%), and Sky Kelvin Color Temperature.
- **Expert Mode**: Direct derivative controls for Barometric Pressure (hPa), 6-Hour Pressure Trend (`hPa/6h`), and Target Tempo BPM Lock, complete with live Sonic Vector response bars (`valence`, `energy`, `tempo`, `acousticness`, `density`, `grit`, `spatiality`).

### 3.2 Three-Pillar Almanac & Data Viz Live QnA Studio (`almanac_screen.dart` & `dataviz_screen.dart`)
1. **Pillar 1 — FORGED DAYLISTS**: Responsive 2-column weather-forged sets (*your rain sound*, *your first-frost record*, *your falling barometer*) with Weather Theme badges, track preview chips, Play in Set, and Ridge Regression feedback loops.
2. **Pillar 2 — SCROBBLE CATALOG & SONIC DNA**: Sub-millisecond inspection of the `160,717` historical scrobbles (`2012–2026`) with single-row Weather Mood & Genre filter chips, interactive track seed toggles, and floating Forge Daylist seed bar.
3. **Pillar 3 — COHORT MATCHER**: Universal cross-check engine comparing any pasted playlist or song list against the 15-year scrobble cohort with side-by-side Familiarity Donut Chart, Track-by-Track match list, and 1-click Seed Fresh Discoveries button.
4. **Data Viz & Gemini Live QnA Studio (`dataviz_screen.dart`)**: Connected directly via 1-click header shortcut (`Data Viz & Live QnA →`) and main-menu destination, providing 4 interactive telemetry charts (`Pressure vs BPM/Energy`, `Weather Affinity`, `24h Solar Chronology`, `Decade Sonic DNA`), Gemini Live 2.5 Voice/Text QnA, and BigQuery Conversational Data QnA (`geminidataanalytics.googleapis.com/v1beta`) with on-demand custom chart synthesis (`horizontal_bar`, `bar`, `donut`, `line`).

### 3.3 AI Observability & Telemetry Inspector (`TelemetryInspectorPanel`)
Provides real-time transparency into every AI agent call (Gemini Live 2.5 Voice/Text Advisor, BigQuery Data QnA, and Forge Reranker):
- **Live Span Waterfall**: Inspects latency, token consumption, and tool invocations per turn.
- **Long-Term Memory Bank**: Shows extracted user musical preferences, weather affinities, and Sonic Matrix deltas.
- **System Health & Evaluation Metrics**: Displays cache hit ratios, BigQuery bytes billed (`$0.00` guardrail enforcement), and upstream health.
