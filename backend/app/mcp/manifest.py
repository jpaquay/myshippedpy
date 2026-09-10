"""Machine-readable descriptor for the BAROGROOVE MCP server.

This module is the *contract layer*. It is deliberately free of any dependency on
the ``mcp`` package, on FastAPI request handling, or on the A2UI builders, so
that:

* ``server.py`` can import the tool argument/result models and register them,
* the REST surface and the Flutter client can negotiate capabilities against the
  exact same schemas,
* and the test-suite can assert "every tool's declared name and input schema
  match the manifest" without the SDK installed.

Everything the server advertises is derived from the pydantic v2 models below.
There is one definition of each tool's shape, and it lives here.

A note on layering, since it matters when reading ``server.py``:

    functions.py   (agent-function registry, no mcp dependency)
        v
    manifest.py    (tool models + specs, no mcp dependency)   <- you are here
        v
    server.py      (MCPServer wiring, imports mcp)

Nothing points back up.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps FastAPI out of import cost
    from fastapi import FastAPI

__all__ = [
    "SERVER_NAME",
    "SERVER_TITLE",
    "SERVER_VERSION",
    "SERVER_INSTRUCTIONS",
    "MCP_MOUNT_PATH",
    "MCP_MANIFEST_PATH",
    "A2UI_VERSION",
    "A2UI_MEDIA_TYPE",
    "A2UI_MESSAGES_META_KEY",
    "A2UI_TOOL_META_KEY",
    "A2UI_RESOURCE_SCHEME",
    "ToolError",
    "ToolResultBase",
    "GetSkyVectorInput",
    "GetSkyVectorOutput",
    "ListThemesInput",
    "ListThemesOutput",
    "ForgePlaylistInput",
    "ForgePlaylistOutput",
    "ExplainPlaylistInput",
    "ExplainPlaylistOutput",
    "SavePlaylistInput",
    "SavePlaylistOutput",
    "ToolSpec",
    "AgentFunctionSpec",
    "ServerManifest",
    "TOOL_SPECS",
    "TOOL_NAMES",
    "tool_spec",
    "tool_specs",
    "agent_function_specs",
    "a2ui_catalog_descriptor",
    "build_manifest",
    "manifest_dict",
    "manifest_json",
    "install_manifest_route",
]

# --------------------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------------------

SERVER_NAME: Final[str] = "barogroove"
SERVER_TITLE: Final[str] = "BAROGROOVE - your sky has a soundtrack"
SERVER_VERSION: Final[str] = "1.0.0"
MCP_MOUNT_PATH: Final[str] = "/mcp"
MCP_MANIFEST_PATH: Final[str] = "/mcp/manifest"

SERVER_INSTRUCTIONS: Final[str] = (
    "BAROGROOVE turns the weather over a specific point on Earth into a playlist. "
    "Read the sky first with get_sky_vector if the user is curious about conditions; "
    "call list_themes when they want to choose a mood or a genre corridor; "
    "call forge_playlist to actually build the playlist (this is the headline tool and "
    "it works with nothing but a latitude and a longitude); call explain_playlist to "
    "justify a playlist that already exists; call save_playlist to push one to a sink. "
    "Every tool also returns an A2UI v1.0 surface stream, so an A2UI-capable renderer "
    "can draw the result instead of reading it out loud."
)

# --------------------------------------------------------------------------------------
# A2UI-over-MCP binding constants
# --------------------------------------------------------------------------------------
#
# a2ui.org v1.0 states plainly that "A2UI can be carried over MCP tool calls, tool
# outputs, or resource subscriptions". The published MCP recipe (a2ui.org guides ->
# "A2UI over MCP") demonstrates the *static template* half of that: tools carry
# ``_meta.ui`` links pointing at an ``a2ui://`` resource holding a createSurface +
# updateComponents template, and the tool result then ships only an updateDataModel.
#
# BAROGROOVE generates its surfaces dynamically from live weather, so a frozen
# template resource would be a lie. We therefore ship the *whole* envelope stream in
# the tool result and advertise it in three places at once:
#
#   1. ``result.content`` -> an EmbeddedResource with mimeType A2UI_MEDIA_TYPE, whose
#      URI is ``a2ui://barogroove/surface/<surfaceId>``. This is the "Tools and
#      Embedded Resources" shape the official guide uses, and it is the placement a
#      generic A2UI-aware MCP host is most likely to look at.
#   2. ``result._meta["a2ui/messages"]`` -> the same list, unwrapped, for renderers
#      that would rather not parse a resource body.
#   3. ``result.structuredContent["a2ui"]`` -> the same list again, so a plain MCP
#      client with no A2UI support at all still receives a well-typed payload and can
#      ignore the key.
#
# UNVERIFIED: the exact reserved ``_meta`` key name the A2UI MCP binding blesses for
# an inline message stream. The spec text we could retrieve confirms that the binding
# exists and that tool outputs are a sanctioned carrier, but not the key spelling.
# ``a2ui/messages`` follows the MCP ``_meta`` convention of a slash-namespaced key and
# is safe against collision either way. Redundancy across the three placements above
# is the mitigation: at least one of them will be the one a given host reads.
A2UI_VERSION: Final[str] = "1.0"
A2UI_MEDIA_TYPE: Final[str] = "application/vnd.a2ui+json"
A2UI_MESSAGES_META_KEY: Final[str] = "a2ui/messages"
A2UI_TOOL_META_KEY: Final[str] = "a2ui"
A2UI_RESOURCE_SCHEME: Final[str] = "a2ui://barogroove"

#: Fallback catalog identity, used only when ``app.a2ui.catalog`` cannot be imported
#: (its author is a different worker and it may not have landed yet).
FALLBACK_CATALOG_ID: Final[str] = "barogroove.catalog.v1"


# --------------------------------------------------------------------------------------
# Shared result scaffolding
# --------------------------------------------------------------------------------------


class _Strict(BaseModel):
    """Base for tool inputs: reject unknown keys so a hallucinated argument is loud."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ToolError(BaseModel):
    """Structured failure. Tools return this instead of raising; see server.py."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable machine-readable error code, e.g. 'theme_not_found'.")
    message: str = Field(description="One-sentence human-readable summary. Never a stack trace.")
    detail: str | None = Field(default=None, description="Optional extra context, still not a traceback.")


class ToolResultBase(BaseModel):
    """Fields every BAROGROOVE tool result carries.

    ``a2ui`` is the surface stream: a list of A2UI v1.0 envelope dicts produced by the
    builders in ``app.a2ui.surfaces``. It is never assembled by hand.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="False when the tool degraded into an error surface.")
    tool: str = Field(description="Name of the tool that produced this result.")
    a2ui: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "A2UI v1.0 envelope stream for this result: createSurface, then "
            "updateComponents, then updateDataModel."
        ),
    )
    surface_id: str | None = Field(default=None, description="surfaceId of the primary surface in `a2ui`.")
    degraded: list[str] = Field(
        default_factory=list,
        description="Names of subsystems that fell back to defaults while producing this result.",
    )
    error: ToolError | None = Field(default=None, description="Populated iff ok is false.")


# --------------------------------------------------------------------------------------
# Tool 1: get_sky_vector
# --------------------------------------------------------------------------------------

GET_SKY_VECTOR_DESCRIPTION: Final[str] = (
    "Read the sky over one point on Earth and return BAROGROOVE's nine-dimensional sky "
    "vector: pressure_trend_6h, pressure_norm_deviation, temp_norm_deviation, "
    "sun_elevation, golden_hour_proximity, gust_variance, cloud_depth, precip_intensity "
    "and daylight_delta. Use this when the user asks what the weather *feels* like, what "
    "the barometer is doing, or why a playlist came out the way it did - it is the raw "
    "input every other BAROGROOVE decision is derived from. It does NOT build a playlist; "
    "call forge_playlist for that. Also returns an A2UI sky surface for rendering."
)


class GetSkyVectorInput(_Strict):
    lat: float = Field(ge=-90.0, le=90.0, description="Latitude in decimal degrees, WGS84.")
    lon: float = Field(ge=-180.0, le=180.0, description="Longitude in decimal degrees, WGS84.")
    scenario: str | None = Field(
        default=None,
        description=(
            "Optional named synthetic sky ('storm-front', 'high-pressure', 'golden-hour', "
            "'flat-grey', ...) used for demos and offline work. When set, no live weather "
            "provider is contacted and the reading is flagged as synthetic."
        ),
    )
    label: str | None = Field(
        default=None,
        max_length=120,
        description="Optional human place name to display on the surface, e.g. 'Brussels'.",
    )


class GetSkyVectorOutput(ToolResultBase):
    sky: dict[str, Any] = Field(default_factory=dict, description="SkyVector.as_dict(): the nine dimensions.")
    observed_at: str | None = Field(default=None, description="ISO-8601 timestamp of the observation window.")
    stale: bool = Field(default=False, description="True when the reading came from a cache or a fallback.")
    notes: list[str] = Field(default_factory=list, description="Human-readable remarks attached to the reading.")
    coordinates: dict[str, Any] = Field(default_factory=dict, description="Echo of the resolved coordinates.")


# --------------------------------------------------------------------------------------
# Tool 2: list_themes
# --------------------------------------------------------------------------------------

LIST_THEMES_DESCRIPTION: Final[str] = (
    "List BAROGROOVE's eight sonic themes and its genre corridors. A theme is a mood bias "
    "('what the sky is doing to you'); a corridor is a genre constraint ('what it should "
    "sound like'). Call this before forge_playlist whenever the user wants to pick, browse "
    "or compare moods, or when you need the exact theme_id / genre_id strings that "
    "forge_playlist accepts - do not guess those ids. Takes no arguments. Also returns an "
    "A2UI themes surface whose chips call back into the agent when tapped."
)


class ListThemesInput(_Strict):
    """No arguments. The catalogue is static; there is nothing to filter on."""


class ListThemesOutput(ToolResultBase):
    themes: list[dict[str, Any]] = Field(default_factory=list, description="The eight themes, in display order.")
    corridors: list[dict[str, Any]] = Field(default_factory=list, description="Genre corridors, including 'any'.")


# --------------------------------------------------------------------------------------
# Tool 3: forge_playlist  (the headline tool)
# --------------------------------------------------------------------------------------

FORGE_PLAYLIST_DESCRIPTION: Final[str] = (
    "THE headline tool. Build a playlist from the live sky over a latitude/longitude: read "
    "the weather, project it onto a sonic target vector, and select and order tracks. Use "
    "this whenever the user wants music for the weather, 'a playlist for right now', a "
    "soundtrack for a place, or anything of that shape. Latitude and longitude are the only "
    "required arguments - theme and genre are optional and BAROGROOVE will choose sensible "
    "ones from the sky itself if you omit them. Pass lastfm_user only if the user has "
    "volunteered a Last.fm handle. Returns the ordered tracklist, the sky reading, the sonic "
    "target, a short rationale, and an A2UI playlist surface."
)


class ForgePlaylistInput(_Strict):
    lat: float = Field(ge=-90.0, le=90.0, description="Latitude in decimal degrees, WGS84.")
    lon: float = Field(ge=-180.0, le=180.0, description="Longitude in decimal degrees, WGS84.")
    theme: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Theme id from list_themes. Omit to let BAROGROOVE pick the theme the sky "
            "implies. Do not invent ids."
        ),
    )
    genre: str = Field(
        default="any",
        max_length=64,
        description="Genre corridor id from list_themes. 'any' leaves the corridor unconstrained.",
    )
    length: int = Field(default=18, ge=4, le=60, description="Number of tracks to select. Default 18.")
    lastfm_user: str | None = Field(
        default=None,
        max_length=64,
        description="Optional Last.fm username used to bias selection toward the listener's taste.",
    )
    label: str | None = Field(default=None, max_length=120, description="Optional display name for the location.")
    seed: int | None = Field(
        default=None,
        ge=0,
        description="Optional deterministic seed. Supply it to make a forge reproducible.",
    )


class ForgePlaylistOutput(ToolResultBase):
    playlist: dict[str, Any] = Field(default_factory=dict, description="The full Playlist as JSON.")
    playlist_id: str | None = Field(default=None, description="Id to hand to explain_playlist / save_playlist.")
    track_count: int = Field(default=0, description="Number of tracks actually selected.")
    theme_id: str | None = Field(default=None, description="Theme that was used, chosen or supplied.")
    genre_id: str | None = Field(default=None, description="Genre corridor that was used.")
    sonic_target: dict[str, Any] = Field(default_factory=dict, description="SonicVector.as_dict() aimed at.")
    sky: dict[str, Any] = Field(default_factory=dict, description="SkyVector.as_dict() the forge read.")
    elapsed_ms: int = Field(default=0, description="Server-side wall time for the forge.")


# --------------------------------------------------------------------------------------
# Tool 4: explain_playlist
# --------------------------------------------------------------------------------------

EXPLAIN_PLAYLIST_DESCRIPTION: Final[str] = (
    "Explain why a playlist looks the way it does: the headline, the sky reading in plain "
    "language, the sonic moves BAROGROOVE made, any taste adjustment, and a confidence "
    "score. Use this when the user asks 'why these songs?', 'what is this based on?', or "
    "wants the reasoning behind a forge. Supply playlist_id for a playlist BAROGROOVE "
    "already made (the id from forge_playlist), or inline the playlist object itself if you "
    "are holding one that was never persisted. Exactly one of the two is required. Also "
    "returns an A2UI rationale surface."
)


class ExplainPlaylistInput(_Strict):
    playlist_id: str | None = Field(
        default=None,
        max_length=128,
        description="Id returned by forge_playlist. Preferred. Looked up in the almanac.",
    )
    playlist: dict[str, Any] | None = Field(
        default=None,
        description="A whole Playlist object, for a playlist that was never persisted. Use only if no id exists.",
    )


class ExplainPlaylistOutput(ToolResultBase):
    playlist_id: str | None = Field(default=None, description="Id of the explained playlist, when known.")
    rationale: dict[str, Any] = Field(default_factory=dict, description="The Rationale as JSON.")
    headline: str | None = Field(default=None, description="One-line summary, convenient for chat replies.")
    confidence: float | None = Field(default=None, description="Confidence in [0, 1].")


# --------------------------------------------------------------------------------------
# Tool 5: save_playlist
# --------------------------------------------------------------------------------------

SAVE_PLAYLIST_DESCRIPTION: Final[str] = (
    "Persist a playlist to an output sink - a streaming service, an M3U file, or whatever "
    "sinks this deployment has registered. Use it only after the user has explicitly asked "
    "to keep, save or export a playlist; forging does not imply saving. Requires the "
    "playlist_id from forge_playlist. Leave sink as 'auto' unless the user named a specific "
    "destination. Returns the sink's own identifiers plus an A2UI result surface."
)


class SavePlaylistInput(_Strict):
    playlist_id: str = Field(min_length=1, max_length=128, description="Id returned by forge_playlist.")
    sink: str = Field(
        default="auto",
        max_length=32,
        description="Sink kind: 'auto' picks the highest-priority configured sink. Otherwise name one.",
    )
    user_id: str | None = Field(default=None, max_length=128, description="Owner to attribute the save to.")


class SavePlaylistOutput(ToolResultBase):
    playlist_id: str | None = Field(default=None, description="Id of the saved playlist.")
    sink: str | None = Field(default=None, description="Sink kind that actually accepted the write.")
    sink_result: dict[str, Any] = Field(default_factory=dict, description="Raw SinkResult as JSON.")
    url: str | None = Field(default=None, description="Externally visible URL, when the sink produced one.")


# --------------------------------------------------------------------------------------
# Tool specs
# --------------------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """One row of the manifest's tool table."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    title: str
    description: str
    input_model: type[BaseModel] = Field(exclude=True, repr=False)
    output_model: type[ToolResultBase] = Field(exclude=True, repr=False)
    surface: str = Field(description="Which A2UI surface builder this tool drives.")
    read_only: bool = True
    idempotent: bool = True
    open_world: bool = True

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool arguments, straight from pydantic v2."""
        return self.input_model.model_json_schema(mode="validation")

    @property
    def output_schema(self) -> dict[str, Any]:
        """JSON Schema for the structured result."""
        return self.output_model.model_json_schema(mode="serialization")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": {
                "readOnlyHint": self.read_only,
                "idempotentHint": self.idempotent,
                "openWorldHint": self.open_world,
            },
            "_meta": {
                A2UI_TOOL_META_KEY: {
                    "version": A2UI_VERSION,
                    "surface": self.surface,
                    "catalogId": a2ui_catalog_descriptor()["id"],
                    "mediaType": A2UI_MEDIA_TYPE,
                    "messagesMetaKey": A2UI_MESSAGES_META_KEY,
                }
            },
        }


TOOL_SPECS: Final[tuple[ToolSpec, ...]] = (
    ToolSpec(
        name="get_sky_vector",
        title="Read the sky",
        description=GET_SKY_VECTOR_DESCRIPTION,
        input_model=GetSkyVectorInput,
        output_model=GetSkyVectorOutput,
        surface="sky",
    ),
    ToolSpec(
        name="list_themes",
        title="List themes and genre corridors",
        description=LIST_THEMES_DESCRIPTION,
        input_model=ListThemesInput,
        output_model=ListThemesOutput,
        surface="themes",
    ),
    ToolSpec(
        name="forge_playlist",
        title="Forge a playlist from the sky",
        description=FORGE_PLAYLIST_DESCRIPTION,
        input_model=ForgePlaylistInput,
        output_model=ForgePlaylistOutput,
        surface="playlist",
        # It reaches the network and writes an almanac row, so it is neither read-only
        # nor idempotent. Hosts use these hints to decide what to auto-approve.
        read_only=False,
        idempotent=False,
    ),
    ToolSpec(
        name="explain_playlist",
        title="Explain a playlist",
        description=EXPLAIN_PLAYLIST_DESCRIPTION,
        input_model=ExplainPlaylistInput,
        output_model=ExplainPlaylistOutput,
        surface="rationale",
    ),
    ToolSpec(
        name="save_playlist",
        title="Save a playlist to a sink",
        description=SAVE_PLAYLIST_DESCRIPTION,
        input_model=SavePlaylistInput,
        output_model=SavePlaylistOutput,
        surface="result",
        read_only=False,
        idempotent=True,
    ),
)

TOOL_NAMES: Final[tuple[str, ...]] = tuple(spec.name for spec in TOOL_SPECS)

_TOOL_INDEX: Final[dict[str, ToolSpec]] = {spec.name: spec for spec in TOOL_SPECS}


def tool_specs() -> tuple[ToolSpec, ...]:
    """All five tool specs, in the order the server registers them."""
    return TOOL_SPECS


def tool_spec(name: str) -> ToolSpec:
    """Look up one tool spec by name.

    Raises:
        KeyError: if ``name`` is not one of :data:`TOOL_NAMES`.
    """
    return _TOOL_INDEX[name]


# --------------------------------------------------------------------------------------
# Agent functions (renderer -> agent callbacks) and A2UI catalog identity
# --------------------------------------------------------------------------------------


class AgentFunctionSpec(BaseModel):
    """One renderer-initiated ``callAgentFunction`` the server is prepared to answer."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    argument_schema: dict[str, Any]
    aliases: list[str] = Field(default_factory=list)


def agent_function_specs() -> list[AgentFunctionSpec]:
    """Reflect the live registry in ``functions.py`` into manifest rows.

    Imported inside the function: ``functions.py`` performs its own lazy imports of the
    A2UI builders, and we would rather a broken builder module degrade a single manifest
    section than take down the whole descriptor.
    """
    try:
        from .functions import REGISTRY
    except Exception:  # pragma: no cover - defensive; functions.py has no hard deps
        return []
    return [
        AgentFunctionSpec(
            name=fn.name,
            description=fn.description,
            argument_schema=fn.argument_schema,
            aliases=list(fn.aliases),
        )
        for fn in REGISTRY.values()
    ]


def a2ui_catalog_descriptor() -> dict[str, Any]:
    """Identity of the single UI catalog both the Flutter renderer and MCP tools use.

    Lazy and forgiving: ``app.a2ui.catalog`` belongs to another module and may not be
    importable yet. A manifest that reports a fallback id is worth more than an
    ImportError at mount time.
    """
    catalog_id = FALLBACK_CATALOG_ID
    available = False
    component_count: int | None = None
    try:
        from ..a2ui import catalog as _catalog

        catalog_id = str(getattr(_catalog, "CATALOG_ID", FALLBACK_CATALOG_ID))
        raw = getattr(_catalog, "CATALOG", None)
        if isinstance(raw, dict):
            components = raw.get("components")
            if isinstance(components, (list, dict)):
                component_count = len(components)
        available = True
    except Exception:
        available = False
    return {
        "id": catalog_id,
        "version": A2UI_VERSION,
        "available": available,
        "componentCount": component_count,
        "mediaType": A2UI_MEDIA_TYPE,
    }


# --------------------------------------------------------------------------------------
# The manifest itself
# --------------------------------------------------------------------------------------


class ServerManifest(BaseModel):
    """Everything a client needs to negotiate with this server before speaking MCP."""

    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    version: str
    instructions: str
    protocol: Literal["mcp"] = "mcp"
    transport: Literal["streamable-http"] = "streamable-http"
    endpoint: str
    manifest_endpoint: str
    a2ui: dict[str, Any]
    tools: list[dict[str, Any]]
    agent_functions: list[AgentFunctionSpec]
    notes: list[str] = Field(default_factory=list)


def build_manifest() -> ServerManifest:
    """Assemble the descriptor. Pure; safe to call on every request."""
    catalog = a2ui_catalog_descriptor()
    return ServerManifest(
        name=SERVER_NAME,
        title=SERVER_TITLE,
        version=SERVER_VERSION,
        instructions=SERVER_INSTRUCTIONS,
        endpoint=MCP_MOUNT_PATH,
        manifest_endpoint=MCP_MANIFEST_PATH,
        a2ui={
            "version": A2UI_VERSION,
            "status": "release-candidate",
            "catalog": catalog,
            "mediaType": A2UI_MEDIA_TYPE,
            "messagesMetaKey": A2UI_MESSAGES_META_KEY,
            "resourceScheme": A2UI_RESOURCE_SCHEME,
            "agentToRenderer": [
                "createSurface",
                "updateComponents",
                "updateDataModel",
                "deleteSurface",
                "callRendererFunction",
                "agentFunctionResponse",
            ],
            "rendererToAgent": [
                "callAgentFunction",
                "rendererFunctionResponse",
                "actionResponse",
            ],
        },
        tools=[spec.as_dict() for spec in TOOL_SPECS],
        agent_functions=agent_function_specs(),
        notes=[
            "A2UI messages ride in three places on every tool result: an EmbeddedResource "
            f"with mimeType {A2UI_MEDIA_TYPE}, result._meta['{A2UI_MESSAGES_META_KEY}'], "
            "and structuredContent['a2ui'].",
            "UNVERIFIED: the reserved _meta key the official A2UI MCP binding uses for an "
            "inline message stream. Redundant placement is the mitigation.",
            "Tools never raise. A failure returns ok=false, a structured error, and an "
            "error surface built by build_error_surface.",
        ],
    )


def manifest_dict() -> dict[str, Any]:
    """The manifest as a plain JSON-safe dict."""
    return build_manifest().model_dump(mode="json")


def manifest_json(*, indent: int | None = 2) -> str:
    """The manifest as a JSON string, for ``curl`` and for the Flutter client's cache."""
    return json.dumps(manifest_dict(), indent=indent, sort_keys=False)


def install_manifest_route(app: FastAPI) -> None:
    """Wire ``GET /mcp/manifest`` onto the host app.

    Route ordering is load-bearing. Starlette matches routes in insertion order and the
    MCP transport is attached at ``/mcp``; if that were installed first and as a Mount,
    it would shadow ``/mcp/manifest``. ``mount_mcp`` therefore calls this *before*
    attaching the transport, and this function is idempotent so a double mount is
    harmless.
    """
    from fastapi.responses import JSONResponse

    for route in app.router.routes:
        if getattr(route, "path", None) == MCP_MANIFEST_PATH:
            return

    async def _manifest() -> JSONResponse:
        return JSONResponse(manifest_dict())

    app.add_api_route(
        MCP_MANIFEST_PATH,
        _manifest,
        methods=["GET"],
        name="mcp_manifest",
        summary="BAROGROOVE MCP server descriptor",
        description=(
            "Capability negotiation for the Flutter A2UI renderer, and a debugging aid: "
            "tool schemas, A2UI catalog identity, and the declared agent functions."
        ),
        tags=["mcp"],
        include_in_schema=True,
    )
