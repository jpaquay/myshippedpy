"""Tests for the BAROGROOVE MCP server, its tools, and the callAgentFunction registry.

No network. Nothing here reaches past the process boundary: the weather source, the
forge, the almanac and the sinks are whatever the container hands back, and the two
tests that would otherwise depend on live data assert *structure* rather than content.

Layering of the skips, which is deliberate:

* The registry and manifest tests import ``app.mcp.functions`` and ``app.mcp.manifest``
  only. Neither module touches the ``mcp`` package, so these tests run on a machine
  where the SDK was never installed. That is required: the renderer round-trip is a
  property of BAROGROOVE, not of the SDK.
* The mounting tests call ``pytest.importorskip("mcp")`` and skip cleanly without it.
* The surface-shape tests skip when ``app.a2ui.surfaces`` is unavailable, since the
  builders are a separate module and an absent one is a different failure than a broken
  one.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------------
# Import path. tests/ sits beside backend/, and the package root is backend/.
# ---------------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.mcp import functions as fx  # noqa: E402
from app.mcp import manifest as mf  # noqa: E402
from app.mcp import server as srv  # noqa: E402


def _run(coro: Any) -> Any:
    """Drive a coroutine without depending on a pytest-asyncio mode being configured."""
    return asyncio.run(coro)


def _a2ui_available() -> bool:
    try:
        from app.a2ui import surfaces  # noqa: F401
    except Exception:
        return False
    return True


requires_a2ui = pytest.mark.skipif(
    not _a2ui_available(), reason="app.a2ui.surfaces is not available in this checkout"
)


# =================================================================================
# JSON Schema validity
# =================================================================================

_JSON_SCHEMA_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}


def assert_valid_json_schema(schema: Any, *, where: str) -> None:
    """Assert ``schema`` is a structurally valid JSON Schema document.

    Uses the ``jsonschema`` library's own metaschema check when it is installed, and
    otherwise falls back to a structural walk. The fallback is not a full validator and
    does not pretend to be; it catches the failures that actually happen when a pydantic
    model is misdeclared - a non-dict schema, a bogus ``type``, a ``required`` entry with
    no matching property, a ``properties`` value that is not itself a schema.
    """
    assert isinstance(schema, dict), f"{where}: schema is {type(schema).__name__}, not a dict"

    try:
        import jsonschema  # type: ignore[import-not-found]

        validator = jsonschema.validators.validator_for(schema)
        validator.check_schema(schema)
    except ImportError:
        pass

    assert json.loads(json.dumps(schema)) == schema, f"{where}: schema is not JSON round-trippable"

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        declared = node.get("type")
        if declared is not None:
            kinds = declared if isinstance(declared, list) else [declared]
            for kind in kinds:
                assert kind in _JSON_SCHEMA_TYPES, f"{where}{path}: '{kind}' is not a JSON Schema type"
        properties = node.get("properties")
        if properties is not None:
            assert isinstance(properties, dict), f"{where}{path}: 'properties' must be an object"
            for key, value in properties.items():
                assert isinstance(value, dict), f"{where}{path}.{key}: property schema must be an object"
                walk(value, f"{path}.{key}")
        required = node.get("required")
        if required is not None:
            assert isinstance(required, list), f"{where}{path}: 'required' must be an array"
            known = set((properties or {}).keys())
            if properties is not None:
                for name in required:
                    assert name in known, f"{where}{path}: required '{name}' has no property"
        for keyword in ("items", "additionalProperties", "not"):
            child = node.get(keyword)
            if isinstance(child, dict):
                walk(child, f"{path}.{keyword}")
        for keyword in ("anyOf", "oneOf", "allOf", "prefixItems"):
            children = node.get(keyword)
            if isinstance(children, list):
                for index, child in enumerate(children):
                    walk(child, f"{path}.{keyword}[{index}]")
        for name, child in (node.get("$defs") or {}).items():
            walk(child, f"{path}.$defs.{name}")

    walk(schema, "")


# =================================================================================
# A2UI envelope-stream validity
# =================================================================================


def assert_valid_a2ui_stream(messages: Any, *, where: str, expect_root: bool = True) -> None:
    """Assert an A2UI v1.0 agent-to-renderer stream is well formed.

    The invariants checked are the ones the v1.0 spec makes load-bearing:

    * every message is an object with **exactly one** top-level key, and that key names
      a known agent-to-renderer message type;
    * ``createSurface`` comes first, because the renderer instantiates the canonical
      Surface container from it and everything after targets that surface;
    * a surfaceId is present and consistent across the stream;
    * some component in the stream carries ``id == "root"`` - ``createSurface``
      implicitly creates a Surface whose ``child`` is ``"root"``, so a stream without one
      renders nothing.
    """
    agent_to_renderer = {
        "createSurface",
        "updateComponents",
        "updateDataModel",
        "deleteSurface",
        "callRendererFunction",
        "agentFunctionResponse",
    }

    assert isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)), (
        f"{where}: the stream must be a sequence of envelopes"
    )
    assert len(messages) >= 1, f"{where}: the stream is empty"

    for index, message in enumerate(messages):
        assert isinstance(message, Mapping), f"{where}[{index}]: envelope is not an object"
        keys = list(message.keys())
        assert len(keys) == 1, f"{where}[{index}]: envelope has {len(keys)} keys {keys}, expected exactly 1"
        assert keys[0] in agent_to_renderer, f"{where}[{index}]: '{keys[0]}' is not an A2UI v1.0 message type"
        assert isinstance(message[keys[0]], Mapping), f"{where}[{index}]: '{keys[0]}' body is not an object"

    first = list(messages[0].keys())[0]
    assert first == "createSurface", f"{where}: stream starts with '{first}', expected 'createSurface'"

    surface_ids = {
        body.get("surfaceId")
        for message in messages
        for body in message.values()
        if isinstance(body, Mapping) and body.get("surfaceId")
    }
    assert surface_ids, f"{where}: no surfaceId anywhere in the stream"
    assert len(surface_ids) == 1, f"{where}: stream mixes surfaces {surface_ids}"
    assert isinstance(next(iter(surface_ids)), str)

    if expect_root:
        roots = [
            component
            for message in messages
            for body in message.values()
            if isinstance(body, Mapping)
            for component in (body.get("components") or [])
            if isinstance(component, Mapping) and component.get("id") == "root"
        ]
        assert roots, f"{where}: no component with id 'root'; the Surface would have nothing to mount"


def structured_of(result: Any) -> dict[str, Any]:
    """Pull the structured payload out of whatever ``_pack`` produced.

    With the SDK installed that is a ``CallToolResult``; without it, a plain dict. Both
    carry the identical payload, which is the point of the fallback.
    """
    if isinstance(result, dict):
        return result
    for attribute in ("structured_content", "structuredContent"):
        value = getattr(result, attribute, None)
        if isinstance(value, dict):
            return value
    raise AssertionError(f"no structured content on {type(result).__name__}")


# =================================================================================
# Manifest
# =================================================================================


def test_manifest_declares_the_five_tools() -> None:
    manifest = mf.manifest_dict()
    names = [tool["name"] for tool in manifest["tools"]]
    assert names == [
        "get_sky_vector",
        "list_themes",
        "forge_playlist",
        "explain_playlist",
        "save_playlist",
    ]
    assert manifest["name"] == "barogroove"
    assert manifest["transport"] == "streamable-http"
    assert manifest["endpoint"] == "/mcp"
    assert manifest["a2ui"]["version"] == "1.0"


def test_manifest_is_json_serialisable() -> None:
    assert json.loads(mf.manifest_json()) == mf.manifest_dict()


@pytest.mark.parametrize("name", mf.TOOL_NAMES)
def test_tool_schemas_are_valid_json_schema(name: str) -> None:
    spec = mf.tool_spec(name)
    assert spec.name == name
    assert_valid_json_schema(spec.input_schema, where=f"{name}.inputSchema")
    assert_valid_json_schema(spec.output_schema, where=f"{name}.outputSchema")
    assert spec.description.strip(), f"{name} has no description; the description is the prompt"
    assert len(spec.description) > 80, f"{name}'s description is too thin to steer a model"


@pytest.mark.parametrize("name", mf.TOOL_NAMES)
def test_tool_declared_name_matches_the_manifest_row(name: str) -> None:
    row = next(t for t in mf.manifest_dict()["tools"] if t["name"] == name)
    assert row["inputSchema"] == mf.tool_spec(name).input_schema
    assert row["outputSchema"] == mf.tool_spec(name).output_schema
    assert row["_meta"]["a2ui"]["version"] == "1.0"


def test_required_arguments_are_the_ones_we_mean() -> None:
    assert set(mf.tool_spec("get_sky_vector").input_schema["required"]) == {"lat", "lon"}
    assert set(mf.tool_spec("forge_playlist").input_schema["required"]) == {"lat", "lon"}
    assert set(mf.tool_spec("save_playlist").input_schema["required"]) == {"playlist_id"}
    assert not mf.tool_spec("list_themes").input_schema.get("required")
    # explain_playlist takes either id or inline object, so neither may be required.
    assert not mf.tool_spec("explain_playlist").input_schema.get("required")


def test_manifest_lists_the_agent_functions() -> None:
    declared = {spec.name for spec in mf.agent_function_specs()}
    assert declared == set(fx.FUNCTION_NAMES)
    for spec in mf.agent_function_specs():
        assert_valid_json_schema(spec.argument_schema, where=f"agentFunction.{spec.name}")


# =================================================================================
# callAgentFunction registry - no dependency on the mcp package
# =================================================================================


def test_registry_exposes_the_four_declared_functions() -> None:
    assert set(fx.FUNCTION_NAMES) == {"selectTheme", "selectGenre", "rateTrack", "reforge"}


@pytest.mark.parametrize(
    "spelling",
    ["selectTheme", "selecttheme", "barogroove.selectTheme", "select_theme", "onThemeSelected"],
)
def test_resolve_accepts_aliases_and_is_case_insensitive(spelling: str) -> None:
    assert fx.resolve(spelling).name == "selectTheme"


def test_resolve_rejects_an_unknown_function() -> None:
    with pytest.raises(fx.AgentFunctionError) as caught:
        fx.resolve("makeMeASandwich")
    assert caught.value.code == "unknown_function"


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("selectTheme", {"themeId": "storm-front", "surfaceId": "s1"}),
        ("selectGenre", {"genreId": "ambient", "themeId": "storm-front"}),
        ("rateTrack", {"playlistId": "p1", "trackId": "t1", "verdict": "love"}),
        ("reforge", {"lat": 50.85, "lon": 4.35, "length": 12}),
    ],
)
def test_registry_validates_good_payloads(name: str, payload: dict[str, Any]) -> None:
    """Validation only. Running the handler needs subsystems; that is a separate test."""
    args = fx.resolve(name).validate(payload)
    assert args is not None


@pytest.mark.parametrize(
    ("name", "payload", "why"),
    [
        ("selectTheme", {}, "themeId is required"),
        ("selectTheme", {"themeId": ""}, "themeId must be non-empty"),
        ("selectTheme", {"themeId": "x", "smuggled": True}, "unknown keys are rejected"),
        ("selectGenre", {"themeId": "x"}, "genreId is required"),
        ("rateTrack", {"playlistId": "p", "trackId": "t", "verdict": "shrug"}, "verdict is an enum"),
        ("rateTrack", {"playlistId": "p", "verdict": "love"}, "trackId is required"),
        ("reforge", {"lat": 999.0, "lon": 0.0}, "latitude is bounded"),
        ("reforge", {"lat": 0.0, "lon": 0.0, "length": 9999}, "length is bounded"),
        ("reforge", {"lon": 4.35}, "lat is required"),
    ],
)
def test_registry_rejects_malformed_payloads(name: str, payload: dict[str, Any], why: str) -> None:
    with pytest.raises(fx.AgentFunctionError) as caught:
        fx.resolve(name).validate(payload)
    assert caught.value.code == "invalid_arguments", why


def test_dispatch_never_raises_and_answers_with_an_agent_function_response() -> None:
    """The contract: a renderer always gets a well-formed answer to its call."""
    for name, payload in [
        ("nosuchfunction", {}),
        ("selectTheme", {}),
        ("reforge", {"lat": 999.0, "lon": 0.0}),
    ]:
        result = _run(fx.dispatch(name, payload, call_id="call-1"))
        assert result.ok is False
        assert result.error is not None
        assert list(result.response.keys()) == ["agentFunctionResponse"]
        body = result.response["agentFunctionResponse"]
        assert body["success"] is False
        assert body["callId"] == "call-1"
        assert "error" in body and "code" in body["error"]
        # No traceback anywhere near the wire.
        assert "Traceback" not in json.dumps(result.response)


def test_agent_function_response_carries_both_field_spellings() -> None:
    envelope = fx.agent_function_response("selectTheme", surface_id="s1", call_id="c1", result={"ok": True})
    body = envelope["agentFunctionResponse"]
    assert body["name"] == body["functionName"] == "selectTheme"
    assert body["callId"] == body["functionCallId"] == "c1"
    assert body["surfaceId"] == "s1"
    assert body["success"] is True


@requires_a2ui
@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("selectTheme", {"themeId": "storm-front", "surfaceId": "s1"}),
        ("selectGenre", {"genreId": "ambient", "surfaceId": "s1"}),
    ],
)
def test_selection_round_trips_return_a_renderable_surface(name: str, payload: dict[str, Any]) -> None:
    result = _run(fx.dispatch(name, payload, call_id="c9"))
    if not result.ok:
        pytest.skip(f"{name} degraded ({result.error}); the theme catalogue is not wired up here")
    assert_valid_a2ui_stream(result.messages, where=f"dispatch({name})")
    assert result.response["agentFunctionResponse"]["success"] is True
    # The whole stream, response last, is what the renderer consumes.
    assert list(result.stream()[-1].keys()) == ["agentFunctionResponse"]


@requires_a2ui
def test_rate_track_emits_a_single_data_model_patch() -> None:
    """A heart tap must not re-forge the playlist; it patches the data model and stops."""
    result = _run(
        fx.dispatch(
            "rateTrack",
            {"playlistId": "p1", "trackId": "t1", "verdict": "love", "surfaceId": "s-play"},
            call_id="c2",
        )
    )
    assert result.ok is True
    assert len(result.messages) == 1
    assert list(result.messages[0].keys()) == ["updateDataModel"]
    body = result.messages[0]["updateDataModel"]
    assert body["surfaceId"] == "s-play"
    assert body["contents"]["verdict"] == "love"


def test_dispatch_injects_the_calling_surface_id() -> None:
    result = _run(fx.dispatch("rateTrack", {"playlistId": "p", "trackId": "t", "verdict": "skip"},
                              surface_id="s-injected"))
    if result.ok:
        assert result.messages[0]["updateDataModel"]["surfaceId"] == "s-injected"
    else:  # degraded, but the surface must still have been threaded through
        assert result.surface_id == "s-injected"


# =================================================================================
# Tool bodies - structure, and degradation
# =================================================================================

_TOOL_CALLS: list[tuple[str, Any]] = [
    ("get_sky_vector", mf.GetSkyVectorInput(lat=50.85, lon=4.35, label="Brussels")),
    ("list_themes", mf.ListThemesInput()),
    ("forge_playlist", mf.ForgePlaylistInput(lat=50.85, lon=4.35, length=6)),
    ("explain_playlist", mf.ExplainPlaylistInput(playlist_id="does-not-exist")),
    ("save_playlist", mf.SavePlaylistInput(playlist_id="does-not-exist")),
]


@requires_a2ui
@pytest.mark.parametrize(("name", "args"), _TOOL_CALLS, ids=[c[0] for c in _TOOL_CALLS])
def test_every_tool_returns_a_valid_a2ui_stream(name: str, args: Any) -> None:
    """Success or degradation, the stream must be renderable.

    We deliberately do not require ``ok`` to be true: two of these calls reference a
    playlist id that will not exist, and a checkout without a live weather source will
    degrade the others. An error surface is still a surface, and it must satisfy exactly
    the same invariants - that is the point of routing failures through
    ``build_error_surface`` rather than letting them raise.
    """
    payload = structured_of(_run(getattr(srv, f"_run_{name}")(args)))

    assert payload["tool"] == name
    assert isinstance(payload["ok"], bool)
    assert_valid_a2ui_stream(payload["a2ui"], where=f"{name}.a2ui")
    assert payload["surface_id"], f"{name}: surface_id was not reported"

    created = payload["a2ui"][0]["createSurface"]["surfaceId"]
    assert payload["surface_id"] == created

    if not payload["ok"]:
        assert payload["error"], f"{name}: ok is false but no structured error"
        assert set(payload["error"]) >= {"code", "message"}
        assert "Traceback" not in json.dumps(payload)


@requires_a2ui
@pytest.mark.parametrize(("name", "args"), _TOOL_CALLS, ids=[c[0] for c in _TOOL_CALLS])
def test_tool_output_conforms_to_its_declared_schema(name: str, args: Any) -> None:
    payload = structured_of(_run(getattr(srv, f"_run_{name}")(args)))
    model = mf.tool_spec(name).output_model
    model.model_validate(payload)


@requires_a2ui
def test_a_failing_subsystem_yields_an_error_surface_not_an_exception(monkeypatch: Any) -> None:
    """Break the container outright and confirm the tool still answers politely."""
    container = pytest.importorskip("app.container", reason="app.container is not available")

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("upstream weather provider is unreachable")

    monkeypatch.setattr(container, "get_container", boom)

    payload = structured_of(_run(srv._run_get_sky_vector(mf.GetSkyVectorInput(lat=0.0, lon=0.0))))

    assert payload["ok"] is False
    assert payload["error"]["message"]
    assert "Traceback" not in json.dumps(payload)
    assert_valid_a2ui_stream(payload["a2ui"], where="degraded get_sky_vector")

    # And the forge, which is the tool a user is most likely to be sitting in front of.
    forged = structured_of(_run(srv._run_forge_playlist(mf.ForgePlaylistInput(lat=0.0, lon=0.0))))
    assert forged["ok"] is False
    assert_valid_a2ui_stream(forged["a2ui"], where="degraded forge_playlist")


def test_error_stream_is_empty_rather_than_hand_rolled_when_a2ui_is_gone(monkeypatch: Any) -> None:
    """If the builders themselves are the casualty, we return no UI - not invented UI."""

    def no_surfaces() -> Any:
        raise ImportError("app.a2ui.surfaces is not installed")

    monkeypatch.setattr(srv, "_surfaces", no_surfaces)
    assert srv._error_stream("gone") == []


# =================================================================================
# Mounting - requires the mcp package
# =================================================================================


def test_manifest_route_is_installed_without_the_sdk() -> None:
    """The descriptor is dependency-free and must survive a deployment with no SDK."""
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = fastapi.FastAPI()
    mf.install_manifest_route(app)
    mf.install_manifest_route(app)  # idempotent

    paths = [getattr(r, "path", None) for r in app.router.routes]
    assert paths.count("/mcp/manifest") == 1

    with TestClient(app) as client:
        body = client.get("/mcp/manifest").json()
    assert [t["name"] for t in body["tools"]] == list(mf.TOOL_NAMES)


def test_mount_mcp_composes_rather_than_replaces_the_host_lifespan() -> None:
    """The host's lifespan must still run, in the right order, with MCP nested inside."""
    pytest.importorskip("mcp", reason="the MCP SDK is not installed")
    import contextlib

    import fastapi
    from fastapi.testclient import TestClient

    events: list[str] = []

    @contextlib.asynccontextmanager
    async def host_lifespan(_app: fastapi.FastAPI) -> Any:
        events.append("host:open")
        try:
            yield {"pool": "open"}
        finally:
            events.append("host:close")

    app = fastapi.FastAPI(lifespan=host_lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    original = app.router.lifespan_context
    srv.mount_mcp(app)
    assert app.router.lifespan_context is not original, "the host lifespan was not composed"

    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert events == ["host:open"], "the host lifespan did not run, or ran twice"

    assert events == ["host:open", "host:close"], "the host lifespan did not close cleanly"


def test_transport_survives_repeated_lifespan_cycles() -> None:
    """Regression: a session manager refuses a second ``run()``.

    Binding the router to one session manager at mount time yields a working endpoint on
    the first boot and a dead one on every boot after - which is what a test suite, a
    ``uvicorn --reload`` worker, or anything that restarts an ASGI app in-process will do
    to you. The transport must be rebuilt per cycle.
    """
    pytest.importorskip("mcp", reason="the MCP SDK is not installed")
    import fastapi
    from fastapi.testclient import TestClient

    app = fastapi.FastAPI()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    srv.mount_mcp(app)

    for cycle in range(3):
        with TestClient(app, base_url="http://testserver") as client:
            assert client.get("/healthz").status_code == 200
            response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "t", "version": "1"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
            )
            assert response.status_code == 200, f"cycle {cycle}: {response.status_code} {response.text[:200]}"
            assert "error" not in _sse_payload(response), f"cycle {cycle} returned a JSON-RPC error"


def test_transport_answers_503_while_not_running() -> None:
    """Outside a lifespan the endpoint exists but is dark. 503, not a 500 or a traceback."""
    transport = srv._MCPTransport()
    assert transport.live is False

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:  # pragma: no cover - never awaited on this path
        return {"type": "http.request"}

    _run(transport({"type": "http", "method": "POST", "path": "/mcp"}, receive, send))

    assert sent[0]["status"] == 503
    body = json.loads(sent[1]["body"])
    assert body["error"]["message"]
    assert "Traceback" not in json.dumps(body)


def test_mount_mcp_is_idempotent() -> None:
    pytest.importorskip("mcp", reason="the MCP SDK is not installed")
    import fastapi

    app = fastapi.FastAPI()
    srv.mount_mcp(app)
    before = len(app.router.routes)
    srv.mount_mcp(app)
    assert len(app.router.routes) == before


def test_mount_mcp_is_non_fatal_when_the_sdk_cannot_be_loaded(monkeypatch: Any) -> None:
    """A broken SDK must cost us the /mcp endpoint and nothing else."""
    import fastapi
    from fastapi.testclient import TestClient

    app = fastapi.FastAPI()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    def boom() -> Any:
        raise ImportError("mcp is not installed on this deployment")

    monkeypatch.setattr(srv, "_load_server_class", boom)
    srv.mount_mcp(app)  # must not raise

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        # The descriptor is still served, because it never needed the SDK.
        assert client.get("/mcp/manifest").status_code == 200
    assert not getattr(app.state, "_barogroove_mcp_mounted", False)


# =================================================================================
# The real app, booted
# =================================================================================


def _real_app() -> Any:
    try:
        from app.main import app
    except Exception as exc:  # pragma: no cover - depends on another worker's module
        pytest.skip(f"app.main is not importable in this checkout: {exc}")
    return app


def test_real_app_still_serves_rest_after_mounting() -> None:
    """Boot the actual application and confirm mounting did not eat the REST surface."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = _real_app()
    with TestClient(app, base_url="http://testserver") as client:
        health = client.get("/healthz")
        assert health.status_code == 200, "/healthz broke after mount_mcp"

        legacy = client.get("/legacy")
        assert legacy.status_code == 200, "/legacy broke after mount_mcp"

        manifest = client.get("/mcp/manifest")
        assert manifest.status_code == 200
        assert [t["name"] for t in manifest.json()["tools"]] == list(mf.TOOL_NAMES)


def test_manifest_route_is_not_shadowed_by_the_transport() -> None:
    """Route ordering regression guard: /mcp/manifest must win over anything at /mcp.

    The transport is an exact-path route, so it cannot shadow the manifest today. The
    guard stays because the ordering is only safe by construction - swap the transport
    back to an ``app.mount`` and ``/mcp/manifest`` disappears silently.
    """
    app = _real_app()
    routes = list(app.router.routes)
    paths = [getattr(r, "path", None) for r in routes]
    assert "/mcp/manifest" in paths
    manifest_at = paths.index("/mcp/manifest")
    for index, route in enumerate(routes):
        if getattr(route, "path", None) == "/mcp" and getattr(route, "routes", None) is not None:
            assert index > manifest_at, "the /mcp mount shadows /mcp/manifest"


# =================================================================================
# End-to-end over streamable HTTP - the whole point of the module
# =================================================================================


def _sse_payload(response: Any) -> dict[str, Any]:
    """Read the single JSON-RPC message out of a streamable-HTTP SSE response."""
    if response.headers.get("content-type", "").startswith("application/json"):
        return dict(response.json())
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return dict(json.loads(line[6:]))
    raise AssertionError(f"no SSE data frame in {response.text[:200]!r}")


def _mcp_session(client: Any) -> dict[str, str]:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "barogroove-tests", "version": "1.0"},
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, f"initialize failed: {response.status_code} {response.text[:200]}"
    assert "error" not in _sse_payload(response)
    return headers


def test_streamable_http_endpoint_lists_the_tools() -> None:
    pytest.importorskip("mcp", reason="the MCP SDK is not installed")
    from fastapi.testclient import TestClient

    app = _real_app()
    if not getattr(app.state, "_barogroove_mcp_mounted", False):
        pytest.skip("MCP did not mount in this checkout")

    with TestClient(app, base_url="http://testserver") as client:
        headers = _mcp_session(client)
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)
        tools = _sse_payload(response)["result"]["tools"]

    listed = {tool["name"]: tool for tool in tools}
    assert set(listed) == set(mf.TOOL_NAMES), "the wire disagrees with the manifest"
    for name, tool in listed.items():
        assert_valid_json_schema(tool["inputSchema"], where=f"wire.{name}.inputSchema")
        assert tool["description"] == mf.tool_spec(name).description
        # The A2UI binding is advertised before the tool is ever called.
        assert tool.get("_meta", {}).get("a2ui", {}).get("version") == "1.0"


@requires_a2ui
def test_tool_call_carries_a2ui_in_all_three_placements() -> None:
    """The placement decision, asserted. See the comment block in manifest.py."""
    pytest.importorskip("mcp", reason="the MCP SDK is not installed")
    from fastapi.testclient import TestClient

    app = _real_app()
    if not getattr(app.state, "_barogroove_mcp_mounted", False):
        pytest.skip("MCP did not mount in this checkout")

    with TestClient(app, base_url="http://testserver") as client:
        headers = _mcp_session(client)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_themes", "arguments": {}},
            },
            headers=headers,
        )
        result = _sse_payload(response)["result"]

    # Placement 3: structured content, for a client with no A2UI support at all.
    structured = result["structuredContent"]
    assert_valid_a2ui_stream(structured["a2ui"], where="wire.structuredContent.a2ui")

    # A text block, so a text-only host still gets a sentence.
    text_blocks = [block for block in result["content"] if block["type"] == "text"]
    assert text_blocks and text_blocks[0]["text"].strip()

    if structured["ok"]:
        # Placement 1: an embedded resource with the A2UI media type.
        resources = [block for block in result["content"] if block["type"] == "resource"]
        assert resources, "no EmbeddedResource carrying the surface"
        embedded = resources[0]["resource"]
        assert embedded["mimeType"] == mf.A2UI_MEDIA_TYPE
        assert embedded["uri"].startswith("a2ui://")
        assert_valid_a2ui_stream(json.loads(embedded["text"]), where="wire.embeddedResource")

        # Placement 2: result._meta, unwrapped.
        meta = result.get("_meta") or {}
        assert mf.A2UI_MESSAGES_META_KEY in meta
        assert_valid_a2ui_stream(meta[mf.A2UI_MESSAGES_META_KEY], where="wire._meta")

        # All three must agree. One UI definition, one stream, three doorways.
        assert meta[mf.A2UI_MESSAGES_META_KEY] == structured["a2ui"]
        assert json.loads(embedded["text"]) == structured["a2ui"]


def test_bad_arguments_are_rejected_by_the_declared_schema() -> None:
    """A latitude of 999 must not reach the weather source."""
    pytest.importorskip("mcp", reason="the MCP SDK is not installed")
    from fastapi.testclient import TestClient

    app = _real_app()
    if not getattr(app.state, "_barogroove_mcp_mounted", False):
        pytest.skip("MCP did not mount in this checkout")

    with TestClient(app, base_url="http://testserver") as client:
        headers = _mcp_session(client)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_sky_vector", "arguments": {"lat": 999.0, "lon": 0.0}},
            },
            headers=headers,
        )
        payload = _sse_payload(response)

    # Either the SDK rejects it as a protocol error, or our model rejects it and we
    # answer with a structured tool error. Both are correct; a 500 is not.
    if "error" in payload:
        assert payload["error"]["code"]
    else:
        result = payload["result"]
        assert result.get("isError") or result["structuredContent"]["ok"] is False
    assert "Traceback" not in response.text
