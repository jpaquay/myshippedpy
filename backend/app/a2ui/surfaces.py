"""THE SINGLE SOURCE OF UI TRUTH for BAROGROOVE.

Two consumers call into this module and must get byte-identical output:
  * the MCP server, which returns these streams as ``application/a2ui+json``;
  * the HTTP router in :mod:`app.routes.surfaces`, which the Flutter web client
    fetches when it is not talking MCP.

Neither of them builds UI. They call a builder, get a list of A2UI envelopes, and
forward it. That is the whole architecture: one UI definition, two surfaces.

THE TWO RULES EVERY BUILDER OBEYS
---------------------------------
1. STRUCTURE lives in components; DATA lives in the data model.
   A builder never inlines a value into the component tree. Every property the
   catalog marks bindable is emitted as ``{"path": "/pointer"}`` and the value
   goes into ``updateDataModel``. This is not pedantry -- it is what makes the
   round trips cheap. When the user taps a theme chip, the agent answers with a
   single ``updateDataModel`` patching ``/themes/selectedThemeId``: no component
   churn, no re-layout, no flicker. See :func:`patch_selection`.
2. LISTS use the ChildList template form.
   A fifty-track playlist emits ONE ``TrackRow`` template component, not fifty.
   Inside the template, pointers resolve relative to the current item.

ORDERING
--------
Every builder returns ``[createSurface, updateComponents, updateDataModel]`` in
that order. The renderer paints the moment it parses the component with
``"id": "root"``, so shipping components before data gives progressive rendering:
skeleton first, values a beat later.

Callers that would rather pay one round trip than three can fold the stream with
:func:`single_message` -- that is A2UI v1.0's *single-message UI instantiation*
("Components and initial data model states can be defined directly within the
createSurface parameters"). We do NOT make it the default because progressive
rendering is worth more on a mobile connection than one saved frame, but the
HTTP route exposes it as ``?single=true`` and the MCP tools use it when they have
to return a single content block.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final
from uuid import uuid4

from ..contracts import (
    SKY_DIMS,
    GenreCorridor,
    Playlist,
    Rationale,
    SkyVector,
    Theme,
)
from .catalog import (
    ARC_ROLES,
    CATALOG_ID,
    FN_EXPLAIN_DIMENSION,
    FN_FORGE,
    FN_OPEN_ALMANAC_ENTRY,
    FN_OPEN_TRACK,
    FN_REFRESH_SKY,
    FN_RETRY,
    FN_SELECT_GENRE,
    FN_SELECT_THEME,
    FN_SET_CORRIDOR_WIDTH,
    FN_TRACK_FEEDBACK,
    HERO_SKY_DIM,
    SKY_DIM_LABELS,
    SKY_DIM_TIERS,
    SKY_DIM_UNITS,
    SKY_DIM_WEIGHTS,
)
from .palette import THEME_PALETTES, surface_properties_for
from .protocol import (
    Action,
    AgentFunctionResponse,
    ChildTemplate,
    Component,
    CreateSurface,
    UpdateComponents,
    UpdateDataModel,
    bind,
    collapse_to_single_message,
    envelope,
    stream,
)

__all__ = [
    "build_sky_surface",
    "build_themes_surface",
    "build_playlist_surface",
    "build_rationale_surface",
    "build_almanac_surface",
    "build_error_surface",
    "patch_selection",
    "patch_track_feedback",
    "agent_function_response",
    "single_message",
    "new_surface_id",
    "SURFACE_KINDS",
    "ROLE_LABELS",
    "ALMANAC_BADGES",
]

SURFACE_KINDS: Final[tuple[str, ...]] = (
    "sky",
    "themes",
    "playlist",
    "rationale",
    "almanac",
    "error",
)


def new_surface_id(kind: str) -> str:
    """``surfaceId`` must be globally unique for the renderer's lifetime.

    Surfaces are keyed by this id, so a collision silently overwrites a live
    surface. uuid4 rather than a counter: the MCP server and the HTTP router are
    separate processes handing ids to the same renderer.
    """
    return f"bg-{kind}-{uuid4().hex[:12]}"


def single_message(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold a builder stream into one ``createSurface`` (v1.0 single-message UI)."""
    return collapse_to_single_message(messages)


# --------------------------------------------------------------------------- #
# Display helpers (presentation only -- no domain logic lives here)
# --------------------------------------------------------------------------- #

#: Display ranges used ONLY to normalise a raw dimension onto the dial. They are
#: not claims about physics and they are not used for scoring -- the sonic engine
#: owns that. Values are clamped, so an extraordinary reading pins the arc rather
#: than breaking the layout.
_DIM_RANGE: Final[dict[str, tuple[float, float]]] = {
    "pressure_trend_6h": (-12.0, 12.0),
    "pressure_norm_deviation": (-25.0, 25.0),
    "temp_norm_deviation": (-12.0, 12.0),
    "sun_elevation": (-18.0, 90.0),
    "golden_hour_proximity": (0.0, 1.0),
    "gust_variance": (0.0, 15.0),
    "cloud_depth": (0.0, 1.0),
    "precip_intensity": (0.0, 20.0),
    "daylight_delta": (-5.0, 5.0),
}

#: Dimensions whose SIGN carries meaning; the dial draws these either side of
#: centre instead of from zero.
_SIGNED_DIMS: Final[frozenset[str]] = frozenset(
    {
        "pressure_trend_6h",
        "pressure_norm_deviation",
        "temp_norm_deviation",
        "daylight_delta",
    }
)

_DIM_DIGITS: Final[dict[str, int]] = {
    "golden_hour_proximity": 2,
    "cloud_depth": 2,
    "sun_elevation": 0,
}

ROLE_LABELS: Final[dict[str, str]] = {
    "opener": "Opener",
    "build": "Build",
    "peak": "Peak",
    "descent": "Descent",
    "closer": "Closer",
    "body": "Body",
}

ALMANAC_BADGES: Final[dict[str, str]] = {
    "petrichor": "your rain sound",
    "first_frost": "your first-frost record",
    "high_pressure_blue": "your clear-sky record",
    "gale_warning": "your storm record",
    "golden_hour": "your golden-hour record",
    "blanket_grey": "your overcast record",
    "heat_shimmer": "your heatwave record",
    "long_dusk": "your long-dusk record",
}


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _normalise(dim: str, value: float) -> float:
    """0..1 magnitude for the arc length."""
    low, high = _DIM_RANGE[dim]
    if dim in _SIGNED_DIMS:
        span = max(abs(low), abs(high)) or 1.0
        return round(_clamp(abs(value) / span, 0.0, 1.0), 4)
    span = (high - low) or 1.0
    return round(_clamp((value - low) / span, 0.0, 1.0), 4)


def _signed(dim: str, value: float) -> float:
    """-1..1 for dimensions where direction is the story."""
    low, high = _DIM_RANGE[dim]
    span = max(abs(low), abs(high)) or 1.0
    if dim in _SIGNED_DIMS:
        return round(_clamp(value / span, -1.0, 1.0), 4)
    return _normalise(dim, value)


def _polarity(dim: str, value: float) -> str:
    if dim not in _SIGNED_DIMS:
        return "flat"
    low, high = _DIM_RANGE[dim]
    epsilon = max(abs(low), abs(high)) * 0.05
    if value > epsilon:
        return "up"
    if value < -epsilon:
        return "down"
    return "flat"


def _format_dim(dim: str, value: float) -> str:
    digits = _DIM_DIGITS.get(dim, 1)
    unit = SKY_DIM_UNITS.get(dim, "")
    sign = "+" if (dim in _SIGNED_DIMS and value > 0) else ""
    number = f"{sign}{value:.{digits}f}"
    return f"{number} {unit}".strip()


def _hero_caption(trend: float) -> tuple[str, str]:
    """(caption, tone) for the hero pressure trend -- the one number that matters."""
    if trend <= -6.0:
        return "falling fast", "falling"
    if trend <= -2.0:
        return "falling", "falling"
    if trend < 2.0:
        return "steady", "steady"
    if trend < 6.0:
        return "rising", "rising"
    return "rising fast", "rising"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _human_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    return str(value or "")


def _duration_display(duration_ms: int | None) -> str:
    if not duration_ms:
        return ""
    total = int(duration_ms // 1000)
    if total >= 3600:
        return f"{total // 3600}h {(total % 3600) // 60:02d}m"
    if total >= 600:
        return f"{total // 60} min"
    return f"{total // 60}:{total % 60:02d}"


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "fair"
    return "thin"


def _width_label(width: float) -> str:
    if width <= 0.33:
        return "tight"
    if width <= 0.66:
        return "balanced"
    return "loose"


def _latlon(coordinates: Any) -> tuple[float, float]:
    """Pull (lat, lon) out of whatever we were handed.

    The frozen contract says ``SkyVector.coordinates`` is a ``Coordinates``
    model, but this module is also fed hand-built payloads from the MCP tools
    and from tests, where a bare ``(lat, lon)`` pair is the natural thing to
    write. Accept both rather than making every caller care.
    """
    if coordinates is None:
        return (0.0, 0.0)
    lat = getattr(coordinates, "latitude", None)
    lon = getattr(coordinates, "longitude", None)
    if lat is not None and lon is not None:
        return (float(lat), float(lon))
    try:
        lat, lon = tuple(coordinates)[:2]  # type: ignore[misc]
        return (float(lat), float(lon))
    except Exception:  # pragma: no cover - defensive; coordinates are optional
        return (0.0, 0.0)


def _coords(coordinates: Any) -> str:
    if coordinates is None:
        return ""
    lat, lon = _latlon(coordinates)
    label = getattr(coordinates, "label", None)
    rendered = f"{lat:.3f}, {lon:.3f}"
    return f"{label} ({rendered})" if label else rendered


# --------------------------------------------------------------------------- #
# Stream assembly
# --------------------------------------------------------------------------- #


def _assemble(
    surface_id: str,
    components: list[Component],
    data: dict[str, Any],
    *,
    theme_id: str | None = None,
    send_data_model: bool = True,
) -> list[dict[str, Any]]:
    """The canonical three-message stream.

    ``sendDataModel`` is requested so that when a chip or a row calls back, the
    renderer attaches the whole client-side data model -- the agent can then
    answer a ``callAgentFunction`` without holding per-surface state.
    """
    return stream(
        [
            CreateSurface(
                surface_id=surface_id,
                catalog_id=CATALOG_ID,
                surface_properties=surface_properties_for(theme_id),
                send_data_model=send_data_model,
            ),
            UpdateComponents(surface_id=surface_id, components=components),
            UpdateDataModel(surface_id=surface_id, path="/", contents=data),
        ]
    )


def _root(children: list[str], **props: Any) -> Component:
    """The one component whose id is ``root``.

    ``createSurface`` implicitly instantiates the reserved ``Surface`` container
    with ``{"child": "root"}``, so exactly one component per surface must be
    called ``root`` or the renderer has nothing to attach.
    """
    return Component(
        id="root",
        component="Stack",
        properties={
            "children": children,
            "direction": "vertical",
            "gap": "section",
            "padding": "xl",
            "tone": "canvas",
            "maxWidth": 960,
            "align": "stretch",
            **props,
        },
    )


# --------------------------------------------------------------------------- #
# 1. Sky surface
# --------------------------------------------------------------------------- #


def build_sky_surface(sky: SkyVector, *, surface_id: str | None = None) -> list[dict[str, Any]]:
    """The SkyDial: nine dimensions, weighted so the derivatives dominate.

    The dial is built from ONE spoke template bound to ``/sky/dimensions`` rather
    than nine components, so adding a dimension is a data change, not a UI change.
    The hero (``pressure_trend_6h``) is lifted out of the array into its own
    scalar bindings because it is drawn completely differently -- needle, display
    type, caption -- and pretending it is just another spoke would be a lie about
    how the engine reads weather.
    """
    sid = surface_id or new_surface_id("sky")
    values = sky.as_dict()
    hero_value = float(values[HERO_SKY_DIM])
    caption, tone = _hero_caption(hero_value)

    dimensions: list[dict[str, Any]] = [
        {
            "dimensionId": dim,
            "label": SKY_DIM_LABELS[dim],
            "display": _format_dim(dim, float(values[dim])),
            "value": _normalise(dim, float(values[dim])),
            "signed": _signed(dim, float(values[dim])),
            "unit": SKY_DIM_UNITS[dim],
            "tier": SKY_DIM_TIERS[dim],
            "weight": SKY_DIM_WEIGHTS[dim],
            "polarity": _polarity(dim, float(values[dim])),
        }
        # Ordered by visual weight, not by declaration order: the renderer walks
        # the array outward from the hero.
        for dim in sorted(SKY_DIMS, key=lambda d: -SKY_DIM_WEIGHTS[d])
    ]

    components = [
        _root(["skyDial"], heading=bind("/sky/heading"), subheading=bind("/sky/subheading")),
        Component(
            id="skyDial",
            component="SkyDial",
            accessibility={
                "label": bind("/sky/accessibilityLabel"),
                "live": "polite",
            },
            properties={
                "heroDimension": bind("/sky/heroDimension"),
                "heroLabel": bind("/sky/heroLabel"),
                "heroDisplay": bind("/sky/heroDisplay"),
                "heroValue": bind("/sky/heroValue"),
                "heroCaption": bind("/sky/heroCaption"),
                "heroTone": bind("/sky/heroTone"),
                "observedAt": bind("/sky/observedAt"),
                "coordinates": bind("/sky/coordinates"),
                "stale": bind("/sky/stale"),
                "notes": bind("/sky/notes"),
                # ChildList template form: one component, N rendered spokes.
                "spokes": ChildTemplate(component_id="skySpoke", data_binding="/sky/dimensions"),
                "onRefresh": Action(
                    action=FN_REFRESH_SKY,
                    context={"lat": bind("/sky/lat"), "lon": bind("/sky/lon")},
                ),
                # NB: the per-dimension tap lives on SkyDialSpoke, not here, so that
                # every pointer on this component resolves in the SURFACE scope and
                # every pointer on the spoke resolves in the ITEM scope. Mixing the
                # two scopes on one component is the classic way to produce a
                # binding that works in one renderer and silently fails in another.
            },
        ),
        # Template component. Pointers inside resolve relative to the list item.
        Component(
            id="skySpoke",
            component="SkyDialSpoke",
            properties={
                "dimensionId": bind("/dimensionId"),
                "label": bind("/label"),
                "display": bind("/display"),
                "value": bind("/value"),
                "signed": bind("/signed"),
                "unit": bind("/unit"),
                "tier": bind("/tier"),
                "weight": bind("/weight"),
                "polarity": bind("/polarity"),
                "onTap": Action(
                    action=FN_EXPLAIN_DIMENSION,
                    context={"dimension": bind("/dimensionId")},
                ),
            },
        ),
    ]

    lat, lon = _latlon(getattr(sky, "coordinates", None))
    data = {
        "sky": {
            "heading": "Your sky right now",
            "subheading": "Nine dimensions. The ones that are moving matter most.",
            "accessibilityLabel": (
                f"Sky dial. {SKY_DIM_LABELS[HERO_SKY_DIM]} "
                f"{_format_dim(HERO_SKY_DIM, hero_value)}, {caption}."
            ),
            "heroDimension": HERO_SKY_DIM,
            "heroLabel": SKY_DIM_LABELS[HERO_SKY_DIM],
            "heroDisplay": _format_dim(HERO_SKY_DIM, hero_value),
            "heroValue": _signed(HERO_SKY_DIM, hero_value),
            "heroCaption": caption,
            "heroTone": tone,
            "observedAt": _iso(getattr(sky, "observed_at", None)),
            "coordinates": _coords(getattr(sky, "coordinates", None)),
            "lat": float(lat),
            "lon": float(lon),
            "stale": bool(getattr(sky, "stale", False)),
            "notes": list(getattr(sky, "notes", []) or []),
            "dimensions": dimensions,
        }
    }
    return _assemble(sid, components, data)


# --------------------------------------------------------------------------- #
# 2. Themes x genre corridors -- two orthogonal axes
# --------------------------------------------------------------------------- #


def build_themes_surface(
    themes: Sequence[Theme],
    corridors: Sequence[GenreCorridor],
    *,
    selected_theme: str | None = None,
    selected_genre: str | None = None,
    surface_id: str | None = None,
) -> list[dict[str, Any]]:
    """Two knobs, drawn as two panels, because they really are independent.

    Theme is the weather register; the genre corridor is the vocabulary. Putting
    them in one control would imply krautrock is a flavour of Petrichor. It is
    not -- "Petrichor x krautrock" is a CROSSING, and the surface says so
    literally via ``crossingLabel``.

    Both axes fire ``callAgentFunction`` on selection (``barogroove.selectTheme``
    / ``barogroove.selectGenre``). Nothing is decided client-side: the agent owns
    the crossing and answers with a data-model patch.
    """
    sid = surface_id or new_surface_id("themes")

    theme_items: list[dict[str, Any]] = []
    for theme in themes:
        palette = THEME_PALETTES.get(theme.id, {})
        # The Theme's own palette wins where it has one; the house palette fills
        # the gaps so a chip can never render with an undefined colour.
        swatch = {**palette, **(theme.palette or {})}
        theme_items.append(
            {
                "themeId": theme.id,
                "name": theme.name,
                "tagline": theme.tagline,
                "swatchAccent": swatch.get("accent", "#0369A1"),
                "swatchSoft": swatch.get("accentSoft", "#E0F2FE"),
                "swatchInk": swatch.get("accentInk", "#0C4A6E"),
                "selected": theme.id == selected_theme,
            }
        )

    genre_items: list[dict[str, Any]] = [
        {
            "genreId": corridor.id,
            "name": corridor.name,
            "description": corridor.description,
            "tags": list(corridor.tags or []),
            "selected": corridor.id == selected_genre,
        }
        for corridor in corridors
    ]

    theme_name = next(
        (t["name"] for t in theme_items if t["selected"]), "no theme yet"
    )
    genre_name = next(
        (g["name"] for g in genre_items if g["selected"]), "no corridor yet"
    )
    width = next(
        (float(c.width) for c in corridors if c.id == selected_genre), 0.5
    )

    components = [
        _root(
            ["themeChips", "genreCorridor"],
            heading=bind("/page/heading"),
            subheading=bind("/page/subheading"),
        ),
        Component(
            id="themeChips",
            component="ThemeChips",
            properties={
                "label": bind("/themes/label"),
                "axisNote": bind("/themes/axisNote"),
                "helpText": bind("/themes/helpText"),
                "selectedThemeId": bind("/themes/selectedThemeId"),
                "chips": ChildTemplate(component_id="themeChip", data_binding="/themes/items"),
            },
        ),
        Component(
            id="themeChip",
            component="ThemeChip",
            accessibility={"label": bind("/name"), "description": bind("/tagline")},
            properties={
                "themeId": bind("/themeId"),
                "name": bind("/name"),
                "tagline": bind("/tagline"),
                "swatchAccent": bind("/swatchAccent"),
                "swatchSoft": bind("/swatchSoft"),
                "swatchInk": bind("/swatchInk"),
                "selected": bind("/selected"),
                # The round trip: chip -> callAgentFunction -> updateDataModel.
                "onSelect": Action(
                    action=FN_SELECT_THEME,
                    context={"themeId": bind("/themeId")},
                    send_data_model=False,
                ),
            },
        ),
        Component(
            id="genreCorridor",
            component="GenreCorridor",
            properties={
                "label": bind("/genres/label"),
                "axisNote": bind("/genres/axisNote"),
                "helpText": bind("/genres/helpText"),
                "selectedGenreId": bind("/genres/selectedGenreId"),
                "crossingLabel": bind("/genres/crossingLabel"),
                "width": bind("/genres/width"),
                "widthLabel": bind("/genres/widthLabel"),
                "options": ChildTemplate(component_id="genreOption", data_binding="/genres/items"),
                "onWidthChange": Action(
                    action=FN_SET_CORRIDOR_WIDTH,
                    context={
                        "genreId": bind("/genres/selectedGenreId"),
                        "width": bind("/genres/width"),
                    },
                ),
                "onForge": Action(
                    action=FN_FORGE,
                    context={
                        "themeId": bind("/themes/selectedThemeId"),
                        "genreId": bind("/genres/selectedGenreId"),
                    },
                ),
            },
        ),
        Component(
            id="genreOption",
            component="GenreOption",
            accessibility={"label": bind("/name"), "description": bind("/description")},
            properties={
                "genreId": bind("/genreId"),
                "name": bind("/name"),
                "description": bind("/description"),
                "tags": bind("/tags"),
                "selected": bind("/selected"),
                "onSelect": Action(
                    action=FN_SELECT_GENRE,
                    context={"genreId": bind("/genreId")},
                    send_data_model=False,
                ),
            },
        ),
    ]

    data = {
        "page": {
            "heading": "Cross two axes",
            "subheading": "The sky picks the mood. You pick the vocabulary.",
        },
        "themes": {
            "label": "Theme",
            "axisNote": "Axis 1 of 2 — the weather register",
            "helpText": "Each theme biases the sonic target and tints the surface.",
            "selectedThemeId": selected_theme,
            "items": theme_items,
        },
        "genres": {
            "label": "Genre corridor",
            "axisNote": "Axis 2 of 2 — independent of theme",
            "helpText": "The corridor is a vocabulary, not a mood. It never overrides the sky.",
            "selectedGenreId": selected_genre,
            "crossingLabel": f"{theme_name} × {genre_name}",
            "width": width,
            "widthLabel": _width_label(width),
            "items": genre_items,
        },
    }
    return _assemble(sid, components, data, theme_id=selected_theme)


# --------------------------------------------------------------------------- #
# 3. Playlist -- rationale first, then the arc
# --------------------------------------------------------------------------- #


def _rationale_data(rationale: Rationale, *, theme_name: str = "", genre_name: str = "") -> dict[str, Any]:
    confidence = float(getattr(rationale, "confidence", 0.0) or 0.0)
    return {
        "headline": rationale.headline,
        "body": rationale.body,
        "skyReading": list(rationale.sky_reading or []),
        "sonicMoves": list(rationale.sonic_moves or []),
        "tasteNote": rationale.taste_note,
        "confidence": round(confidence, 3),
        "confidenceLabel": _confidence_label(confidence),
        "degraded": list(rationale.degraded or []),
        "themeName": theme_name,
        "genreName": genre_name,
    }


def _rationale_component(component_id: str = "rationale", *, root: str = "/rationale") -> Component:
    """The hero card, bound to ``/rationale``.

    Same component definition wherever it appears; only ``emphasis`` changes.
    """
    return Component(
        id=component_id,
        component="RationaleCard",
        accessibility={"label": bind(f"{root}/headline"), "live": "polite"},
        properties={
            "headline": bind(f"{root}/headline"),
            "body": bind(f"{root}/body"),
            "skyReading": bind(f"{root}/skyReading"),
            "sonicMoves": bind(f"{root}/sonicMoves"),
            "tasteNote": bind(f"{root}/tasteNote"),
            "confidence": bind(f"{root}/confidence"),
            "confidenceLabel": bind(f"{root}/confidenceLabel"),
            "degraded": bind(f"{root}/degraded"),
            "themeName": bind(f"{root}/themeName"),
            "genreName": bind(f"{root}/genreName"),
            "emphasis": "hero",
            "onExplainDimension": Action(
                action=FN_EXPLAIN_DIMENSION,
                context={"dimension": bind("/selectedDimension")},
            ),
        },
    )


def build_playlist_surface(
    playlist: Playlist, *, surface_id: str | None = None
) -> list[dict[str, Any]]:
    """The forged playlist.

    ORDER IS THE ARGUMENT: the RationaleCard comes FIRST, above the tracks. A
    playlist you cannot interrogate is a shuffle with better marketing, so the
    explanation is the hero and the track list is the evidence underneath it.
    Every row then repeats the claim at its own scale via ``why``.

    The whole list is one ``TrackRow`` template bound to ``/playlist/tracks`` --
    fifty tracks cost four components, and marking one loved is a one-field
    ``updateDataModel`` at ``/playlist/tracks/<i>`` (see
    :func:`patch_track_feedback`).
    """
    sid = surface_id or new_surface_id("playlist")

    rows: list[dict[str, Any]] = []
    for index, scored in enumerate(playlist.tracks):
        track = scored.track
        rows.append(
            {
                "index": index,
                # Carried on the item so every pointer inside the TrackRow
                # template resolves in the item scope, never the surface scope.
                "playlistId": playlist.id,
                "trackKey": track.key,
                "position": int(scored.position or index + 1),
                "title": track.title,
                "artist": track.artist,
                "display": track.display,
                "role": scored.role,
                "roleLabel": ROLE_LABELS.get(scored.role, scored.role.title()),
                "why": scored.why,
                "durationDisplay": _duration_display(track.duration_ms),
                "score": round(float(scored.score or 0.0), 3),
                "sonicDistance": round(float(scored.sonic_distance or 0.0), 3),
                "loved": False,
                "skipped": False,
                "spotifyUri": track.spotify_uri,
            }
        )

    components = [
        # Rationale before tracks: the hero card leads the surface.
        _root(["rationale", "trackList"]),
        _rationale_component(),
        Component(
            id="trackList",
            component="TrackList",
            properties={
                "title": bind("/playlist/title"),
                "subtitle": bind("/playlist/subtitle"),
                "trackCount": bind("/playlist/trackCount"),
                "durationDisplay": bind("/playlist/durationDisplay"),
                "arcLegend": bind("/playlist/arcLegend"),
                "showWhy": bind("/playlist/showWhy"),
                "rows": ChildTemplate(component_id="trackRow", data_binding="/playlist/tracks"),
            },
        ),
        Component(
            id="trackRow",
            component="TrackRow",
            accessibility={"label": bind("/display"), "description": bind("/why")},
            properties={
                "trackKey": bind("/trackKey"),
                "position": bind("/position"),
                "title": bind("/title"),
                "artist": bind("/artist"),
                "display": bind("/display"),
                "role": bind("/role"),
                "roleLabel": bind("/roleLabel"),
                "why": bind("/why"),
                "durationDisplay": bind("/durationDisplay"),
                "score": bind("/score"),
                "sonicDistance": bind("/sonicDistance"),
                "loved": bind("/loved"),
                "skipped": bind("/skipped"),
                "spotifyUri": bind("/spotifyUri"),
                "onLove": Action(
                    action=FN_TRACK_FEEDBACK,
                    context={
                        "trackKey": bind("/trackKey"),
                        "verdict": "loved",
                        "position": bind("/position"),
                        "playlistId": bind("/playlistId"),
                    },
                ),
                "onSkip": Action(
                    action=FN_TRACK_FEEDBACK,
                    context={
                        "trackKey": bind("/trackKey"),
                        "verdict": "skipped",
                        "position": bind("/position"),
                        "playlistId": bind("/playlistId"),
                    },
                ),
                "onOpen": Action(
                    action=FN_OPEN_TRACK,
                    context={"trackKey": bind("/trackKey"), "spotifyUri": bind("/spotifyUri")},
                ),
            },
        ),
    ]

    data = {
        "playlist": {
            "id": playlist.id,
            "title": playlist.title,
            "subtitle": playlist.subtitle,
            "themeId": playlist.theme_id,
            "genreId": playlist.genre_id,
            "createdAt": _iso(playlist.created_at),
            "trackCount": len(playlist.tracks),
            "durationDisplay": _duration_display(playlist.duration_ms),
            "arcLegend": [ROLE_LABELS[role] for role in ARC_ROLES],
            "showWhy": True,
            "tracks": rows,
        },
        "rationale": _rationale_data(
            playlist.rationale,
            theme_name=playlist.theme_id,
            genre_name=playlist.genre_id,
        ),
        "selectedDimension": HERO_SKY_DIM,
    }
    return _assemble(sid, components, data, theme_id=playlist.theme_id)


# --------------------------------------------------------------------------- #
# 4. Rationale on its own
# --------------------------------------------------------------------------- #


def build_rationale_surface(
    rationale: Rationale, *, surface_id: str | None = None
) -> list[dict[str, Any]]:
    """The hero card standing alone -- used by the MCP "explain" tool and by any
    client that wants the reasoning without the tracks."""
    sid = surface_id or new_surface_id("rationale")
    components = [
        _root(["rationale"], heading=bind("/page/heading")),
        _rationale_component(),
    ]
    data = {
        "page": {"heading": "Why this playlist"},
        "rationale": _rationale_data(rationale),
        "selectedDimension": HERO_SKY_DIM,
    }
    return _assemble(sid, components, data)


# --------------------------------------------------------------------------- #
# 5. Almanac
# --------------------------------------------------------------------------- #


def build_almanac_surface(
    entries: Sequence[Playlist], *, surface_id: str | None = None
) -> list[dict[str, Any]]:
    """Past forges, each keeping the tint it was born under.

    The badge ("your rain sound", "your first-frost record") is the point: the
    almanac is how BAROGROOVE shows that it has been paying attention.
    """
    sid = surface_id or new_surface_id("almanac")

    items: list[dict[str, Any]] = []
    for entry in entries:
        palette = THEME_PALETTES.get(entry.theme_id, {})
        items.append(
            {
                "playlistId": entry.id,
                "title": entry.title,
                "subtitle": entry.subtitle,
                "badge": ALMANAC_BADGES.get(entry.theme_id, "a past forge"),
                "createdAt": _iso(entry.created_at),
                "createdLabel": _human_date(entry.created_at),
                "themeId": entry.theme_id,
                "themeName": entry.theme_id.replace("_", " ").title(),
                "genreName": entry.genre_id.replace("_", " ").title(),
                "accent": palette.get("accent", "#0369A1"),
                "headline": entry.rationale.headline if entry.rationale else "",
                "trackCount": len(entry.tracks),
            }
        )

    components = [
        _root(["almanac"]),
        Component(
            id="almanac",
            component="AlmanacTimeline",
            properties={
                "title": bind("/almanac/title"),
                "subtitle": bind("/almanac/subtitle"),
                "groupBy": bind("/almanac/groupBy"),
                "emptyMessage": bind("/almanac/emptyMessage"),
                "entryCount": bind("/almanac/entryCount"),
                "entries": ChildTemplate(
                    component_id="almanacEntry", data_binding="/almanac/entries"
                ),
            },
        ),
        Component(
            id="almanacEntry",
            component="AlmanacEntry",
            accessibility={"label": bind("/title"), "description": bind("/badge")},
            properties={
                "playlistId": bind("/playlistId"),
                "title": bind("/title"),
                "subtitle": bind("/subtitle"),
                "badge": bind("/badge"),
                "createdAt": bind("/createdAt"),
                "createdLabel": bind("/createdLabel"),
                "themeId": bind("/themeId"),
                "themeName": bind("/themeName"),
                "genreName": bind("/genreName"),
                "accent": bind("/accent"),
                "headline": bind("/headline"),
                "trackCount": bind("/trackCount"),
                "onOpen": Action(
                    action=FN_OPEN_ALMANAC_ENTRY,
                    context={"playlistId": bind("/playlistId")},
                ),
            },
        ),
    ]

    data = {
        "almanac": {
            "title": "Your almanac",
            "subtitle": "Every sky you have forged, kept in the light it was made in.",
            "groupBy": "season",
            "emptyMessage": "No forges yet. Read the sky and make the first one.",
            "entryCount": len(items),
            "entries": items,
        }
    }
    return _assemble(sid, components, data)


# --------------------------------------------------------------------------- #
# 6. Error / degradation
# --------------------------------------------------------------------------- #


def build_error_surface(
    message: str, *, detail: str | None = None, surface_id: str | None = None
) -> list[dict[str, Any]]:
    """Failure, stated plainly, with a retry.

    Still the full three-message stream so the caller's handling is uniform;
    :func:`single_message` collapses it for transports that want one blob.
    """
    sid = surface_id or new_surface_id("error")
    components = [
        _root(["notice"]),
        Component(
            id="notice",
            component="Notice",
            accessibility={"label": bind("/error/title"), "live": "assertive"},
            properties={
                "tone": "critical",
                "title": bind("/error/title"),
                "message": bind("/error/message"),
                "detail": bind("/error/detail"),
                "degraded": bind("/error/degraded"),
                "onRetry": Action(action=FN_RETRY, context={"intent": bind("/error/intent")}),
            },
        ),
    ]
    data = {
        "error": {
            "title": "The sky did not answer",
            "message": message,
            "detail": detail,
            "degraded": [],
            "intent": "forge",
        }
    }
    return _assemble(sid, components, data, send_data_model=False)


# --------------------------------------------------------------------------- #
# Round-trip follow-ups: what the agent sends BACK after a callAgentFunction
# --------------------------------------------------------------------------- #


def patch_selection(
    surface_id: str,
    *,
    theme_id: str | None = None,
    genre_id: str | None = None,
    width: float | None = None,
    crossing_label: str | None = None,
) -> list[dict[str, Any]]:
    """Answer a theme/genre selection with data-model patches only.

    This is the payoff for keeping data out of the component tree: a chip tap
    costs two tiny ``updateDataModel`` messages and zero component rebuilds. The
    chips' ``selected`` flags live in the item array, so we patch the array's
    selection pointer and let the renderer re-resolve the bindings.
    """
    messages: list[dict[str, Any]] = []
    if theme_id is not None:
        messages.append(
            envelope(
                UpdateDataModel(
                    surface_id=surface_id,
                    path="/themes",
                    contents={"selectedThemeId": theme_id},
                )
            )
        )
    if genre_id is not None or width is not None or crossing_label is not None:
        contents: dict[str, Any] = {}
        if genre_id is not None:
            contents["selectedGenreId"] = genre_id
        if width is not None:
            contents["width"] = round(float(width), 3)
            contents["widthLabel"] = _width_label(float(width))
        if crossing_label is not None:
            contents["crossingLabel"] = crossing_label
        messages.append(
            envelope(
                UpdateDataModel(surface_id=surface_id, path="/genres", contents=contents)
            )
        )
    return messages


def patch_track_feedback(
    surface_id: str, *, index: int, verdict: str
) -> list[dict[str, Any]]:
    """Answer loved/skipped with a one-field patch at the row's own pointer."""
    contents = {
        "loved": verdict == "loved",
        "skipped": verdict == "skipped",
    }
    return [
        envelope(
            UpdateDataModel(
                surface_id=surface_id,
                path=f"/playlist/tracks/{int(index)}",
                contents=contents,
            )
        )
    ]


def agent_function_response(
    surface_id: str,
    call_id: str,
    *,
    result: Any | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The typed answer to a renderer-initiated ``callAgentFunction``."""
    return envelope(
        AgentFunctionResponse(
            surface_id=surface_id, call_id=call_id, result=result, error=error
        )
    )
