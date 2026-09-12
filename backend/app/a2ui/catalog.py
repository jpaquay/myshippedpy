"""The BAROGROOVE A2UI component catalog -- declared ONCE, as data.

This module is the contract between three things that must never drift:
  * the Flutter app, which is an A2UI renderer pointed at
    ``frontend/a2ui/catalog.json`` (generated from :data:`CATALOG`);
  * the MCP server, which emits the identical JSON;
  * :mod:`app.a2ui.surfaces`, which builds component trees against these
    definitions.

Nobody builds this UI twice.  If a property is not declared here, no surface may
emit it, and no renderer is obliged to draw it.

CATALOG SHAPE (CONFIRMED at a2ui.org, v1.0 Candidate)
-----------------------------------------------------
  * Top-level keys are strict; ``$schema``, ``$id``, ``title`` and ``description``
    are explicitly supported, alongside ``components`` and ``functions``.  Anything
    house-specific (our surfaceProperties tokens, design intent, the sky-dimension
    weighting) therefore lives under ``metadata`` -- v1.0 added static ``metadata``
    (containing ``extensions``) to ComponentDefinition and surface-level metadata
    for exactly this purpose, rather than at the top level where a strict
    validator would reject it.
  * Component discriminator rule: every entry in ``components`` must declare a
    required property ``component`` whose ``const`` equals the map key.
  * ``functions`` is a map of function name -> FunctionDefinition, with
    ``allowedCallers`` (rendererOnly | agentOnly | rendererOrAgent) and
    ``requiresUserActivation``.
  * Composition constraints ``allowedParents`` / ``allowedChildren`` use
    ``"Surface"`` as the canonical root parent type.
  * Any property holding children or a template MUST reference
    ``common_types.json#/$defs/ChildList`` -- validators use the ``$ref`` to decide
    which fields are structural links.  We follow that religiously.
"""

from __future__ import annotations

import json
from typing import Any, Final

from ..contracts import SKY_DIMS, SONIC_DIMS
from .palette import (
    SURFACE_PROPERTIES,
    THEME_IDS,
    THEME_INTENT,
    THEME_PALETTES,
)
from .protocol import A2UI_VERSION, FunctionDefinition, validate_function_payload

__all__ = [
    "CATALOG",
    "CATALOG_ID",
    "CATALOG_VERSION",
    "CATALOG_TITLE",
    "BASIC_CATALOG_ID",
    "COMPONENTS",
    "FUNCTIONS",
    "AGENT_FUNCTIONS",
    "RENDERER_FUNCTIONS",
    "FN_SELECT_THEME",
    "FN_SELECT_GENRE",
    "FN_SET_CORRIDOR_WIDTH",
    "FN_TRACK_FEEDBACK",
    "FN_OPEN_TRACK",
    "FN_FORGE",
    "FN_EXPLAIN_DIMENSION",
    "FN_OPEN_ALMANAC_ENTRY",
    "FN_REFRESH_SKY",
    "FN_RETRY",
    "FN_OPEN_TELEMETRY_TRACE",
    "FN_REFRESH_TELEMETRY",
    "FN_SCROLL_TO_TRACK",
    "FN_FORMAT_SIGNED",
    "SKY_DIM_WEIGHTS",
    "SKY_DIM_TIERS",
    "SKY_DIM_LABELS",
    "SKY_DIM_UNITS",
    "HERO_SKY_DIM",
    "ARC_ROLES",
    "catalog_json",
    "validate_action",
    "function_definition",
]

# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #

#: Catalog ids are URIs by convention -- the renderer looks the catalog up by id
#: and the agent must name exactly this id in every ``createSurface``.
CATALOG_ID: Final[str] = "https://bg.netdev.be/a2ui/catalogs/barogroove/v1"
CATALOG_VERSION: Final[str] = "1.0.0"
CATALOG_TITLE: Final[str] = "BAROGROOVE Component Catalog"

#: v1.0 allows mixing catalogs inside one surface.  We advertise the standard
#: basic catalog as a mixin so an agent may fall back to Text/Column/Button, but
#: BAROGROOVE's own surfaces never depend on it: ``Stack`` and ``Notice`` below
#: give us a self-sufficient chassis.
BASIC_CATALOG_ID: Final[str] = "https://a2ui.org/catalogs/basic/v1.0/catalog.json"


# --------------------------------------------------------------------------- #
# WHY THE SKY DIAL IS WEIGHTED, AND NOT A NINE-SPOKE RADAR CHART
# --------------------------------------------------------------------------- #
#
# A nine-armed radar plot would give every dimension the same visual authority.
# That is factually wrong about weather and about music.  Nobody's mood tracks
# 1013 hPa; it tracks the fact that it was 1022 hPa six hours ago.  The dims that
# carry the signal are DERIVATIVES -- rates of change and deviations from the
# local norm -- and the absolute state dims (how much cloud, how much rain, how
# high the sun) are context, not story.
#
# So the SkyDial is a weighted dial, not a radar:
#   * pressure_trend_6h is the HERO.  It gets the needle, the display-size
#     readout and the caption.  It is the single number that most often decides
#     whether the forge leans anxious or expansive.
#   * the other derivative dims form the inner ring at full stroke.
#   * the absolute state dims form a thin outer ring, dimmed.
# ``weight`` drives radius, stroke and label prominence in the renderer; ``tier``
# lets a small screen drop the outer ring entirely without losing the meaning.

HERO_SKY_DIM: Final[str] = "pressure_trend_6h"

SKY_DIM_TIERS: Final[dict[str, str]] = {
    "pressure_trend_6h": "hero",  # d(pressure)/dt -- the story
    "pressure_norm_deviation": "derivative",  # how far from this place's normal
    "temp_norm_deviation": "derivative",
    "gust_variance": "derivative",  # variance IS a derivative of the wind field
    "daylight_delta": "derivative",  # the season moving under you
    "golden_hour_proximity": "derivative",  # d(light quality)/dt, effectively
    "sun_elevation": "state",
    "cloud_depth": "state",
    "precip_intensity": "state",
}

SKY_DIM_WEIGHTS: Final[dict[str, float]] = {
    "pressure_trend_6h": 1.00,
    "pressure_norm_deviation": 0.80,
    "temp_norm_deviation": 0.75,
    "gust_variance": 0.70,
    "daylight_delta": 0.65,
    "golden_hour_proximity": 0.60,
    "sun_elevation": 0.35,
    "cloud_depth": 0.30,
    "precip_intensity": 0.30,
}

SKY_DIM_LABELS: Final[dict[str, str]] = {
    "pressure_trend_6h": "Pressure trend",
    "pressure_norm_deviation": "Pressure vs norm",
    "temp_norm_deviation": "Temp vs norm",
    "gust_variance": "Gust variance",
    "daylight_delta": "Daylight delta",
    "golden_hour_proximity": "Golden hour",
    "sun_elevation": "Sun elevation",
    "cloud_depth": "Cloud depth",
    "precip_intensity": "Precipitation",
}

SKY_DIM_UNITS: Final[dict[str, str]] = {
    "pressure_trend_6h": "hPa/6h",
    "pressure_norm_deviation": "hPa",
    "temp_norm_deviation": "K",
    "gust_variance": "m/s",
    "daylight_delta": "min/d",
    "golden_hour_proximity": "",
    "sun_elevation": "deg",
    "cloud_depth": "",
    "precip_intensity": "mm/h",
}

#: Fail loudly at import if contracts.py ever changes the dimension set: the dial
#: is the one place in the product that must cover all nine.
assert set(SKY_DIM_TIERS) == set(SKY_DIMS), "SkyDial weighting is out of sync with SKY_DIMS"
assert set(SKY_DIM_WEIGHTS) == set(SKY_DIMS)
assert set(SKY_DIM_LABELS) == set(SKY_DIMS)

#: The narrative arc a playlist is built along.  TrackRow renders these as badges.
ARC_ROLES: Final[tuple[str, ...]] = (
    "opener",
    "build",
    "peak",
    "descent",
    "closer",
    "body",
)


# --------------------------------------------------------------------------- #
# Function signatures -- DECLARED HERE ONCE
# --------------------------------------------------------------------------- #
#
# The builders in surfaces.py, the HTTP action endpoint and the MCP tool surface
# all import these names.  Action ids and catalog function names are deliberately
# the SAME strings, so `POST /api/surfaces/action` and a `callAgentFunction`
# carry interchangeable payloads and only one vocabulary has to be documented.

FN_SELECT_THEME: Final[str] = "barogroove.selectTheme"
FN_SELECT_GENRE: Final[str] = "barogroove.selectGenre"
FN_SET_CORRIDOR_WIDTH: Final[str] = "barogroove.setCorridorWidth"
FN_TRACK_FEEDBACK: Final[str] = "barogroove.trackFeedback"
FN_OPEN_TRACK: Final[str] = "barogroove.openTrack"
FN_FORGE: Final[str] = "barogroove.forge"
FN_EXPLAIN_DIMENSION: Final[str] = "barogroove.explainDimension"
FN_OPEN_ALMANAC_ENTRY: Final[str] = "barogroove.openAlmanacEntry"
FN_REFRESH_SKY: Final[str] = "barogroove.refreshSky"
FN_RETRY: Final[str] = "barogroove.retry"
FN_OPEN_TELEMETRY_TRACE: Final[str] = "barogroove.openTelemetryTrace"
FN_REFRESH_TELEMETRY: Final[str] = "barogroove.refreshTelemetry"

# Agent -> renderer direction (callRendererFunction).
FN_SCROLL_TO_TRACK: Final[str] = "barogroove.scrollToTrack"
# Pure client-side value formatter, usable as a Dynamic* FunctionCall.
FN_FORMAT_SIGNED: Final[str] = "barogroove.formatSigned"


def _obj(
    properties: dict[str, Any],
    required: list[str] | None = None,
    *,
    additional: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    if required:
        schema["required"] = required
    return schema


_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}


AGENT_FUNCTIONS: Final[dict[str, FunctionDefinition]] = {
    FN_SELECT_THEME: FunctionDefinition(
        description=(
            "The user picked a weather theme chip. Re-target the sonic vector "
            "toward that theme's bias and re-render the theme/genre surface."
        ),
        parameters=_obj(
            {
                "themeId": {**_STR, "enum": list(THEME_IDS)},
                "surfaceId": _STR,
            },
            ["themeId"],
        ),
        returns={"type": "object", "description": "Follow-up A2UI messages."},
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_SELECT_GENRE: FunctionDefinition(
        description=(
            "The user moved the genre corridor. This axis is ORTHOGONAL to theme: "
            "changing it must not reset the selected theme."
        ),
        parameters=_obj({"genreId": _STR, "surfaceId": _STR}, ["genreId"]),
        returns={"type": "object"},
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_SET_CORRIDOR_WIDTH: FunctionDefinition(
        description=(
            "Widen or narrow the genre corridor: 0 hugs the anchor, 1 lets the "
            "sky pull the selection anywhere inside the corridor's tags."
        ),
        parameters=_obj(
            {"genreId": _STR, "width": {**_NUM, "minimum": 0.0, "maximum": 1.0}},
            ["genreId", "width"],
        ),
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_TRACK_FEEDBACK: FunctionDefinition(
        description=(
            "Loved / skipped feedback on one track. Feeds taste affinity for the "
            "next forge; never mutates the playlist currently on screen."
        ),
        parameters=_obj(
            {
                "trackKey": _STR,
                "verdict": {**_STR, "enum": ["loved", "skipped", "cleared"]},
                "position": {**_INT, "minimum": 0},
                "playlistId": _STR,
            },
            ["trackKey", "verdict"],
        ),
        returns={"type": "object"},
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_OPEN_TRACK: FunctionDefinition(
        description="Open a track in the configured sink (Spotify / Last.fm).",
        parameters=_obj({"trackKey": _STR, "spotifyUri": _STR}, ["trackKey"]),
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_FORGE: FunctionDefinition(
        description=(
            "Commit the current theme x genre crossing and forge a playlist from "
            "the live sky vector."
        ),
        parameters=_obj({"themeId": _STR, "genreId": _STR, "length": _INT}),
        returns={"type": "object"},
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_EXPLAIN_DIMENSION: FunctionDefinition(
        description=(
            "The user tapped a spoke on the SkyDial. Return the sentence that "
            "explains how that dimension moved the sonic target. The explanation "
            "is a first-class feature, so every dimension is interrogable."
        ),
        parameters=_obj({"dimension": {**_STR, "enum": list(SKY_DIMS)}}, ["dimension"]),
        returns={"type": "object"},
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_OPEN_ALMANAC_ENTRY: FunctionDefinition(
        description="Re-open a past forge from the almanac timeline.",
        parameters=_obj({"playlistId": _STR}, ["playlistId"]),
        returns={"type": "object"},
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_REFRESH_SKY: FunctionDefinition(
        description="Re-read the sky for a coordinate pair and update the dial.",
        parameters=_obj(
            {
                "lat": {**_NUM, "minimum": -90, "maximum": 90},
                "lon": {**_NUM, "minimum": -180, "maximum": 180},
            },
            ["lat", "lon"],
        ),
        returns={"type": "object"},
        allowed_callers="rendererOrAgent",
    ),
    FN_RETRY: FunctionDefinition(
        description="Retry whatever failed on an error surface.",
        parameters=_obj({"intent": _STR}),
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_OPEN_TELEMETRY_TRACE: FunctionDefinition(
        description="Open a detailed trace inspection view for a recorded AI trajectory.",
        parameters=_obj({"trajectoryId": _STR, "surfaceId": _STR}, ["trajectoryId"]),
        returns={"type": "object"},
        allowed_callers="rendererOnly",
        requires_user_activation=True,
    ),
    FN_REFRESH_TELEMETRY: FunctionDefinition(
        description="Refresh the live AI Observability Telemetry Inspector surface.",
        parameters=_obj({"surface": _STR, "surfaceId": _STR}),
        returns={"type": "object"},
        allowed_callers="rendererOrAgent",
    ),
}

RENDERER_FUNCTIONS: Final[dict[str, FunctionDefinition]] = {
    FN_SCROLL_TO_TRACK: FunctionDefinition(
        description=(
            "Agent -> renderer: bring a track into view (used when the agent "
            "answers 'why is #7 there?' and wants the row highlighted)."
        ),
        parameters=_obj({"position": {**_INT, "minimum": 0}, "flash": _BOOL}, ["position"]),
        returns={"type": "object", "properties": {"scrolled": _BOOL}},
        allowed_callers="agentOnly",
    ),
    FN_FORMAT_SIGNED: FunctionDefinition(
        description=(
            "Client-side formatter for derivative readouts: renders a signed "
            "value with a unit and a fixed number of digits, e.g. '-9.2 hPa/6h'. "
            "Used as a Dynamic* FunctionCall so the sign convention lives in the "
            "catalog rather than in every builder."
        ),
        parameters=_obj(
            {"value": _NUM, "unit": _STR, "digits": {**_INT, "minimum": 0, "maximum": 3}},
            ["value"],
        ),
        returns=_STR,
        allowed_callers="rendererOrAgent",
    ),
}

FUNCTIONS: Final[dict[str, FunctionDefinition]] = {**AGENT_FUNCTIONS, **RENDERER_FUNCTIONS}


def function_definition(name: str) -> FunctionDefinition:
    """Look up a declared signature, raising a clear error for unknown names."""
    try:
        return FUNCTIONS[name]
    except KeyError as exc:
        raise KeyError(
            f"{name!r} is not a BAROGROOVE catalog function; known: {sorted(FUNCTIONS)}"
        ) from exc


def validate_action(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate an inbound action / callAgentFunction payload against its signature."""
    return validate_function_payload(function_definition(name), payload)


# --------------------------------------------------------------------------- #
# Component definition helpers
# --------------------------------------------------------------------------- #

_CT = "common_types.json#/$defs/"


def _dyn(kind: str, description: str, **extra: Any) -> dict[str, Any]:
    """A bindable property: literal | JSON-Pointer path | FunctionCall."""
    return {"$ref": f"{_CT}Dynamic{kind}", "description": description, **extra}


def _children(description: str, **extra: Any) -> dict[str, Any]:
    """A structural property.

    MUST be a ChildList $ref: validators identify structural links by this exact
    reference, and a raw string id would be treated as static text instead.
    """
    return {"$ref": f"{_CT}ChildList", "description": description, **extra}


def _action(description: str, function: str) -> dict[str, Any]:
    return {
        "$ref": f"{_CT}Action",
        "description": f"{description} Dispatches `{function}`.",
        "x-a2ui-function": function,
    }


def _component(
    name: str,
    *,
    purpose: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
    allowed_parents: list[str] | None = None,
    allowed_children: list[str] | None = None,
    bindable: list[str] | None = None,
    actions: list[str] | None = None,
    design: str = "",
) -> dict[str, Any]:
    """One entry of the catalog ``components`` map.

    Honours the v1.0 discriminator rule: a required ``component`` property whose
    ``const`` equals the map key.
    """
    props: dict[str, Any] = {
        "component": {"const": name, "description": f"Discriminator: always {name!r}."}
    }
    props.update(properties)
    definition: dict[str, Any] = {
        "type": "object",
        "title": name,
        "description": purpose.strip(),
        "properties": props,
        "required": ["component", *(required or [])],
        "additionalProperties": False,
        "allowedParents": allowed_parents or ["Surface", "Stack"],
        "metadata": {
            "extensions": {
                "barogroove": {
                    "purpose": purpose.strip(),
                    #: Which properties MUST come from the data model rather than
                    #: being inlined by a builder.  surfaces.py is tested against
                    #: this list.
                    "bindable": bindable or [],
                    "functions": actions or [],
                    "design": design.strip(),
                }
            }
        },
    }
    if allowed_children is not None:
        definition["allowedChildren"] = allowed_children
    return definition


_ALL_FEATURE = [
    "SkyDial",
    "ThemeChips",
    "GenreCorridor",
    "TrackList",
    "RationaleCard",
    "AlmanacTimeline",
    "TelemetryInspector",
    "Notice",
    "Stack",
]


# --------------------------------------------------------------------------- #
# The catalog components
# --------------------------------------------------------------------------- #

COMPONENTS: Final[dict[str, dict[str, Any]]] = {
    # ---------------------------------------------------------------- chrome --
    "Stack": _component(
        "Stack",
        purpose=(
            "The single layout primitive. A vertical (or horizontal) run of "
            "children with house spacing. BAROGROOVE declares its own container "
            "rather than depending on the basic catalog, so the Flutter renderer "
            "can load this catalog alone and still draw every surface."
        ),
        properties={
            "children": _children("Child components, array form or list template."),
            "direction": _dyn("String", "'vertical' (default) or 'horizontal'."),
            "gap": _dyn("String", "Spacing token: xs|sm|md|lg|xl|xxl|section."),
            "padding": _dyn("String", "Spacing token applied on all sides."),
            "tone": _dyn("String", "'canvas' | 'surface' | 'sunken'."),
            "maxWidth": _dyn("Number", "Max content width in logical pixels."),
            "heading": _dyn("String", "Optional section heading."),
            "subheading": _dyn("String", "Optional section subheading."),
            "align": _dyn("String", "'start' | 'center' | 'stretch'."),
        },
        required=["children"],
        allowed_children=_ALL_FEATURE + ["ThemeChip", "GenreOption"],
        bindable=["heading", "subheading"],
        design="Executive layout: one column, generous section gaps, capped width.",
    ),
    "Notice": _component(
        "Notice",
        purpose=(
            "Degradation and failure, stated plainly. BAROGROOVE never shows a "
            "spinner-turned-blank: if the sky read failed or a provider is down, "
            "the user is told what is missing and what still worked."
        ),
        properties={
            "tone": _dyn("String", "'info' | 'warning' | 'critical'."),
            "title": _dyn("String", "One-line summary of what happened."),
            "message": _dyn("String", "Plain-language explanation."),
            "detail": _dyn("String", "Optional technical detail, collapsed by default."),
            "degraded": _dyn(
                "StringList", "Named capabilities that are unavailable right now."
            ),
            "onRetry": _action("Retry the failed intent.", FN_RETRY),
        },
        required=["tone", "title"],
        bindable=["title", "message", "detail", "degraded"],
        actions=[FN_RETRY],
        design="Critical uses criticalSoft fill with criticalInk text; never red-on-red.",
    ),
    # ------------------------------------------------------------- feature 1 --
    "SkyDial": _component(
        "SkyDial",
        purpose=(
            "Radial reading of the nine SkyVector dimensions -- WEIGHTED, not "
            "equal. pressure_trend_6h is the hero: it owns the needle, the "
            "display-size readout and the caption. The remaining derivative "
            "dimensions form the inner ring at full stroke; the absolute state "
            "dimensions (sun elevation, cloud depth, precipitation) sit dimmed on "
            "a thin outer ring. Weather is felt as CHANGE, so the derivatives get "
            "the ink."
        ),
        properties={
            "heroDimension": _dyn("String", "Dimension id driving the needle."),
            "heroLabel": _dyn("String", "Human label for the hero dimension."),
            "heroDisplay": _dyn("String", "Formatted hero readout, e.g. '-9.2 hPa/6h'."),
            "heroValue": _dyn("Number", "Hero value normalised to -1..1 for the needle."),
            "heroCaption": _dyn("String", "Plain-language gloss: 'falling fast'."),
            "heroTone": _dyn("String", "'rising' | 'steady' | 'falling'."),
            "spokes": _children(
                "Template ChildList over the sky dimension array. One SkyDialSpoke "
                "per dimension; the template form keeps N out of the component tree."
            ),
            "observedAt": _dyn("String", "ISO-8601 observation timestamp."),
            "coordinates": _dyn("String", "Formatted lat/lon of the reading."),
            "stale": _dyn("Boolean", "True when the reading is older than the TTL."),
            "notes": _dyn("StringList", "Provider notes attached to the reading."),
            "onDimensionTap": _action(
                "Ask the agent to explain one dimension's contribution.",
                FN_EXPLAIN_DIMENSION,
            ),
            "onRefresh": _action("Re-read the sky.", FN_REFRESH_SKY),
        },
        required=["spokes"],
        bindable=[
            "heroDimension",
            "heroLabel",
            "heroDisplay",
            "heroValue",
            "heroCaption",
            "heroTone",
            "observedAt",
            "coordinates",
            "stale",
            "notes",
        ],
        actions=[FN_EXPLAIN_DIMENSION, FN_REFRESH_SKY],
        design=(
            "Needle in accent; hero readout in display type with tabular numerals; "
            "outer state ring at 45% opacity in inkSubtle. Stale readings get a "
            "gold hairline, not a red one -- stale is not an error."
        ),
    ),
    "SkyDialSpoke": _component(
        "SkyDialSpoke",
        purpose=(
            "One dimension of the dial. Rendered at a radius and stroke derived "
            "from `weight`, and dropped entirely on narrow screens when "
            "`tier` == 'state'."
        ),
        properties={
            "dimensionId": _dyn("String", "One of the nine SKY_DIMS ids."),
            "label": _dyn("String", "Short human label."),
            "display": _dyn("String", "Formatted value with unit."),
            "value": _dyn("Number", "Normalised 0..1 magnitude for the arc length."),
            "signed": _dyn("Number", "Signed -1..1 value where direction matters."),
            "unit": _dyn("String", "Unit suffix."),
            "tier": _dyn("String", "'hero' | 'derivative' | 'state'."),
            "weight": _dyn("Number", "0..1 visual prominence; drives radius and stroke."),
            "polarity": _dyn("String", "'up' | 'down' | 'flat'."),
            "onTap": _action("Explain this dimension.", FN_EXPLAIN_DIMENSION),
        },
        required=["dimensionId"],
        allowed_parents=["SkyDial"],
        bindable=["dimensionId", "label", "display", "value", "signed", "unit", "tier", "weight", "polarity"],
        actions=[FN_EXPLAIN_DIMENSION],
    ),
    # ------------------------------------------------------------- feature 2 --
    "ThemeChips": _component(
        "ThemeChips",
        purpose=(
            "AXIS 1 OF 2. Selectable chips for the eight weather themes, each "
            "carrying its own palette so the chip previews the register it will "
            "put the whole surface into. Selection fires callAgentFunction, so the "
            "chips genuinely talk back to the agent rather than mutating local "
            "state the agent never hears about."
        ),
        properties={
            "chips": _children("Template ChildList over the theme array."),
            "label": _dyn("String", "Axis label, e.g. 'Theme'."),
            "axisNote": _dyn("String", "'Axis 1 of 2 - the weather register'."),
            "helpText": _dyn("String", "One line on what the axis does."),
            "selectedThemeId": _dyn("String", "Currently selected theme id."),
        },
        required=["chips"],
        bindable=["label", "axisNote", "helpText", "selectedThemeId"],
        actions=[FN_SELECT_THEME],
        design="Chips are pill-shaped, bordered, and tint with their own accentSoft.",
    ),
    "ThemeChip": _component(
        "ThemeChip",
        purpose="One theme chip, carrying that theme's palette swatch and tagline.",
        properties={
            "themeId": _dyn("String", "Theme id."),
            "name": _dyn("String", "Display name."),
            "tagline": _dyn("String", "Six-word promise."),
            "swatchAccent": _dyn("String", "#RRGGBB accent for the swatch."),
            "swatchSoft": _dyn("String", "#RRGGBB soft fill when selected."),
            "swatchInk": _dyn("String", "#RRGGBB text colour on the soft fill."),
            "selected": _dyn("Boolean", "True when this chip is the active theme."),
            "onSelect": _action("Select this theme.", FN_SELECT_THEME),
        },
        required=["themeId", "onSelect"],
        allowed_parents=["ThemeChips"],
        bindable=["themeId", "name", "tagline", "swatchAccent", "swatchSoft", "swatchInk", "selected"],
        actions=[FN_SELECT_THEME],
    ),
    # ------------------------------------------------------------- feature 3 --
    "GenreCorridor": _component(
        "GenreCorridor",
        purpose=(
            "AXIS 2 OF 2, and visibly separate from the theme chips. The whole "
            "point of BAROGROOVE is that 'Petrichor x krautrock' is a CROSSING of "
            "two independent knobs: the sky picks the mood, you pick the "
            "vocabulary. Rendered as its own bordered panel with its own axis "
            "label and an explicit crossing readout ('Petrichor x krautrock'), so "
            "nobody mistakes genre for a sub-option of theme. Corridor width is a "
            "second-order control: how far the sky is allowed to drag the "
            "selection away from the corridor's anchor."
        ),
        properties={
            "options": _children("Template ChildList over the genre corridor array."),
            "label": _dyn("String", "Axis label, e.g. 'Genre corridor'."),
            "axisNote": _dyn("String", "'Axis 2 of 2 - independent of theme'."),
            "helpText": _dyn("String", "One line on orthogonality."),
            "selectedGenreId": _dyn("String", "Currently selected corridor id."),
            "crossingLabel": _dyn("String", "Live crossing readout: 'Petrichor x krautrock'."),
            "width": _dyn("Number", "0..1 corridor width."),
            "widthLabel": _dyn("String", "'tight' | 'balanced' | 'loose'."),
            "onWidthChange": _action("Change the corridor width.", FN_SET_CORRIDOR_WIDTH),
            "onForge": _action("Commit the crossing and forge.", FN_FORGE),
        },
        required=["options"],
        bindable=["label", "axisNote", "helpText", "selectedGenreId", "crossingLabel", "width", "widthLabel"],
        actions=[FN_SELECT_GENRE, FN_SET_CORRIDOR_WIDTH, FN_FORGE],
        design="Panel with borderStrong hairline and its own heading; never inline with chips.",
    ),
    "GenreOption": _component(
        "GenreOption",
        purpose="One genre corridor: a name, its tag vocabulary, and its anchor.",
        properties={
            "genreId": _dyn("String", "Corridor id."),
            "name": _dyn("String", "Display name."),
            "description": _dyn("String", "What this corridor sounds like."),
            "tags": _dyn("StringList", "The corridor's tag vocabulary."),
            "selected": _dyn("Boolean", "True when active."),
            "onSelect": _action("Select this corridor.", FN_SELECT_GENRE),
        },
        required=["genreId", "onSelect"],
        allowed_parents=["GenreCorridor"],
        bindable=["genreId", "name", "description", "tags", "selected"],
        actions=[FN_SELECT_GENRE],
    ),
    # ------------------------------------------------------------- feature 4 --
    "TrackList": _component(
        "TrackList",
        purpose=(
            "The ordered playlist as an ARC, not a bag. Every row carries its arc "
            "role badge (opener / build / peak / descent / closer) and its own "
            "`why`, because a track's position is a claim the engine is making and "
            "the user is entitled to see the claim. Rows come from a template "
            "ChildList over the bound track array -- the component tree stays a "
            "fixed handful of nodes no matter how long the playlist is."
        ),
        properties={
            "rows": _children("Template ChildList over the track array."),
            "title": _dyn("String", "Playlist title."),
            "subtitle": _dyn("String", "Playlist subtitle."),
            "trackCount": _dyn("Number", "Number of tracks."),
            "durationDisplay": _dyn("String", "Total running time, e.g. '58 min'."),
            "arcLegend": _dyn("StringList", "Ordered arc role legend."),
            "showWhy": _dyn("Boolean", "Show the per-track rationale line (default true)."),
        },
        required=["rows"],
        bindable=["title", "subtitle", "trackCount", "durationDisplay", "arcLegend", "showWhy"],
        actions=[FN_TRACK_FEEDBACK, FN_OPEN_TRACK],
        design="Peak row gets the gold hairline. Everything else is slate on white.",
    ),
    "TrackRow": _component(
        "TrackRow",
        purpose=(
            "One track: position, artist/title, arc role badge, and the one-line "
            "`why`. Loved / skipped are per-row actions that feed taste affinity "
            "without reordering the playlist under the user's finger."
        ),
        properties={
            "trackKey": _dyn("String", "Stable track key (artist|title)."),
            "position": _dyn("Number", "1-based position in the arc."),
            "title": _dyn("String", "Track title."),
            "artist": _dyn("String", "Artist name."),
            "display": _dyn("String", "'Artist - Title'."),
            "role": _dyn("String", "Arc role id."),
            "roleLabel": _dyn("String", "Arc role display label."),
            "why": _dyn("String", "Why this track sits at this position."),
            "durationDisplay": _dyn("String", "Formatted duration."),
            "score": _dyn("Number", "0..1 overall score."),
            "sonicDistance": _dyn("Number", "Distance from the sonic target."),
            "loved": _dyn("Boolean", "User marked this track loved."),
            "skipped": _dyn("Boolean", "User marked this track skipped."),
            "spotifyUri": _dyn("String", "Sink URI when resolved."),
            "onLove": _action("Mark loved.", FN_TRACK_FEEDBACK),
            "onSkip": _action("Mark skipped.", FN_TRACK_FEEDBACK),
            "onOpen": _action("Open in the sink.", FN_OPEN_TRACK),
        },
        required=["trackKey"],
        allowed_parents=["TrackList"],
        bindable=[
            "trackKey", "position", "title", "artist", "display", "role", "roleLabel",
            "why", "durationDisplay", "score", "sonicDistance", "loved", "skipped", "spotifyUri",
        ],
        actions=[FN_TRACK_FEEDBACK, FN_OPEN_TRACK],
    ),
    # ------------------------------------------------------------- feature 5 --
    "RationaleCard": _component(
        "RationaleCard",
        purpose=(
            "THE HERO CARD. In BAROGROOVE the explanation is the product, not a "
            "footnote: a playlist you cannot interrogate is just a shuffle with "
            "better marketing. So the rationale is rendered FIRST, at display "
            "type, above the track list, with the sky reading and the sonic moves "
            "spelled out as separate evidence lists and the confidence stated as a "
            "number. Degradation is shown here too, in the same card -- if the "
            "engine had to guess, it says so where you are already looking."
        ),
        properties={
            "headline": _dyn("String", "One sentence: what the sky did to the music."),
            "body": _dyn("String", "The paragraph. Concrete, never mystical."),
            "skyReading": _dyn("StringList", "Evidence bullets drawn from the sky vector."),
            "sonicMoves": _dyn("StringList", "What the engine did to the sonic target."),
            "tasteNote": _dyn("String", "How the user's history bent the result."),
            "confidence": _dyn("Number", "0..1 confidence in the reading."),
            "confidenceLabel": _dyn("String", "'high' | 'fair' | 'thin'."),
            "degraded": _dyn("StringList", "Capabilities that were unavailable."),
            "emphasis": _dyn("String", "'hero' (default) | 'inline' when re-shown lower down."),
            "themeName": _dyn("String", "Active theme name."),
            "genreName": _dyn("String", "Active corridor name."),
            "onExplainDimension": _action(
                "Drill into one sky dimension from the evidence list.",
                FN_EXPLAIN_DIMENSION,
            ),
        },
        required=["headline"],
        bindable=[
            "headline", "body", "skyReading", "sonicMoves", "tasteNote",
            "confidence", "confidenceLabel", "degraded", "themeName", "genreName",
        ],
        actions=[FN_EXPLAIN_DIMENSION],
        design=(
            "Gold hairline rule above the headline -- the only gold on the surface. "
            "Display type headline, body at 15/23, evidence lists at caption size in "
            "inkMuted. Confidence as a numeral, never a vague adjective alone."
        ),
    ),
    # ------------------------------------------------------------- feature 6 --
    "AlmanacTimeline": _component(
        "AlmanacTimeline",
        purpose=(
            "The retrospective: 'your rain sound', 'your first-frost record'. "
            "BAROGROOVE gets better the longer you use it, and the almanac is "
            "where that becomes visible -- past forges grouped by season, each "
            "keeping the theme tint it was born under."
        ),
        properties={
            "entries": _children("Template ChildList over the almanac entry array."),
            "title": _dyn("String", "Section title."),
            "subtitle": _dyn("String", "Section subtitle."),
            "groupBy": _dyn("String", "'season' (default) | 'year' | 'theme'."),
            "emptyMessage": _dyn("String", "Shown when there are no past forges yet."),
            "entryCount": _dyn("Number", "Number of entries."),
        },
        required=["entries"],
        bindable=["title", "subtitle", "groupBy", "emptyMessage", "entryCount"],
        actions=[FN_OPEN_ALMANAC_ENTRY],
    ),
    "AlmanacEntry": _component(
        "AlmanacEntry",
        purpose="One past forge on the timeline, tinted with the theme it was born under.",
        properties={
            "playlistId": _dyn("String", "Playlist id."),
            "title": _dyn("String", "Playlist title."),
            "subtitle": _dyn("String", "Playlist subtitle."),
            "badge": _dyn("String", "Almanac badge, e.g. 'your rain sound'."),
            "createdAt": _dyn("String", "ISO-8601 creation timestamp."),
            "createdLabel": _dyn("String", "Human date, e.g. '14 Nov 2025'."),
            "themeId": _dyn("String", "Theme id."),
            "themeName": _dyn("String", "Theme display name."),
            "genreName": _dyn("String", "Corridor display name."),
            "accent": _dyn("String", "#RRGGBB tint from that theme's palette."),
            "headline": _dyn("String", "The rationale headline from that forge."),
            "trackCount": _dyn("Number", "Track count."),
            "onOpen": _action("Re-open this forge.", FN_OPEN_ALMANAC_ENTRY),
        },
        required=["playlistId", "onOpen"],
        allowed_parents=["AlmanacTimeline"],
        bindable=[
            "playlistId", "title", "subtitle", "badge", "createdAt", "createdLabel",
            "themeId", "themeName", "genreName", "accent", "headline", "trackCount",
        ],
        actions=[FN_OPEN_ALMANAC_ENTRY],
    ),
    "TelemetryInspector": _component(
        "TelemetryInspector",
        purpose="Real-time AI Observability inspector showing trajectories, token usage, latency, and semantic memories.",
        properties={
            "entries": _children("Template ChildList over telemetry trajectory entries."),
            "title": _dyn("String", "Inspector title."),
            "subtitle": _dyn("String", "Inspector subtitle."),
            "totalAiCalls": _dyn("Number", "Total AI calls recorded."),
            "totalTokens": _dyn("Number", "Total tokens consumed."),
            "activeSessions": _dyn("Number", "Active user sessions count."),
            "storedMemories": _dyn("Number", "Stored semantic memories count."),
            "avgLatencyMs": _dyn("Number", "Average turn latency in ms."),
            "onRefresh": _action("Refresh telemetry stream.", FN_REFRESH_TELEMETRY),
        },
        required=["entries"],
        bindable=[
            "title", "subtitle", "totalAiCalls", "totalTokens",
            "activeSessions", "storedMemories", "avgLatencyMs",
        ],
        actions=[FN_REFRESH_TELEMETRY, FN_OPEN_TELEMETRY_TRACE],
    ),
    "TelemetryEntry": _component(
        "TelemetryEntry",
        purpose="One AI trajectory row in the TelemetryInspector.",
        properties={
            "trajectoryId": _dyn("String", "Trajectory identifier."),
            "surface": _dyn("String", "Originating surface (advisor, dataviz, forge, a2ui, mcp)."),
            "endpoint": _dyn("String", "Endpoint or tool name."),
            "executionPath": _dyn("String", "Execution path (vertex-ai, semantic-fallback, deterministic-fallback)."),
            "latencyMs": _dyn("Number", "Turn latency in ms."),
            "totalTokens": _dyn("Number", "Total tokens used."),
            "traceId": _dyn("String", "W3C trace ID."),
            "createdAt": _dyn("String", "ISO-8601 timestamp."),
            "status": _dyn("String", "ok | error."),
            "onOpen": _action("Inspect full trace.", FN_OPEN_TELEMETRY_TRACE),
        },
        required=["trajectoryId", "onOpen"],
        allowed_parents=["TelemetryInspector"],
        bindable=[
            "trajectoryId", "surface", "endpoint", "executionPath",
            "latencyMs", "totalTokens", "traceId", "createdAt", "status",
        ],
        actions=[FN_OPEN_TELEMETRY_TRACE],
    ),
}

#: Enforce the v1.0 discriminator rule at import time rather than at render time.
for _name, _definition in COMPONENTS.items():
    assert _definition["properties"]["component"]["const"] == _name, _name


# --------------------------------------------------------------------------- #
# The catalog document
# --------------------------------------------------------------------------- #

CATALOG: Final[dict[str, Any]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": CATALOG_ID,
    "title": CATALOG_TITLE,
    "description": (
        "BAROGROOVE - your sky has a soundtrack. A weather-driven playlist engine. "
        "One UI definition, two surfaces: the Flutter app is an A2UI renderer "
        "pointed at this catalog, and the MCP server emits the identical JSON."
    ),
    "components": COMPONENTS,
    "functions": {
        name: fn.model_dump(by_alias=True, exclude_none=True)
        for name, fn in FUNCTIONS.items()
    },
    # House-specific material lives under metadata.extensions: v1.0 keeps the
    # catalog's top-level keys strict, and it removed both the $defs/theme schema
    # and the Catalog-level primaryColor, so design tokens have no top-level home.
    "metadata": {
        "version": CATALOG_VERSION,
        "a2uiVersion": A2UI_VERSION,
        "mixinCatalogIds": [BASIC_CATALOG_ID],
        "surfaceProperties": SURFACE_PROPERTIES,
        "extensions": {
            "barogroove": {
                "tagline": "your sky has a soundtrack",
                "designIntent": (
                    "Professional, executive-level, high-contrast, clean; EHDS portal "
                    "register - Slate structure, Sky Blue action, subtle Gold accent. "
                    "Light mode default. Explicitly not neon."
                ),
                "featureComponents": [
                    "SkyDial",
                    "ThemeChips",
                    "GenreCorridor",
                    "TrackList",
                    "RationaleCard",
                    "AlmanacTimeline",
                ],
                "templateComponents": [
                    "SkyDialSpoke",
                    "ThemeChip",
                    "GenreOption",
                    "TrackRow",
                    "AlmanacEntry",
                    "TelemetryEntry",
                ],
                "chromeComponents": ["Stack", "Notice"],
                "skyDimensions": list(SKY_DIMS),
                "sonicDimensions": list(SONIC_DIMS),
                "heroSkyDimension": HERO_SKY_DIM,
                "skyDimensionTiers": dict(SKY_DIM_TIERS),
                "skyDimensionWeights": dict(SKY_DIM_WEIGHTS),
                "skyDimensionLabels": dict(SKY_DIM_LABELS),
                "skyDimensionUnits": dict(SKY_DIM_UNITS),
                "arcRoles": list(ARC_ROLES),
                "themeIds": list(THEME_IDS),
                "themePalettes": {tid: dict(THEME_PALETTES[tid]) for tid in THEME_IDS},
                "themeIntent": dict(THEME_INTENT),
                "agentFunctions": sorted(AGENT_FUNCTIONS),
                "rendererFunctions": sorted(RENDERER_FUNCTIONS),
            }
        },
    },
}


def catalog_json(*, indent: int = 2) -> str:
    """Emit the catalog file the Flutter renderer loads.

    Written to ``frontend/a2ui/catalog.json`` at build time so the Flutter worker
    never has to import Python. The test suite asserts the two are identical.
    """
    return json.dumps(CATALOG, indent=indent, ensure_ascii=False, sort_keys=False) + "\n"
