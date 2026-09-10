# BAROGROOVE — A2UI v1.0 layer (handoff to the MCP + Flutter workers)

**One UI definition, two surfaces.** The Flutter app is an A2UI renderer pointed at
`frontend/a2ui/catalog.json`. The MCP server emits the identical JSON produced by
`backend/app/a2ui/surfaces.py`. Nobody builds this UI twice.

## Published files

| Path | What it is |
|---|---|
| `backend/app/a2ui/protocol.py` | Typed pydantic v2 models for the A2UI v1.0 envelope + common types |
| `backend/app/a2ui/palette.py` | 8 theme palettes + base surfaceProperties tokens (all clear WCAG AA/AAA) |
| `backend/app/a2ui/catalog.py` | The component catalog + all function signatures, declared once |
| `backend/app/a2ui/surfaces.py` | **THE SINGLE SOURCE OF UI TRUTH** — the builders |
| `backend/app/a2ui/__init__.py` | Package re-exports |
| `backend/app/routes/surfaces.py` | `APIRouter(prefix="/api/surfaces", tags=["a2ui"])` |
| `frontend/a2ui/catalog.json` | Generated from `catalog_json()`; byte-identical to `CATALOG` |
| `tests/test_a2ui.py` | 71 pytest tests, no network |

NOT published: a throwaway local `backend/app/contracts.py` stub used only to test in
isolation. The real frozen `contracts.py` owns that module.

## Builder signatures (call these; do not build components yourself)

```python
from app.a2ui.surfaces import (
    build_sky_surface,        # (sky: SkyVector, *, surface_id=None) -> list[dict]
    build_themes_surface,     # (themes, corridors, *, selected_theme=None,
                              #  selected_genre=None, surface_id=None) -> list[dict]
    build_playlist_surface,   # (playlist: Playlist, *, surface_id=None) -> list[dict]
    build_rationale_surface,  # (rationale: Rationale, *, surface_id=None) -> list[dict]
    build_almanac_surface,    # (entries: Sequence[Playlist], *, surface_id=None) -> list[dict]
    build_error_surface,      # (message: str, *, detail=None, surface_id=None) -> list[dict]
)
```

Each returns an ordered stream `[createSurface, updateComponents, updateDataModel]`.
Every message is a plain JSON-ready dict with exactly one envelope key.

Round-trip follow-ups (what the agent sends BACK after a `callAgentFunction`):

```python
patch_selection(surface_id, *, theme_id=None, genre_id=None, width=None, crossing_label=None)
patch_track_feedback(surface_id, *, index: int, verdict: str)
agent_function_response(surface_id, call_id, *, result=None, error=None)
single_message(stream)   # v1.0 single-message UI instantiation: folds 3 msgs into 1 createSurface
```

## Catalog

- `CATALOG_ID = "https://bg.netdev.be/a2ui/catalogs/barogroove/v1"`
- 13 component definitions: 6 feature (`SkyDial`, `ThemeChips`, `GenreCorridor`,
  `TrackList`, `RationaleCard`, `AlmanacTimeline`), 5 list templates (`SkyDialSpoke`,
  `ThemeChip`, `GenreOption`, `TrackRow`, `AlmanacEntry`), 2 chrome (`Stack`, `Notice`).
- 12 functions. Action ids **equal** catalog function names, so HTTP `POST /api/surfaces/action`
  and an A2UI `callAgentFunction` carry interchangeable payloads.
- Design tokens live at `CATALOG["metadata"]["surfaceProperties"]` (v1.0 keeps catalog
  top-level keys strict and removed the Catalog-level `primaryColor`).
- Every component's required-binding list is at
  `CATALOG["components"][X]["metadata"]["extensions"]["barogroove"]["bindable"]`.
  Anything in that list MUST arrive as `{"path": "/pointer"}`, never inlined.

## Function vocabulary

`barogroove.selectTheme` · `selectGenre` · `setCorridorWidth` · `trackFeedback` ·
`openTrack` · `forge` · `explainDimension` · `openAlmanacEntry` · `refreshSky` · `retry`
(renderer→agent) — `scrollToTrack` · `formatSigned` (agent→renderer / client-side).

Validate any inbound payload with `catalog.validate_action(name, payload)`.

## HTTP routes

```
GET  /api/surfaces/catalog          -> the catalog JSON
GET  /api/surfaces/catalog.json     -> byte-identical generated file
GET  /api/surfaces/sky?lat=&lon=    -> sky surface stream   (+ ?single=true)
GET  /api/surfaces/themes           -> themes + corridors   (+ ?theme=&genre=&single=)
POST /api/surfaces/action           -> actionResponse / callAgentFunction endpoint
GET  /api/surfaces/health           -> catalog + fallback status
```

Responses use MIME `application/a2ui+json`. `app.sonic.themes` is imported defensively
inside the handler, so this router loads even before that module exists (it falls back to
palette-derived themes and 8 seed corridors).

## Notes for the Flutter worker

- **Two binding scopes.** Pointers on a non-template component resolve against the surface
  data model; pointers inside a template component resolve against the current list item.
  No component mixes the two — that invariant is enforced by tests.
- **UNVERIFIED wire detail:** the ChildList template object is emitted as
  `{"componentId": ..., "dataBinding": "/pointer"}`. a2ui.org's prose says "a template
  componentId and a data binding path" but does not publish the key names. If the released
  schema uses `path`, change only the alias on `ChildTemplate` in `protocol.py` — those
  strings are spelled nowhere else.
- `createSurface` requests `sendDataModel: true`, so the renderer should attach the whole
  client-side data model on callbacks.
- Light mode is the default in every theme; `colorScheme` is always `"light"`.
