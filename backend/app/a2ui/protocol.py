"""Typed A2UI v1.0 protocol models for BAROGROOVE ("your sky has a soundtrack").

WHY THIS FILE EXISTS
--------------------
BAROGROOVE defines its UI exactly once, as data. The Flutter app is an A2UI
renderer pointed at :mod:`app.a2ui.catalog`; the MCP server emits the very same
JSON produced by :mod:`app.a2ui.surfaces`. Nothing in this project is allowed to
hand-roll an A2UI wire dict -- you build a model here and dump it with
``model_dump(by_alias=True, exclude_none=True)``. That is the only way two
independent renderers stay byte-identical.

SPEC PROVENANCE (checked against https://a2ui.org, A2UI v1.0 Candidate)
-----------------------------------------------------------------------
CONFIRMED at a2ui.org:
  * Apache-2.0, Google's agent->UI protocol; official renderers exist for
    Flutter (via the GenUI SDK), React, Lit/Web Components and Angular.
  * "every message streamed by the agent must be a JSON object containing
    exactly one of the following keys: createSurface, updateComponents,
    updateDataModel, deleteSurface, callRendererFunction, agentFunctionResponse".
  * v1.0 adds bidirectional typed RPC: ``callRendererFunction`` (agent->renderer,
    answered by ``rendererFunctionResponse``) and ``callAgentFunction``
    (renderer->agent, answered by ``agentFunctionResponse``); results/errors ride
    a shared ``FunctionResponse`` payload.
  * v1.0 adds single-message UI instantiation: "Components and initial data model
    states can be defined directly within the createSurface parameters."
  * v1.0 renames ``theme`` -> ``surfaceProperties`` on ``createSurface`` and in
    the capabilities exchange; custom primary brand colours are no longer part of
    the surface schema.
  * The protocol reserves the component name ``Surface``: "The createSurface
    message implicitly creates Surface with \"child\": \"root\", and you cannot
    modify Surface using updateComponents."  Hence every surface we emit must
    contain a component whose id is literally ``root``.
  * Renderers "render immediately upon parsing a valid root component (ID root)".
  * ``catalogId`` on ``createSurface`` is optional and acts as the surface default;
    ``catalogId`` may also appear on ComponentCommon and on a FunctionCall.
  * Dynamic types (DynamicString / DynamicNumber / DynamicBoolean /
    DynamicStringList) accept a literal, a JSON-Pointer path, or a FunctionCall.
  * ChildList supports an ``array`` of ComponentId references or an ``object``
    template "for generating children from a data binding list (requires a
    template componentId and a data binding path)".
  * AccessibilityAttributes carries label / description / live
    ("off"|"polite"|"assertive") / hidden, with additionalProperties false.
  * Catalog FunctionDefinition gained ``allowedCallers``
    (rendererOnly | agentOnly | rendererOrAgent, default rendererOnly) and
    ``requiresUserActivation``.
  * Transport is not mandated; there are HTTP request/response, streaming, A2A and
    MCP bindings.  The A2A binding uses MIME type ``application/a2ui+json``.
  * The client->server user-interaction dispatch is ``action`` (it replaces v0.9's
    ``userAction``) and carries ``context`` with resolved paths; the client
    attaches the whole data model when ``sendDataModel`` was requested.

UNVERIFIED (best reading; each is flagged again at its definition):
  * The exact field names inside the ChildList *template object*.  a2ui.org's prose
    says "a template componentId and a data binding path"; the renderer guide says
    "iterate over data arrays at path and render templates specified by
    componentId".  We emit ``{"componentId": ..., "dataBinding": ...}``.  If the
    published schema turns out to use ``path``, only :class:`ChildTemplate` needs
    to change -- nothing else in BAROGROOVE spells those keys out.
  * The exact envelope key and payload of the v1.0 client->server RPC.  Secondary
    sources describe it as ``actionResponse``; a2ui.org's renderer checklist calls
    the user-interaction dispatch ``action``.  We model BOTH and accept either.
  * The precise nesting of a FunctionCall used as a Dynamic* value.  We emit
    ``{"functionCall": {"name": ..., "args": {...}}}``.
  * The shape of the inline ``Action`` object on an interactive component
    (``{"action": <id>, "context": {...}}``, carried over from v0.9.1).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_serializer,
    model_validator,
)

__all__ = [
    "A2UI_VERSION",
    "A2UI_MIME_TYPE",
    "A2UI_SPEC_URL",
    "ROOT_COMPONENT_ID",
    "SURFACE_COMPONENT",
    "AGENT_ENVELOPE_KEYS",
    "RENDERER_ENVELOPE_KEYS",
    "DataBinding",
    "FunctionCall",
    "FunctionCallBinding",
    "DynamicString",
    "DynamicNumber",
    "DynamicBoolean",
    "DynamicStringList",
    "DynamicValue",
    "ChildTemplate",
    "ChildList",
    "AccessibilityAttributes",
    "Action",
    "Component",
    "FunctionResponse",
    "FunctionDefinition",
    "CreateSurface",
    "UpdateComponents",
    "UpdateDataModel",
    "DeleteSurface",
    "CallRendererFunction",
    "AgentFunctionResponse",
    "CallAgentFunction",
    "RendererFunctionResponse",
    "ActionResponse",
    "AgentMessage",
    "RendererMessage",
    "envelope",
    "stream",
    "to_wire",
    "bind",
    "call",
    "collapse_to_single_message",
    "envelope_key",
    "validate_envelope",
    "validate_stream",
    "find_root",
    "validate_function_payload",
    "A2UIProtocolError",
]

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

A2UI_VERSION: str = "1.0"
A2UI_MIME_TYPE: str = "application/a2ui+json"
A2UI_SPEC_URL: str = "https://a2ui.org/specification/v1.0/"

#: The protocol reserves the component type name "Surface" for the implicit
#: top-level container created by ``createSurface``.  It always has
#: ``{"child": "root"}`` and MUST NOT be sent through ``updateComponents``.
SURFACE_COMPONENT: str = "Surface"

#: ...which is precisely why exactly one component in every surface we emit has
#: this id.  The renderer starts painting the moment it parses it.
ROOT_COMPONENT_ID: str = "root"

AGENT_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {
        "createSurface",
        "updateComponents",
        "updateDataModel",
        "deleteSurface",
        "callRendererFunction",
        "agentFunctionResponse",
    }
)

#: Renderer -> agent.  ``action`` is the v1.0 rename of v0.9's ``userAction``;
#: ``actionResponse`` is the v1.0 client->server RPC.  UNVERIFIED which of the two
#: names the final schema settles on, so we accept both.
RENDERER_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {
        "callAgentFunction",
        "rendererFunctionResponse",
        "actionResponse",
        "action",
    }
)


class A2UIProtocolError(ValueError):
    """Raised when a message or stream is not a legal A2UI v1.0 payload."""


# --------------------------------------------------------------------------- #
# Base model: spec-shaped camelCase, aliases everywhere, no stray nulls
# --------------------------------------------------------------------------- #


class _Wire(BaseModel):
    """Base for everything that goes on the wire.

    ``populate_by_name`` lets Python callers use snake_case while serialisation
    always emits the camelCase alias the spec asks for.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        ser_json_exclude_none=True,
    )

    def wire(self) -> dict[str, Any]:
        """Spec-shaped JSON dict for this object."""
        return self.model_dump(by_alias=True, exclude_none=True)


def to_wire(value: Any) -> Any:
    """Recursively convert models / containers into spec-shaped JSON values.

    Used where a property bag is typed ``dict[str, Any]`` but its values are
    real models (``DataBinding``, ``ChildTemplate``, ``Action``, ...).  This is
    the single place where a model becomes a dict, so no hand-rolled dict ever
    escapes into the API.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return {str(k): to_wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_wire(v) for v in value]
    return value


# --------------------------------------------------------------------------- #
# Data binding primitives
# --------------------------------------------------------------------------- #


class DataBinding(_Wire):
    """A JSON-Pointer reference into the surface's data model.

    Wire form: ``{"path": "/playlist/title"}``.

    CONFIRMED: a2ui.org describes Dynamic* as accepting "a path string (JSON
    Pointer)", and every official example resolves it as the object form
    ``{"path": "..."}`` ("Resolve simplified bound values (either literals or
    {\"path\": \"...\"})").  We emit the object form.
    """

    path: str = Field(description="RFC 6901 JSON Pointer into the data model.")

    @field_validator("path")
    @classmethod
    def _pointer_shaped(cls, v: str) -> str:
        if not v.startswith("/") and v != "":
            raise ValueError(f"JSON Pointer must start with '/': {v!r}")
        return v


class FunctionCall(_Wire):
    """A catalog-declared function invocation used as a value or an event target."""

    name: str
    args: dict[str, Any] | None = None
    #: v1.0 allows mixing catalogs inside one surface, so a call may name its own.
    catalog_id: str | None = Field(default=None, alias="catalogId")

    @model_serializer(mode="plain")
    def _ser(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name}
        if self.args is not None:
            out["args"] = to_wire(self.args)
        if self.catalog_id is not None:
            out["catalogId"] = self.catalog_id
        return out


class FunctionCallBinding(_Wire):
    """A Dynamic* value computed by a function call.

    UNVERIFIED nesting: we emit ``{"functionCall": {"name": ..., "args": {...}}}``.
    """

    function_call: FunctionCall = Field(alias="functionCall")


#: The three legal shapes of any bindable property.
DynamicString = Union[str, DataBinding, FunctionCallBinding]
DynamicNumber = Union[float, int, DataBinding, FunctionCallBinding]
DynamicBoolean = Union[bool, DataBinding, FunctionCallBinding]
DynamicStringList = Union[list[str], DataBinding, FunctionCallBinding]
DynamicValue = Union[
    str, float, int, bool, list[str], DataBinding, FunctionCallBinding
]


def bind(path: str) -> DataBinding:
    """Sugar: ``bind("/sky/pressureTrend6h")``."""
    return DataBinding(path=path)


def call(name: str, /, **args: Any) -> FunctionCall:
    """Sugar: ``call("barogroove.selectTheme", themeId=bind("/id"))``."""
    return FunctionCall(name=name, args=dict(args) if args else None)


# --------------------------------------------------------------------------- #
# Children
# --------------------------------------------------------------------------- #


class ChildTemplate(_Wire):
    """The ChildList *object* form: generate N children from a bound list.

    CONFIRMED (prose): "object: A template for generating children from a data
    binding list (requires a template componentId and a data binding path)".

    UNVERIFIED (key names): the published JSON Schema for the object form is not
    quoted anywhere we could reach.  We emit::

        {"componentId": "trackRow", "dataBinding": "/playlist/tracks"}

    If the schema turns out to name the second key ``path``, change ONLY the alias
    below -- BAROGROOVE never writes those strings anywhere else.

    Inside the template component, data bindings are resolved relative to the
    current list item (``/title`` means "this item's title").
    """

    component_id: str = Field(alias="componentId")
    data_binding: str = Field(alias="dataBinding")

    @field_validator("data_binding")
    @classmethod
    def _pointer_shaped(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"ChildList template dataBinding must be a JSON Pointer: {v!r}")
        return v


#: Either a static array of component ids, or a template object.
ChildList = Union[list[str], ChildTemplate]


class AccessibilityAttributes(_Wire):
    """WAI-ARIA-ish attributes attached via ComponentCommon (additionalProperties: false)."""

    label: DynamicString | None = None
    description: DynamicString | None = None
    live: Literal["off", "polite", "assertive"] | None = None
    hidden: DynamicBoolean | None = None


class Action(_Wire):
    """An inline user-interaction dispatch on an interactive component.

    Wire form (UNVERIFIED, carried over from v0.9.1 with the v1.0 rename of the
    client message from ``userAction`` to ``action``)::

        {"action": "barogroove.selectTheme",
         "context": {"themeId": {"path": "/id"}},
         "sendDataModel": false}

    BAROGROOVE deliberately uses the SAME identifier space for action ids and for
    catalog function names, so ``POST /api/surfaces/action`` and a
    ``callAgentFunction`` carry interchangeable payloads.
    """

    action: str
    context: dict[str, DynamicValue] | None = None
    send_data_model: bool | None = Field(default=None, alias="sendDataModel")

    @model_serializer(mode="plain")
    def _ser(self) -> dict[str, Any]:
        out: dict[str, Any] = {"action": self.action}
        if self.context is not None:
            out["context"] = to_wire(self.context)
        if self.send_data_model is not None:
            out["sendDataModel"] = self.send_data_model
        return out


# --------------------------------------------------------------------------- #
# Component
# --------------------------------------------------------------------------- #


class Component(_Wire):
    """One node of the flat, id-addressed component tree.

    A2UI components are a FLAT adjacency list: containers reference children by
    id rather than nesting them.  That is what lets an agent patch a single node
    without resending the tree, and it is why ``properties`` are serialised as
    siblings of ``id`` / ``component`` rather than under a ``props`` object::

        {"id": "skyDial", "component": "SkyDial", "hero": {"path": "/sky/hero"}}

    CONFIRMED discriminator rule: "Every component schema defined inside the
    components map must have a required property named ``component`` whose value
    is a constant matching the key under which it is defined."
    """

    id: str
    component: str
    catalog_id: str | None = Field(default=None, alias="catalogId")
    accessibility: AccessibilityAttributes | None = None
    #: Everything the catalog declares for this component type.  Values are
    #: literals, DataBinding, FunctionCallBinding, ChildList or Action models.
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("component")
    @classmethod
    def _not_reserved(cls, v: str) -> str:
        if v == SURFACE_COMPONENT:
            raise ValueError(
                "'Surface' is reserved: createSurface instantiates it implicitly "
                "with {'child': 'root'} and it cannot be modified via updateComponents."
            )
        return v

    @model_serializer(mode="plain")
    def _ser(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "component": self.component}
        if self.catalog_id is not None:
            out["catalogId"] = self.catalog_id
        if self.accessibility is not None:
            out["accessibility"] = to_wire(self.accessibility)
        for key, value in self.properties.items():
            if value is None:
                continue
            out[key] = to_wire(value)
        return out


# --------------------------------------------------------------------------- #
# Catalog function definitions (shared by catalog.py and the routers)
# --------------------------------------------------------------------------- #


class FunctionDefinition(_Wire):
    """A catalog ``functions`` entry.

    CONFIRMED for v1.0: ``functions`` is a map keyed by function name;
    ``allowedCallers`` (rendererOnly | agentOnly | rendererOrAgent, default
    rendererOnly) restricts who may invoke it; ``requiresUserActivation``
    declares that a user gesture is required (which pins allowedCallers to
    rendererOnly).
    """

    description: str
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema (draft 2020-12) object describing the arguments.",
    )
    returns: dict[str, Any] | None = None
    allowed_callers: Literal["rendererOnly", "agentOnly", "rendererOrAgent"] = Field(
        default="rendererOnly", alias="allowedCallers"
    )
    requires_user_activation: bool = Field(default=False, alias="requiresUserActivation")


_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def validate_function_payload(
    definition: FunctionDefinition, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate an action / function payload against a declared signature.

    A deliberately small JSON-Schema subset (type, enum, required,
    additionalProperties) -- enough to keep the renderer<->agent round trip honest
    without dragging in a schema library.  Returns the payload on success.
    """
    schema = definition.parameters or {}
    props: Mapping[str, Any] = schema.get("properties", {})
    required: Sequence[str] = schema.get("required", [])
    allow_extra = schema.get("additionalProperties", False)

    missing = [name for name in required if name not in payload]
    if missing:
        raise A2UIProtocolError(f"missing required argument(s): {', '.join(sorted(missing))}")

    for key, value in payload.items():
        if key not in props:
            if allow_extra:
                continue
            raise A2UIProtocolError(f"unexpected argument {key!r}")
        spec = props[key]
        expected = spec.get("type")
        if expected and expected in _JSON_TYPES:
            # bool is an int subclass; keep "number" from swallowing True.
            if expected in {"number", "integer"} and isinstance(value, bool):
                raise A2UIProtocolError(f"argument {key!r} must be a {expected}")
            if not isinstance(value, _JSON_TYPES[expected]):
                raise A2UIProtocolError(f"argument {key!r} must be a {expected}")
        if "enum" in spec and value not in spec["enum"]:
            raise A2UIProtocolError(
                f"argument {key!r} must be one of {spec['enum']!r}, got {value!r}"
            )
    return dict(payload)


class FunctionResponse(_Wire):
    """Shared result/error payload for both RPC directions."""

    call_id: str = Field(alias="callId")
    result: Any | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _result_xor_error(self) -> FunctionResponse:
        if (self.result is None) == (self.error is None):
            raise ValueError("FunctionResponse needs exactly one of result / error")
        return self


# --------------------------------------------------------------------------- #
# Agent -> renderer messages
# --------------------------------------------------------------------------- #


class CreateSurface(_Wire):
    """Open a surface.

    CONFIRMED v1.0 changes modelled here:
      * ``theme`` is gone; ``surfaceProperties`` replaces it.
      * ``catalogId`` is optional and acts as the surface's default catalog.
      * ``components`` and ``dataModel`` may be embedded directly, which is the
        "single-message UI instantiation" fast path.
      * ``metadata`` (containing ``extensions``) is optional surface-level data.

    ``surfaceId`` must be globally unique for the renderer's lifetime -- surfaces
    are keyed by it, so a collision silently overwrites a live surface.
    """

    surface_id: str = Field(alias="surfaceId")
    catalog_id: str | None = Field(default=None, alias="catalogId")
    surface_properties: dict[str, Any] | None = Field(
        default=None, alias="surfaceProperties"
    )
    send_data_model: bool | None = Field(default=None, alias="sendDataModel")
    components: list[Component] | None = None
    data_model: dict[str, Any] | None = Field(default=None, alias="dataModel")
    metadata: dict[str, Any] | None = None


class UpdateComponents(_Wire):
    """Upsert components into a surface's flat component buffer."""

    surface_id: str = Field(alias="surfaceId")
    components: list[Component]

    @field_validator("components")
    @classmethod
    def _non_empty(cls, v: list[Component]) -> list[Component]:
        if not v:
            raise ValueError("updateComponents must carry at least one component")
        return v


class UpdateDataModel(_Wire):
    """Upsert data at a JSON Pointer path in the surface's data model."""

    surface_id: str = Field(alias="surfaceId")
    path: str = "/"
    contents: dict[str, Any] = Field(default_factory=dict)

    @model_serializer(mode="plain")
    def _ser(self) -> dict[str, Any]:
        return {
            "surfaceId": self.surface_id,
            "path": self.path,
            "contents": to_wire(self.contents),
        }


class DeleteSurface(_Wire):
    """Tear down a surface and everything in it."""

    surface_id: str = Field(alias="surfaceId")


class CallRendererFunction(_Wire):
    """Agent -> renderer typed RPC; the renderer answers ``rendererFunctionResponse``."""

    surface_id: str = Field(alias="surfaceId")
    call_id: str = Field(alias="callId")
    name: str
    args: dict[str, Any] | None = None
    catalog_id: str | None = Field(default=None, alias="catalogId")

    @model_serializer(mode="plain")
    def _ser(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "surfaceId": self.surface_id,
            "callId": self.call_id,
            "name": self.name,
        }
        if self.args is not None:
            out["args"] = to_wire(self.args)
        if self.catalog_id is not None:
            out["catalogId"] = self.catalog_id
        return out


class AgentFunctionResponse(_Wire):
    """Agent's answer to a renderer-initiated ``callAgentFunction``."""

    surface_id: str = Field(alias="surfaceId")
    call_id: str = Field(alias="callId")
    result: Any | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _result_xor_error(self) -> AgentFunctionResponse:
        if (self.result is None) == (self.error is None):
            raise ValueError("agentFunctionResponse needs exactly one of result / error")
        return self

    @model_serializer(mode="plain")
    def _ser(self) -> dict[str, Any]:
        out: dict[str, Any] = {"surfaceId": self.surface_id, "callId": self.call_id}
        if self.result is not None:
            out["result"] = to_wire(self.result)
        if self.error is not None:
            out["error"] = to_wire(self.error)
        return out


# --------------------------------------------------------------------------- #
# Renderer -> agent messages
# --------------------------------------------------------------------------- #


class CallAgentFunction(_Wire):
    """Renderer -> agent typed RPC.  This is how a theme chip talks back."""

    surface_id: str = Field(alias="surfaceId")
    call_id: str = Field(alias="callId")
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    catalog_id: str | None = Field(default=None, alias="catalogId")
    #: The renderer attaches the whole client-side data model when the surface was
    #: created with sendDataModel = true.
    data_model: dict[str, Any] | None = Field(default=None, alias="dataModel")


class RendererFunctionResponse(_Wire):
    """Renderer's answer to an agent-initiated ``callRendererFunction``."""

    surface_id: str = Field(alias="surfaceId")
    call_id: str = Field(alias="callId")
    result: Any | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _result_xor_error(self) -> RendererFunctionResponse:
        if (self.result is None) == (self.error is None):
            raise ValueError("rendererFunctionResponse needs exactly one of result / error")
        return self


class ActionResponse(_Wire):
    """The v1.0 client->server action RPC.

    UNVERIFIED naming: a2ui.org's renderer checklist calls the client->server
    user-interaction dispatch ``action`` ("replaces userAction") and describes it
    as "containing context with resolved paths"; the v1.0 candidate is elsewhere
    described as adding client-to-server RPC via ``actionResponse``.  We model one
    payload and let it ride under either envelope key -- see
    :data:`RENDERER_ENVELOPE_KEYS` and :func:`validate_envelope`.
    """

    surface_id: str = Field(alias="surfaceId")
    #: The action id the component declared -- in BAROGROOVE this equals the
    #: catalog function name, so one vocabulary covers HTTP, MCP and A2A.
    action: str
    context: dict[str, Any] = Field(default_factory=dict)
    #: Present when the surface was created with sendDataModel = true.
    data_model: dict[str, Any] | None = Field(default=None, alias="dataModel")
    timestamp: str | None = None


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #

_AGENT_KEY_BY_TYPE: dict[type[_Wire], str] = {
    CreateSurface: "createSurface",
    UpdateComponents: "updateComponents",
    UpdateDataModel: "updateDataModel",
    DeleteSurface: "deleteSurface",
    CallRendererFunction: "callRendererFunction",
    AgentFunctionResponse: "agentFunctionResponse",
}

_RENDERER_KEY_BY_TYPE: dict[type[_Wire], str] = {
    CallAgentFunction: "callAgentFunction",
    RendererFunctionResponse: "rendererFunctionResponse",
    ActionResponse: "actionResponse",
}

_KEY_BY_TYPE: dict[type[_Wire], str] = {**_AGENT_KEY_BY_TYPE, **_RENDERER_KEY_BY_TYPE}

AgentPayload = Union[
    CreateSurface,
    UpdateComponents,
    UpdateDataModel,
    DeleteSurface,
    CallRendererFunction,
    AgentFunctionResponse,
]
RendererPayload = Union[CallAgentFunction, RendererFunctionResponse, ActionResponse]


class _ExactlyOneKey(_Wire):
    """Envelope base enforcing the spec's exactly-one-key rule."""

    @model_validator(mode="after")
    def _exactly_one(self):  # type: ignore[no-untyped-def]
        present = [k for k, v in self.__dict__.items() if v is not None]
        if len(present) != 1:
            raise ValueError(
                "an A2UI envelope must contain exactly one message key, "
                f"got {len(present)}: {sorted(present) or '<none>'}"
            )
        return self

    @model_serializer(mode="plain")
    def _ser(self) -> dict[str, Any]:
        for name, value in self.__dict__.items():
            if value is None:
                continue
            alias = type(self).model_fields[name].alias or name
            return {alias: to_wire(value)}
        raise A2UIProtocolError("empty envelope")  # pragma: no cover


class AgentMessage(_ExactlyOneKey):
    """One agent->renderer stream message.  Exactly one field may be set."""

    create_surface: CreateSurface | None = Field(default=None, alias="createSurface")
    update_components: UpdateComponents | None = Field(
        default=None, alias="updateComponents"
    )
    update_data_model: UpdateDataModel | None = Field(
        default=None, alias="updateDataModel"
    )
    delete_surface: DeleteSurface | None = Field(default=None, alias="deleteSurface")
    call_renderer_function: CallRendererFunction | None = Field(
        default=None, alias="callRendererFunction"
    )
    agent_function_response: AgentFunctionResponse | None = Field(
        default=None, alias="agentFunctionResponse"
    )


class RendererMessage(_ExactlyOneKey):
    """One renderer->agent message.  Exactly one field may be set."""

    call_agent_function: CallAgentFunction | None = Field(
        default=None, alias="callAgentFunction"
    )
    renderer_function_response: RendererFunctionResponse | None = Field(
        default=None, alias="rendererFunctionResponse"
    )
    action_response: ActionResponse | None = Field(default=None, alias="actionResponse")


class Stream(RootModel[list[AgentMessage]]):
    """An ordered agent->renderer message stream."""

    root: list[AgentMessage]


# --------------------------------------------------------------------------- #
# Helpers every other module in BAROGROOVE uses
# --------------------------------------------------------------------------- #


def envelope_key(msg: _Wire) -> str:
    """The single envelope key for a payload model."""
    try:
        return _KEY_BY_TYPE[type(msg)]
    except KeyError as exc:  # pragma: no cover - programmer error
        raise A2UIProtocolError(f"{type(msg).__name__} is not an A2UI message") from exc


def envelope(msg: _Wire) -> dict[str, Any]:
    """Wrap one payload model in its spec envelope and return camelCase JSON.

    >>> envelope(DeleteSurface(surface_id="s1"))
    {'deleteSurface': {'surfaceId': 's1'}}
    """
    return {envelope_key(msg): msg.model_dump(by_alias=True, exclude_none=True)}


def stream(msgs: Iterable[_Wire]) -> list[dict[str, Any]]:
    """Wrap an ordered sequence of payload models into a wire stream."""
    return [envelope(m) for m in msgs]


def collapse_to_single_message(
    messages: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Fold a ``createSurface`` + ``updateComponents`` + ``updateDataModel`` stream
    into ONE ``createSurface``.

    This is A2UI v1.0's *single-message UI instantiation*: "Components and initial
    data model states can be defined directly within the createSurface
    parameters."  BAROGROOVE's builders emit the explicit three-message stream by
    default because it progressively renders (the renderer paints as soon as it
    parses ``root``), and callers that would rather pay one round trip -- the HTTP
    route with ``?single=true``, or an MCP tool returning a single content block --
    run the stream through here.

    Anything after the first three messages is passed through untouched.
    """
    if not messages:
        return []
    head = dict(messages[0])
    if "createSurface" not in head:
        return [dict(m) for m in messages]

    create = dict(head["createSurface"])
    rest: list[dict[str, Any]] = []
    surface_id = create.get("surfaceId")
    for msg in messages[1:]:
        if "updateComponents" in msg and msg["updateComponents"].get("surfaceId") == surface_id:
            create.setdefault("components", [])
            create["components"] = list(create["components"]) + list(
                msg["updateComponents"]["components"]
            )
        elif (
            "updateDataModel" in msg
            and msg["updateDataModel"].get("surfaceId") == surface_id
            and msg["updateDataModel"].get("path", "/") == "/"
        ):
            merged = dict(create.get("dataModel") or {})
            merged.update(msg["updateDataModel"].get("contents", {}))
            create["dataModel"] = merged
        else:
            rest.append(dict(msg))
    return [{"createSurface": create}, *rest]


def validate_envelope(message: Mapping[str, Any]) -> str:
    """Assert a message is a legal envelope and return its single key."""
    if not isinstance(message, Mapping):  # pragma: no cover - defensive
        raise A2UIProtocolError(f"envelope must be a JSON object, got {type(message)!r}")
    keys = list(message.keys())
    if len(keys) != 1:
        raise A2UIProtocolError(
            f"an A2UI envelope must contain exactly one key, got {len(keys)}: {sorted(keys)}"
        )
    key = keys[0]
    if key not in AGENT_ENVELOPE_KEYS and key not in RENDERER_ENVELOPE_KEYS:
        raise A2UIProtocolError(f"unknown A2UI envelope key {key!r}")
    return key


def find_root(components: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Return the component whose id is ``root``, or raise.

    Required because ``createSurface`` implicitly instantiates the reserved
    ``Surface`` container with ``{"child": "root"}``; without a ``root`` component
    the renderer has nothing to paint.
    """
    for component in components:
        if component.get("id") == ROOT_COMPONENT_ID:
            return component
    raise A2UIProtocolError('no component with "id": "root" in this surface')


def validate_stream(messages: Sequence[Mapping[str, Any]]) -> None:
    """Validate a full builder output: envelopes, ordering, root, surface ids.

    Rules enforced (all CONFIRMED against a2ui.org except where noted):
      1. every message is an envelope with exactly one known key;
      2. the first message is ``createSurface``;
      3. exactly one ``createSurface`` per stream, so ``surfaceId`` stays unique
         for the renderer's lifetime;
      4. every subsequent message targets that same ``surfaceId``;
      5. a component with ``"id": "root"`` is present, either inline in
         ``createSurface`` (single-message instantiation) or in an
         ``updateComponents``;
      6. no component claims the reserved type ``Surface``.
    """
    if not messages:
        raise A2UIProtocolError("empty stream")

    keys = [validate_envelope(m) for m in messages]
    if keys[0] != "createSurface":
        raise A2UIProtocolError(f"stream must open with createSurface, got {keys[0]!r}")
    if keys.count("createSurface") != 1:
        raise A2UIProtocolError("a surface stream must contain exactly one createSurface")

    create = messages[0]["createSurface"]
    surface_id = create.get("surfaceId")
    if not surface_id:
        raise A2UIProtocolError("createSurface must carry a non-empty surfaceId")

    components: list[Mapping[str, Any]] = list(create.get("components") or [])
    for message, key in zip(messages, keys):
        payload = message[key]
        if payload.get("surfaceId") not in (surface_id, None):
            raise A2UIProtocolError(
                f"{key} targets surfaceId {payload.get('surfaceId')!r}, expected {surface_id!r}"
            )
        if key == "updateComponents":
            components.extend(payload["components"])

    for component in components:
        if component.get("component") == SURFACE_COMPONENT:
            raise A2UIProtocolError("the reserved 'Surface' component cannot be sent")
    find_root(components)
