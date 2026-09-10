"""BAROGROOVE's MCP server, mounted on the same FastAPI app as the REST API.

``main.py`` does this, inside a try/except that logs and continues::

    from .mcp.server import mount_mcp
    mount_mcp(app)

so the single hard requirement of this module is that :func:`mount_mcp` exists, takes a
``FastAPI``, and never leaves the host app worse than it found it.


Why the SDK import is version-shaped
------------------------------------
The Python MCP SDK renamed ``FastMCP`` to ``MCPServer`` in 2.x
(``mcp.server.fastmcp`` now raises a ModuleNotFoundError that says so, and points at the
migration guide). Both spellings are in the wild right now, so :func:`_load_server_class`
tries the 2.x name first and falls back to the 1.x one. Same constructor keywords for
everything we use, same ``streamable_http_app()``, same ``session_manager`` property.


How the transport is attached
-----------------------------
``server.streamable_http_app()`` returns a ``Starlette`` app that contains exactly one
route - a plain ``Route(streamable_http_path, endpoint=StreamableHTTPASGIApp(...))`` -
and whose lifespan is ``session_manager.run()``.

Two consequences drive the code below.

1. **A mounted sub-app's lifespan does not run.** Starlette only invokes the lifespan of
   the outermost application. Mounting the MCP app and walking away gives you an endpoint
   that 500s on the first request because the session manager's task group was never
   entered. This is the failure mode; see :func:`_compose_lifespan`.

2. **A Starlette ``Mount`` cannot match its own prefix exactly.** ``Mount("/mcp")``
   compiles to ``^/mcp/(?P<path>.*)$``, so ``POST /mcp`` misses and only survives via a
   307 from the router's ``redirect_slashes``. Plenty of MCP clients do not follow
   redirects on POST. Since the SDK's own app is a single flat ``Route``, we register our
   own exact-path ``Route("/mcp")`` on the host router and forward to the SDK's ASGI
   handler through :class:`_MCPTransport`. Exact match, no redirect, no nested router,
   and the SDK still owns every transport setting.

3. **A session manager runs exactly once.** ``StreamableHTTPSessionManager.run()`` raises
   if it is called a second time on the same instance, so a router that captured one
   instance at mount time gives you a working endpoint on the first lifespan cycle and a
   dead one on every cycle after. That is not hypothetical: a test suite that boots the
   app twice, ``uvicorn --reload``, and anything that restarts an ASGI app in-process all
   hit it. :class:`_MCPTransport` is the indirection that fixes it - the route is bound to
   the *proxy*, and each lifespan cycle builds a fresh transport and points the proxy at
   it. Between cycles the proxy answers 503 rather than raising.


Route ordering
--------------
``GET /mcp/manifest`` is installed *before* the transport, because Starlette matches in
insertion order and a ``/mcp`` mount would otherwise shadow it. The manifest route is
also installed unconditionally, before the SDK is even imported, so that a deployment
without ``mcp`` still serves a descriptor saying so.


Where the A2UI messages ride
----------------------------
See the long comment in ``manifest.py``. Short version: every tool result carries the
same envelope stream in three places - an ``EmbeddedResource`` with mimeType
``application/vnd.a2ui+json``, ``result._meta["a2ui/messages"]``, and
``structuredContent["a2ui"]`` - plus a plain-text summary so a text-only client still
gets something worth reading.


Degradation
-----------
No tool raises. Every one of them runs its body inside :func:`_guard`, which converts any
exception into ``ok=false``, a structured :class:`~.manifest.ToolError`, and an error
surface from ``build_error_surface``. A stack trace never reaches the wire.

Every import of the A2UI builders and of the container happens *inside* the tool bodies.
A half-finished subsystem can make a tool degrade; it cannot stop the server mounting.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from .manifest import (
    A2UI_MEDIA_TYPE,
    A2UI_MESSAGES_META_KEY,
    A2UI_RESOURCE_SCHEME,
    A2UI_TOOL_META_KEY,
    A2UI_VERSION,
    MCP_MOUNT_PATH,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    SERVER_TITLE,
    SERVER_VERSION,
    ExplainPlaylistInput,
    ExplainPlaylistOutput,
    ForgePlaylistInput,
    ForgePlaylistOutput,
    GetSkyVectorInput,
    GetSkyVectorOutput,
    ListThemesInput,
    ListThemesOutput,
    SavePlaylistInput,
    SavePlaylistOutput,
    ToolError,
    ToolResultBase,
    a2ui_catalog_descriptor,
    install_manifest_route,
    tool_spec,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

logger = logging.getLogger("barogroove.mcp")

__all__ = ["mount_mcp", "build_mcp_server", "MCP_MOUNT_PATH"]

#: Marks the host app so a second ``mount_mcp`` is a no-op rather than a second session
#: manager fighting the first one for the same path.
_MOUNTED_FLAG: Final[str] = "_barogroove_mcp_mounted"


# ======================================================================================
# SDK loading
# ======================================================================================


def _load_server_class() -> type[Any]:
    """Return the SDK's server class, whichever era of the SDK is installed.

    Raises:
        ImportError: if neither spelling is importable. ``mount_mcp`` catches it.
    """
    try:
        from mcp.server.mcpserver import MCPServer  # type: ignore[import-not-found]

        return MCPServer
    except Exception as modern_exc:  # noqa: BLE001 - we want the 1.x path on any failure
        try:
            from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]

            return FastMCP
        except Exception as legacy_exc:  # noqa: BLE001
            raise ImportError(
                "Neither mcp.server.mcpserver.MCPServer (SDK 2.x) nor "
                f"mcp.server.fastmcp.FastMCP (SDK 1.x) is importable: {modern_exc!r} / {legacy_exc!r}"
            ) from legacy_exc


# ======================================================================================
# A2UI plumbing - lazy, forgiving, and never hand-rolling a component
# ======================================================================================


def _surfaces() -> Any:
    """Import the single source of UI truth. Late, and only from inside a tool body."""
    from ..a2ui import surfaces

    return surfaces


def _error_stream(message: str, *, detail: str | None = None, surface_id: str | None = None) -> list[dict[str, Any]]:
    """An error surface from the builder, or an empty stream if even that is unavailable.

    Returning ``[]`` is the honest answer when the A2UI module itself is the thing that
    broke: the structured error still reaches the client, and we have not invented a
    component dict to paper over it.
    """
    try:
        built = _surfaces().build_error_surface(message, detail=detail, surface_id=surface_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("build_error_surface unavailable, returning a bare structured error: %s", exc)
        return []
    return [dict(item) for item in built]


def _first_surface_id(messages: Sequence[Mapping[str, Any]]) -> str | None:
    """Read the surfaceId out of an envelope stream without assuming message order."""
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        for body in message.values():
            if isinstance(body, Mapping):
                candidate = body.get("surfaceId") or body.get("surface_id")
                if isinstance(candidate, str) and candidate:
                    return candidate
    return None


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of a pydantic model / dataclass / scalar into JSON data.

    The contracts module is frozen pydantic v2, so ``model_dump(mode="json")`` covers
    almost everything; the rest of the ladder is for the odd dataclass or enum that
    slips through a container implementation we do not own.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:  # pragma: no cover - non-pydantic object with a model_dump
            pass
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        try:
            return as_dict()
        except Exception:  # pragma: no cover
            pass
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return json.loads(json.dumps(value, default=str))


# ======================================================================================
# Result packaging
# ======================================================================================


def _summary_text(payload: ToolResultBase, headline: str) -> str:
    """One short human-readable block, for hosts that render nothing but text."""
    if not payload.ok and payload.error is not None:
        line = f"BAROGROOVE / {payload.tool}: {payload.error.message}"
        return f"{line} ({payload.error.detail})" if payload.error.detail else line
    if payload.degraded:
        return f"{headline}\n(degraded: {', '.join(payload.degraded)})"
    return headline


def _pack(payload: ToolResultBase, headline: str) -> Any:
    """Turn a result model into a ``CallToolResult`` carrying A2UI in all three places.

    Falls back to returning the plain dict if the SDK's types are not importable, in
    which case the SDK derives content from the return value and the A2UI stream still
    reaches the client inside ``structuredContent["a2ui"]``.
    """
    structured = payload.model_dump(mode="json")

    try:
        from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents
    except Exception:  # pragma: no cover - only when mcp.types moves again
        return structured

    content: list[Any] = [TextContent(type="text", text=_summary_text(payload, headline))]

    # Placement 1: an embedded resource. This is the shape the official "A2UI over MCP"
    # recipe uses for carrying surfaces on a tool result, and the one a generic
    # A2UI-aware host is most likely to look for.
    if payload.a2ui:
        surface_id = payload.surface_id or payload.tool
        try:
            content.append(
                EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri=f"{A2UI_RESOURCE_SCHEME}/surface/{surface_id}",  # type: ignore[arg-type]
                        mimeType=A2UI_MEDIA_TYPE,
                        text=json.dumps(payload.a2ui, separators=(",", ":")),
                    ),
                )
            )
        except Exception as exc:  # pragma: no cover - URI validation differs by version
            logger.debug("could not embed the A2UI resource block: %s", exc)

    # Placement 2: result._meta. Unwrapped, for renderers that would rather not parse a
    # resource body. Key spelling is UNVERIFIED - see manifest.py.
    meta: dict[str, Any] = {
        A2UI_MESSAGES_META_KEY: payload.a2ui,
        A2UI_TOOL_META_KEY: {
            "version": A2UI_VERSION,
            "surfaceId": payload.surface_id,
            "catalogId": a2ui_catalog_descriptor()["id"],
            "mediaType": A2UI_MEDIA_TYPE,
        },
    }

    try:
        return CallToolResult(
            content=content,
            structuredContent=structured,  # placement 3
            _meta=meta,
            isError=False,
        )
    except Exception:  # pragma: no cover - field aliasing differs between SDK versions
        try:
            return CallToolResult(
                content=content,
                structured_content=structured,
                meta=meta,
                is_error=False,
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("CallToolResult construction failed, returning structured dict: %s", exc)
            return structured


async def _guard(
    tool_name: str,
    body: Callable[[], Any],
    output_model: type[ToolResultBase],
    headline: str,
) -> Any:
    """Run a tool body; convert any failure into an error surface plus a structured error.

    This is the only ``except Exception`` a tool needs. ``BarogrooveError`` subclasses get
    their own code derived from the class name, so ``ThemeNotFound`` surfaces as
    ``theme_not_found`` rather than as a generic failure.
    """
    try:
        return await body()
    except Exception as exc:  # noqa: BLE001 - the boundary. Nothing propagates past here.
        code = "tool_failed"
        with contextlib.suppress(Exception):
            from ..errors import BarogrooveError

            if isinstance(exc, BarogrooveError):
                name = type(exc).__name__
                code = "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")
        logger.exception("MCP tool %s failed", tool_name)
        message = str(exc) or f"{tool_name} failed."
        stream = _error_stream(message, detail=type(exc).__name__)
        payload = output_model(
            ok=False,
            tool=tool_name,
            a2ui=stream,
            surface_id=_first_surface_id(stream),
            error=ToolError(code=code, message=message, detail=type(exc).__name__),
        )
        return _pack(payload, headline=f"BAROGROOVE could not complete {tool_name}.")


# ======================================================================================
# Tool bodies
# ======================================================================================
#
# Each body is a plain async function so it can be unit-tested without the SDK. The
# registration wrappers further down give the SDK the explicit signatures it derives
# input schemas from, and immediately re-validate through the manifest's pydantic model
# so that the advertised schema and the enforced schema cannot drift.


async def _run_get_sky_vector(args: GetSkyVectorInput) -> Any:
    spec = tool_spec("get_sky_vector")

    async def body() -> Any:
        from ..container import get_container
        from ..contracts import Coordinates
        from ..errors import DegradationLedger
        from ..sky.extract import extract_sky_vector

        surfaces = _surfaces()
        coordinates = Coordinates(latitude=args.lat, longitude=args.lon, label=args.label)

        ledger: Any | None = None
        with contextlib.suppress(Exception):
            ledger = DegradationLedger()

        window = await get_container().weather().window(coordinates, args.scenario)
        sky = extract_sky_vector(window, ledger=ledger)

        stream = [dict(m) for m in surfaces.build_sky_surface(sky, surface_id=None)]
        degraded = list(getattr(ledger, "entries", None) or []) if ledger is not None else []
        if getattr(sky, "stale", False):
            degraded.append("weather:stale")
        if args.scenario:
            degraded.append(f"weather:synthetic:{args.scenario}")

        observed_at = getattr(sky, "observed_at", None)

        payload = GetSkyVectorOutput(
            ok=True,
            tool=spec.name,
            a2ui=stream,
            surface_id=_first_surface_id(stream),
            degraded=[str(d) for d in degraded],
            sky=_jsonable(sky.as_dict()),
            observed_at=None if observed_at is None else str(observed_at),
            stale=bool(getattr(sky, "stale", False)),
            notes=[str(n) for n in (getattr(sky, "notes", None) or [])],
            coordinates=_jsonable(coordinates),
        )
        return _pack(payload, headline=f"Sky over {args.label or f'{args.lat:.3f}, {args.lon:.3f}'} read.")

    return await _guard(spec.name, body, GetSkyVectorOutput, "sky reading")


async def _run_list_themes(args: ListThemesInput) -> Any:
    spec = tool_spec("list_themes")

    async def body() -> Any:
        from ..sonic.corridors import list_corridors
        from ..sonic.themes import list_themes

        surfaces = _surfaces()
        themes = list_themes()
        corridors = list_corridors()
        stream = [dict(m) for m in surfaces.build_themes_surface(themes, corridors, surface_id=None)]

        payload = ListThemesOutput(
            ok=True,
            tool=spec.name,
            a2ui=stream,
            surface_id=_first_surface_id(stream),
            themes=[_jsonable(t) for t in themes],
            corridors=[_jsonable(c) for c in corridors],
        )
        return _pack(
            payload,
            headline=f"{len(themes)} themes and {len(corridors)} genre corridors available.",
        )

    return await _guard(spec.name, body, ListThemesOutput, "theme catalogue")


async def _run_forge_playlist(args: ForgePlaylistInput) -> Any:
    spec = tool_spec("forge_playlist")

    async def body() -> Any:
        from ..container import get_container
        from ..contracts import Coordinates, ForgeRequest

        surfaces = _surfaces()
        coordinates = Coordinates(latitude=args.lat, longitude=args.lon, label=args.label)
        request = ForgeRequest(
            coordinates=coordinates,
            theme_id=args.theme,
            genre_id=args.genre or "any",
            length=args.length,
            lastfm_user=args.lastfm_user,
            seed=args.seed,
        )
        result = await get_container().forge().forge(request)
        playlist = result.playlist

        stream = [dict(m) for m in surfaces.build_playlist_surface(playlist, surface_id=None)]
        tracks = list(getattr(playlist, "tracks", None) or [])

        payload = ForgePlaylistOutput(
            ok=True,
            tool=spec.name,
            a2ui=stream,
            surface_id=_first_surface_id(stream),
            degraded=[str(d) for d in (result.degraded or [])],
            playlist=_jsonable(playlist),
            playlist_id=str(getattr(playlist, "id", "") or "") or None,
            track_count=len(tracks),
            theme_id=getattr(playlist, "theme_id", None),
            genre_id=getattr(playlist, "genre_id", None),
            sonic_target=_jsonable(getattr(playlist, "sonic_target", None)) or {},
            sky=_jsonable(getattr(getattr(playlist, "sky", None), "as_dict", dict)()) or {},
            elapsed_ms=int(getattr(result, "elapsed_ms", 0) or 0),
        )
        title = getattr(playlist, "title", None) or "Playlist"
        return _pack(payload, headline=f"{title} - {len(tracks)} tracks forged from the sky.")

    return await _guard(spec.name, body, ForgePlaylistOutput, "playlist")


async def _run_explain_playlist(args: ExplainPlaylistInput) -> Any:
    spec = tool_spec("explain_playlist")

    async def body() -> Any:
        surfaces = _surfaces()

        if not args.playlist_id and not args.playlist:
            raise ValueError("explain_playlist needs either playlist_id or an inline playlist object.")

        playlist: Any = None
        rationale: Any = None
        playlist_id = args.playlist_id

        if args.playlist_id:
            from ..container import get_container

            almanac = get_container().almanac()
            # ``history`` is the frozen interface. A store that also offers a direct
            # lookup is used when present, because scanning history is wasteful.
            getter = getattr(almanac, "get", None) or getattr(almanac, "fetch", None)
            if callable(getter):
                candidate = getter(args.playlist_id)
                if hasattr(candidate, "__await__"):
                    candidate = await candidate
                playlist = candidate
            if playlist is None:
                for entry in await almanac.history(None, 200):
                    if str(getattr(entry, "id", "")) == args.playlist_id:
                        playlist = entry
                        break
            if playlist is None:
                raise LookupError(f"No playlist with id '{args.playlist_id}' in the almanac.")
            rationale = getattr(playlist, "rationale", None)
        else:
            raw = args.playlist or {}
            playlist_id = str(raw.get("id") or "") or None
            rationale = raw.get("rationale")
            if rationale is None:
                raise ValueError("The inline playlist carries no rationale to explain.")
            # Re-hydrate so the builder gets the type it expects; if the contract model
            # rejects it, fall through with the raw mapping and let the builder decide.
            with contextlib.suppress(Exception):
                from ..contracts import Rationale

                rationale = Rationale(**rationale) if isinstance(rationale, dict) else rationale

        if rationale is None:
            raise ValueError("That playlist has no rationale attached.")

        stream = [dict(m) for m in surfaces.build_rationale_surface(rationale, surface_id=None)]
        confidence = getattr(rationale, "confidence", None)
        if confidence is None and isinstance(rationale, Mapping):
            confidence = rationale.get("confidence")
        headline_text = getattr(rationale, "headline", None)
        if headline_text is None and isinstance(rationale, Mapping):
            headline_text = rationale.get("headline")

        degraded = list(getattr(rationale, "degraded", None) or [])

        payload = ExplainPlaylistOutput(
            ok=True,
            tool=spec.name,
            a2ui=stream,
            surface_id=_first_surface_id(stream),
            degraded=[str(d) for d in degraded],
            playlist_id=playlist_id,
            rationale=_jsonable(rationale) or {},
            headline=None if headline_text is None else str(headline_text),
            confidence=None if confidence is None else float(confidence),
        )
        return _pack(payload, headline=str(headline_text or "Rationale ready."))

    return await _guard(spec.name, body, ExplainPlaylistOutput, "rationale")


async def _run_save_playlist(args: SavePlaylistInput) -> Any:
    spec = tool_spec("save_playlist")

    async def body() -> Any:
        from ..container import get_container
        from ..sinks.registry import write_playlist

        surfaces = _surfaces()
        container = get_container()
        almanac = container.almanac()

        playlist = None
        getter = getattr(almanac, "get", None) or getattr(almanac, "fetch", None)
        if callable(getter):
            candidate = getter(args.playlist_id)
            if hasattr(candidate, "__await__"):
                candidate = await candidate
            playlist = candidate
        if playlist is None:
            for entry in await almanac.history(args.user_id, 200):
                if str(getattr(entry, "id", "")) == args.playlist_id:
                    playlist = entry
                    break
        if playlist is None:
            raise LookupError(f"No playlist with id '{args.playlist_id}' in the almanac.")

        sink_result = await write_playlist(
            container.sinks(),
            playlist,
            kind=args.sink or "auto",
            user_id=args.user_id,
        )

        # There is no dedicated "saved" builder in the frozen interface, and inventing
        # one here would be inventing UI. The playlist surface is the correct thing to
        # re-render: it is the same object, now with a sink attached.
        with contextlib.suppress(Exception):
            setattr(playlist, "sink", sink_result)
        stream = [dict(m) for m in surfaces.build_playlist_surface(playlist, surface_id=None)]

        as_json = _jsonable(sink_result) or {}
        url = as_json.get("url") if isinstance(as_json, Mapping) else None
        kind = as_json.get("kind") if isinstance(as_json, Mapping) else None

        payload = SavePlaylistOutput(
            ok=True,
            tool=spec.name,
            a2ui=stream,
            surface_id=_first_surface_id(stream),
            playlist_id=args.playlist_id,
            sink=str(kind) if kind else (args.sink or None),
            sink_result=as_json if isinstance(as_json, dict) else {"value": as_json},
            url=str(url) if url else None,
        )
        return _pack(payload, headline=f"Playlist saved to {kind or args.sink}.")

    return await _guard(spec.name, body, SavePlaylistOutput, "save result")


# ======================================================================================
# Registration
# ======================================================================================


def _register_tools(server: Any) -> None:
    """Attach the five tools.

    The SDK derives each tool's input schema from the wrapper's signature, so the
    wrappers spell their parameters out explicitly rather than taking a model. The very
    first thing every wrapper does is round-trip those parameters through the manifest's
    pydantic model, which means the advertised schema and the enforced constraints come
    from one definition even though they travel by two routes.

    ``Annotated[CallToolResult, OutputModel]`` is the SDK 2.x idiom for "I will build the
    CallToolResult myself, and here is the output schema to publish and validate against".
    On an SDK where that annotation is not understood we register the wrappers unannotated
    and the SDK derives content from the returned value; the A2UI stream survives either
    way because it lives inside the structured payload.

    The return annotations are assigned as *objects* after the fact rather than written
    into the ``def`` line. ``from __future__ import annotations`` stringifies every
    annotation in this module, and the SDK resolves them with ``get_type_hints`` against
    the function's module globals - where a closure-local helper does not exist. Assigning
    the real object sidesteps the eval entirely. Parameter annotations are left as strings
    because ``float``, ``str | None`` and ``dict[str, Any]`` all resolve fine up there.
    """
    from typing import Annotated  # local: keeps the module importable without the SDK

    try:
        from mcp.types import CallToolResult

        def _ret(model: type[ToolResultBase]) -> Any:
            return Annotated[CallToolResult, model]

    except Exception:  # pragma: no cover

        def _ret(model: type[ToolResultBase]) -> Any:
            return model

    sky = tool_spec("get_sky_vector")
    themes = tool_spec("list_themes")
    forge = tool_spec("forge_playlist")
    explain = tool_spec("explain_playlist")
    save = tool_spec("save_playlist")

    def _meta_for(name: str) -> dict[str, Any]:
        """Tool-level ``_meta``, advertising the A2UI binding before it is ever called."""
        return dict(tool_spec(name).as_dict()["_meta"])

    async def get_sky_vector(
        lat: float,
        lon: float,
        scenario: str | None = None,
        label: str | None = None,
    ):
        return await _run_get_sky_vector(
            GetSkyVectorInput.model_validate({"lat": lat, "lon": lon, "scenario": scenario, "label": label})
        )

    async def list_themes():
        return await _run_list_themes(ListThemesInput())

    async def forge_playlist(
        lat: float,
        lon: float,
        theme: str | None = None,
        genre: str = "any",
        length: int = 18,
        lastfm_user: str | None = None,
        label: str | None = None,
        seed: int | None = None,
    ):
        return await _run_forge_playlist(
            ForgePlaylistInput.model_validate(
                {
                    "lat": lat,
                    "lon": lon,
                    "theme": theme,
                    "genre": genre,
                    "length": length,
                    "lastfm_user": lastfm_user,
                    "label": label,
                    "seed": seed,
                }
            )
        )

    async def explain_playlist(
        playlist_id: str | None = None,
        playlist: dict[str, Any] | None = None,
    ):
        return await _run_explain_playlist(
            ExplainPlaylistInput.model_validate({"playlist_id": playlist_id, "playlist": playlist})
        )

    async def save_playlist(
        playlist_id: str,
        sink: str = "auto",
        user_id: str | None = None,
    ):
        return await _run_save_playlist(
            SavePlaylistInput.model_validate({"playlist_id": playlist_id, "sink": sink, "user_id": user_id})
        )

    pairs = (
        (get_sky_vector, sky, GetSkyVectorOutput),
        (list_themes, themes, ListThemesOutput),
        (forge_playlist, forge, ForgePlaylistOutput),
        (explain_playlist, explain, ExplainPlaylistOutput),
        (save_playlist, save, SavePlaylistOutput),
    )
    for fn, spec, out_model in pairs:
        fn.__doc__ = spec.description
        # Real object, not a string: see the docstring above.
        fn.__annotations__["return"] = _ret(out_model)
        kwargs: dict[str, Any] = {
            "name": spec.name,
            "title": spec.title,
            "description": spec.description,
        }
        with contextlib.suppress(Exception):
            kwargs["meta"] = _meta_for(spec.name)
        with contextlib.suppress(Exception):
            from mcp.types import ToolAnnotations

            kwargs["annotations"] = ToolAnnotations(
                title=spec.title,
                readOnlyHint=spec.read_only,
                idempotentHint=spec.idempotent,
                openWorldHint=spec.open_world,
            )
        try:
            server.add_tool(fn, **kwargs)
        except TypeError:
            # Older SDKs accept fewer keywords. Name and description are the two that
            # actually matter for tool selection; drop the rest rather than fail.
            server.add_tool(fn, name=spec.name, description=spec.description)


def build_mcp_server() -> Any:
    """Construct and populate the MCP server object. No transport, no mounting.

    Split out so tests can introspect tools without standing up an HTTP app.
    """
    server_cls = _load_server_class()
    try:
        server = server_cls(
            name=SERVER_NAME,
            title=SERVER_TITLE,
            version=SERVER_VERSION,
            instructions=SERVER_INSTRUCTIONS,
        )
    except TypeError:
        # SDK 1.x FastMCP has no `title`/`version` keyword.
        server = server_cls(name=SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    _register_tools(server)
    return server


# ======================================================================================
# Transport attachment and lifespan composition
# ======================================================================================


def _transport_security() -> Any | None:
    """Allow the public host through the SDK's DNS-rebinding guard.

    ``streamable_http_app`` auto-enables rebinding protection whenever ``host`` looks
    like localhost - which is the default - and then rejects any request whose Host
    header is not in the allow-list. Behind a proxy at ``bg.netdev.be`` that is every
    real request. We build the settings explicitly instead, listing the configured
    public host alongside the local ones and Starlette's ``testserver``.
    """
    try:
        from mcp.server.transport_security import TransportSecuritySettings
    except Exception:  # pragma: no cover
        return None

    public_host = "bg.netdev.be"
    with contextlib.suppress(Exception):
        from ..config import get_settings

        public_host = str(getattr(get_settings(), "public_host", public_host) or public_host)

    hosts = [
        public_host,
        f"{public_host}:*",
        "127.0.0.1:*",
        "localhost:*",
        "[::1]:*",
        "testserver",
        "testserver:*",
    ]
    origins = [f"https://{public_host}", f"http://{public_host}"] + [
        f"http://{h}" for h in ("127.0.0.1:*", "localhost:*", "[::1]:*")
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def _build_http_app(server: Any) -> Any:
    """Ask the SDK for its streamable-HTTP Starlette app, configured for our host."""
    kwargs: dict[str, Any] = {
        "streamable_http_path": MCP_MOUNT_PATH,
        "json_response": False,
        # Stateless keeps this horizontally scalable: no server-side session affinity,
        # which matters the moment there is more than one pod behind the proxy.
        "stateless_http": True,
    }
    security = _transport_security()
    if security is not None:
        kwargs["transport_security"] = security
    try:
        return server.streamable_http_app(**kwargs)
    except TypeError:
        # SDK 1.x takes these as constructor settings rather than call keywords.
        return server.streamable_http_app()


def _extract_endpoint(http_app: Any) -> Any:
    """Pull the raw ASGI handler for ``/mcp`` out of the SDK's Starlette app.

    ``streamable_http_app()`` builds exactly one flat ``Route`` whose endpoint is a
    ``StreamableHTTPASGIApp``. Starlette stores a non-function endpoint on ``route.app``
    verbatim, so that attribute is the handler we want - the surrounding Starlette router
    adds nothing we are not already doing on the host router.

    Raises:
        RuntimeError: if the SDK's app does not have the shape we expect, so the caller
            can log it and leave the endpoint dark rather than half-wire it.
    """
    middleware = list(getattr(http_app, "user_middleware", None) or [])
    if middleware:
        # We do not configure auth, so this should be empty. If a future SDK wraps the
        # transport in middleware, forwarding to the bare route would silently drop it.
        raise RuntimeError(f"the SDK app carries {len(middleware)} middleware; refusing to bypass it")

    for route in getattr(http_app, "routes", None) or []:
        if getattr(route, "path", None) != MCP_MOUNT_PATH:
            continue
        endpoint = getattr(route, "app", None) or getattr(route, "endpoint", None)
        if endpoint is not None:
            return endpoint
    raise RuntimeError(f"the SDK app exposes no route at {MCP_MOUNT_PATH}")


class _MCPTransport:
    """Exact-path ASGI endpoint for ``/mcp``, rebindable across lifespan cycles.

    The host router holds a reference to *this* object forever. What it forwards to is
    swapped in at startup and dropped at shutdown, which is what lets a fresh session
    manager be created per cycle without touching the routing table.

    Not callable as a plain function, deliberately: Starlette treats a function endpoint
    as a request/response handler and anything else as a raw ASGI app, and raw ASGI is
    what the streamable-HTTP transport needs in order to stream.
    """

    __slots__ = ("_app",)

    def __init__(self) -> None:
        self._app: Any | None = None

    @property
    def live(self) -> bool:
        return self._app is not None

    def activate(self, asgi_app: Any) -> None:
        self._app = asgi_app

    def deactivate(self) -> None:
        self._app = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        current = self._app
        if current is None:
            await self._unavailable(scope, receive, send)
            return
        await current(scope, receive, send)

    @staticmethod
    async def _unavailable(scope: Any, receive: Any, send: Any) -> None:
        """503 with a JSON-RPC-shaped body, rather than an exception into the log.

        Reachable when the session manager failed to start. The REST API is fine; this
        one endpoint is not, and saying so is more useful than a 500.
        """
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32000, "message": "The BAROGROOVE MCP transport is not running."},
                "id": None,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _attach_transport(app: FastAPI, transport: _MCPTransport) -> str:
    """Register the exact-path ``/mcp`` route on the host router.

    ``methods`` is left unset so the route matches POST (requests), GET (the SSE stream)
    and DELETE (session teardown) alike - the streamable-HTTP transport uses all three
    and decides for itself which are acceptable.
    """
    from starlette.routing import Route

    app.router.routes.append(Route(MCP_MOUNT_PATH, endpoint=transport, name="mcp"))
    return f"exact-path route at {MCP_MOUNT_PATH}"


def _compose_lifespan(app: FastAPI, server: Any, transport: _MCPTransport) -> None:
    """Run the MCP session manager *inside* the host's existing lifespan.

    This is the part that goes wrong. ``streamable_http_app()`` returns a Starlette app
    whose lifespan is ``session_manager.run()``, but Starlette never invokes a mounted
    sub-app's lifespan - only the outermost one runs. So the session manager's task group
    is never entered, and the endpoint fails on the first request.

    The host app already owns a lifespan (it closes the shared httpx pool), and that one
    is frozen. We therefore *wrap* rather than replace: take the current
    ``app.router.lifespan_context``, and return a new async context manager that enters
    the host's first and the session manager second.

    Nesting order is deliberate:

        host startup  ->  MCP startup  ->  [serving]  ->  MCP shutdown  ->  host shutdown

    The MCP layer is the inner context, so on the way down it drains its sessions
    *before* the host closes the httpx pool those sessions were using. Inverting this
    gives you tool calls reaching for a closed pool during shutdown.

    The transport is rebuilt on every cycle, not captured once at mount time. A
    ``StreamableHTTPSessionManager`` refuses a second ``run()``, so reusing one instance
    across two lifespans gives you a working endpoint the first time and a permanently
    broken one thereafter. Building inside the lifespan means each cycle gets a fresh
    session manager, and :class:`_MCPTransport` is what lets the routing table stay put
    while the thing behind it is replaced.

    Failure to start the session manager is logged and swallowed: the host lifespan has
    already yielded, so REST keeps serving and ``/mcp`` answers 503 rather than the whole
    process refusing to boot. The state object the host lifespan yields is passed straight
    through, untouched.
    """
    host_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def composed(scoped_app: FastAPI) -> AsyncIterator[Any]:
        async with host_lifespan(scoped_app) as state:
            async with contextlib.AsyncExitStack() as stack:
                try:
                    endpoint = _extract_endpoint(_build_http_app(server))
                    await stack.enter_async_context(server.session_manager.run())
                    transport.activate(endpoint)
                    # Registered after activate, so it runs before the session manager
                    # stops: the endpoint stops accepting first, then drains.
                    stack.callback(transport.deactivate)
                    logger.info("MCP streamable-HTTP session manager running at %s", MCP_MOUNT_PATH)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "MCP session manager failed to start; %s will answer 503 and the REST API "
                        "will serve normally",
                        MCP_MOUNT_PATH,
                    )
                yield state

    app.router.lifespan_context = composed


# ======================================================================================
# The entry point main.py calls
# ======================================================================================


def mount_mcp(app: FastAPI) -> None:
    """Attach the BAROGROOVE MCP server to ``app`` at ``/mcp``.

    Order of operations:

    1. ``GET /mcp/manifest`` first and unconditionally, so a deployment without the SDK
       still describes itself, and so the manifest route is ahead of anything matching
       ``/mcp`` in the router's insertion-ordered table.
    2. Build the server and register the five tools.
    3. Build the streamable-HTTP app once, purely to validate the configuration - a bad
       transport setting should fail here, at import, and not on the first request.
    4. Attach the rebindable transport route.
    5. Compose the per-cycle session manager into the host's lifespan.

    Non-fatal by construction. ``main.py`` wraps this call in a try/except that logs and
    continues, and this function does the same internally: a missing ``mcp`` package, an
    SDK rename, or a transport failure leaves the REST API completely intact. The only
    thing that changes is that ``/mcp`` is not there.

    Idempotent: a second call on the same app logs and returns.
    """
    if getattr(app.state, _MOUNTED_FLAG, False):
        logger.debug("mount_mcp called twice; ignoring the second call")
        return

    # Step 1. Cheap, dependency-free, and useful even when everything below fails.
    try:
        install_manifest_route(app)
    except Exception:  # noqa: BLE001
        logger.exception("could not install the MCP manifest route")

    try:
        server = build_mcp_server()
    except Exception:  # noqa: BLE001
        logger.exception("MCP server could not be built; serving REST only")
        return

    try:
        # Built and thrown away. Its session manager is never run; the point is to make a
        # misconfigured transport fail loudly at import time instead of at first request.
        _extract_endpoint(_build_http_app(server))
    except Exception:  # noqa: BLE001
        logger.exception("MCP streamable-HTTP app could not be built; serving REST only")
        return

    transport = _MCPTransport()
    try:
        how = _attach_transport(app, transport)
    except Exception:  # noqa: BLE001
        logger.exception("MCP transport could not be attached; serving REST only")
        return

    try:
        _compose_lifespan(app, server, transport)
    except Exception:  # noqa: BLE001
        # An attached endpoint with no running session manager would 500 on every call.
        # Better to say so loudly in the log than to pretend the mount succeeded.
        logger.exception("MCP lifespan composition failed; %s is attached but will not serve", MCP_MOUNT_PATH)
        return

    setattr(app.state, _MOUNTED_FLAG, True)
    setattr(app.state, "barogroove_mcp_server", server)
    logger.info("BAROGROOVE MCP v%s attached: %s", SERVER_VERSION, how)
