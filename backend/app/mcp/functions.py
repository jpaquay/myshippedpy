"""Agent-side handlers for A2UI ``callAgentFunction`` round-trips.

This is the module that stops the theme chips from being decoration. In A2UI v1.0 a
renderer may invoke a *typed* function on the agent - ``callAgentFunction`` - and the
agent answers with ``agentFunctionResponse`` plus, usually, a fresh batch of
agent-to-renderer messages that mutate the UI. Without this file the Flutter app can
draw a theme chip; with it, tapping the chip actually changes what BAROGROOVE thinks.

Four functions, matching what the A2UI catalog declares:

===================  ==============================================================
``selectTheme``      user tapped a theme chip -> re-render the themes surface
``selectGenre``      user moved the genre corridor -> re-render the themes surface
``rateTrack``        user loved or skipped a track -> patch the surface data model
``reforge``          user asked for another pass -> a whole new playlist surface
===================  ==============================================================

Two rules govern everything below.

1. **No hand-rolled A2UI JSON.** Follow-up messages come from the builders in
   ``app.a2ui.surfaces`` or, for a bare data-model patch that has no builder, from the
   typed envelope models in ``app.a2ui.protocol``. There is a last-resort literal in
   :func:`_data_model_message` and it is fenced off, commented, and only reachable when
   ``protocol.py`` exposes neither of the two shapes we know about.

2. **Everything is lazy.** ``app.a2ui`` and ``app.container`` are imported inside
   function bodies. This module must stay importable - and its registry must stay
   introspectable by the manifest and the tests - even when every other subsystem in the
   application is missing or broken.

The registry is shared: ``server.py`` dispatches into it from MCP, and the REST
``/api/surfaces/action`` endpoint dispatches into the same objects. One definition.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger("barogroove.mcp.functions")

__all__ = [
    "AgentFunctionError",
    "SelectThemeArgs",
    "SelectGenreArgs",
    "RateTrackArgs",
    "ReforgeArgs",
    "AgentFunction",
    "DispatchResult",
    "REGISTRY",
    "FUNCTION_NAMES",
    "resolve",
    "argument_model",
    "dispatch",
    "agent_function_response",
    "handle_select_theme",
    "handle_select_genre",
    "handle_rate_track",
    "handle_reforge",
]

A2UI_VERSION: Final[str] = "1.0"

#: Default surface ids. The builders accept ``surface_id=`` and the renderer echoes
#: whichever id it was given, so these are only used when a caller omits one.
DEFAULT_THEMES_SURFACE: Final[str] = "barogroove.themes"
DEFAULT_PLAYLIST_SURFACE: Final[str] = "barogroove.playlist"


class AgentFunctionError(Exception):
    """A handler failed in a way the renderer should be told about, politely.

    Carries a stable code so the Flutter side can branch without string-matching.
    """

    def __init__(self, code: str, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


# ======================================================================================
# Argument models
# ======================================================================================


class _Args(BaseModel):
    """Base for callAgentFunction payloads.

    ``extra="forbid"`` is deliberate: a renderer that invents a field is a renderer
    running against a catalog we did not publish, and we would rather say so than
    silently ignore it. ``populate_by_name`` lets the camelCase wire names through
    alongside the snake_case Python ones.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    surface_id: str | None = Field(
        default=None,
        alias="surfaceId",
        max_length=200,
        description="Surface the interaction originated on. Follow-up messages target it.",
    )


class SelectThemeArgs(_Args):
    """Payload for a theme chip tap."""

    theme_id: str = Field(
        alias="themeId",
        min_length=1,
        max_length=64,
        description="Id of the chosen theme, from the themes surface data model.",
    )
    genre_id: str | None = Field(
        default=None,
        alias="genreId",
        max_length=64,
        description="Genre corridor currently selected, so the re-render keeps it.",
    )


class SelectGenreArgs(_Args):
    """Payload for a genre-corridor change."""

    genre_id: str = Field(
        alias="genreId",
        min_length=1,
        max_length=64,
        description="Id of the chosen corridor, or 'any' to release the constraint.",
    )
    theme_id: str | None = Field(
        default=None,
        alias="themeId",
        max_length=64,
        description="Theme currently selected, so the re-render keeps it.",
    )


class RateTrackArgs(_Args):
    """Payload for a love/skip verdict on one track."""

    playlist_id: str = Field(
        alias="playlistId", min_length=1, max_length=128, description="Playlist the track belongs to."
    )
    track_id: str = Field(alias="trackId", min_length=1, max_length=200, description="Track being rated.")
    verdict: Literal["love", "skip", "clear"] = Field(
        description="'love' pins the track, 'skip' demotes it, 'clear' removes a previous verdict."
    )
    user_id: str | None = Field(default=None, alias="userId", max_length=128, description="Who rated it.")


class ReforgeArgs(_Args):
    """Payload for 'do that again, but ...'."""

    lat: float = Field(ge=-90.0, le=90.0, description="Latitude in decimal degrees.")
    lon: float = Field(ge=-180.0, le=180.0, description="Longitude in decimal degrees.")
    theme_id: str | None = Field(default=None, alias="themeId", max_length=64, description="Theme to force.")
    genre_id: str | None = Field(default=None, alias="genreId", max_length=64, description="Corridor to force.")
    length: int = Field(default=18, ge=4, le=60, description="Track count.")
    lastfm_user: str | None = Field(
        default=None, alias="lastfmUser", max_length=64, description="Optional Last.fm handle."
    )
    label: str | None = Field(default=None, max_length=120, description="Display name for the location.")
    seed: int | None = Field(default=None, ge=0, description="Deterministic seed, when reproducibility matters.")


# ======================================================================================
# A2UI emission helpers - the only places allowed to touch envelope shapes
# ======================================================================================


def _surfaces_module() -> Any:
    """Import the single source of UI truth, late.

    Raises:
        AgentFunctionError: if the builders are unavailable, so the caller can turn it
            into an ``agentFunctionResponse`` error rather than a 500.
    """
    try:
        from ..a2ui import surfaces
    except Exception as exc:  # pragma: no cover - depends on a sibling module landing
        raise AgentFunctionError(
            "a2ui_unavailable",
            "The A2UI surface builders are not available on this deployment.",
            detail=str(exc),
        ) from exc
    return surfaces


def _data_model_message(surface_id: str, contents: Mapping[str, Any], *, path: str = "/") -> dict[str, Any]:
    """Produce one ``updateDataModel`` envelope without hand-rolling it.

    Preference order, most-authoritative first:

    1. a purpose-built helper in ``app.a2ui.surfaces`` (``build_data_model_update`` or
       ``build_data_patch``) if that module grew one;
    2. the typed ``UpdateDataModel`` model from ``app.a2ui.protocol``, fed through that
       module's ``envelope()``;
    3. only if neither exists, the literal below.

    Step 3 is a hand-rolled dict and it is the one exception in this codebase. It is
    here because a data-model patch is the single follow-up shape the frozen builder
    interface does not cover, and a rating that silently does nothing is worse than a
    three-key literal that matches the v1.0 schema. It stays fenced behind two lookups
    so that it disappears the moment ``protocol.py`` exposes what we expect.
    """
    payload = dict(contents)

    surfaces = None
    try:
        surfaces = _surfaces_module()
    except AgentFunctionError:
        surfaces = None

    if surfaces is not None:
        for helper_name in ("build_data_model_update", "build_data_patch", "build_data_model_message"):
            helper = getattr(surfaces, helper_name, None)
            if callable(helper):
                try:
                    result = helper(surface_id, payload, path=path)
                except TypeError:
                    try:
                        result = helper(surface_id, payload)
                    except Exception:  # pragma: no cover - helper signature mismatch
                        continue
                except Exception:  # pragma: no cover - helper blew up
                    continue
                if isinstance(result, dict):
                    return result
                if isinstance(result, list) and result and isinstance(result[0], dict):
                    return result[0]

    try:
        from ..a2ui import protocol as _protocol
    except Exception:
        _protocol = None  # type: ignore[assignment]

    if _protocol is not None:
        model = getattr(_protocol, "UpdateDataModel", None)
        envelope = getattr(_protocol, "envelope", None)
        if model is not None and callable(envelope):
            for kwargs in (
                {"surfaceId": surface_id, "path": path, "contents": payload},
                {"surface_id": surface_id, "path": path, "contents": payload},
                {"surfaceId": surface_id, "contents": payload},
                {"surface_id": surface_id, "contents": payload},
            ):
                try:
                    message = model(**kwargs)  # type: ignore[operator]
                except Exception:
                    continue
                try:
                    produced = envelope(message)
                except Exception:  # pragma: no cover - envelope() disagreed
                    break
                if isinstance(produced, dict):
                    return produced

    # Last resort. Shape per A2UI v1.0: exactly one top-level key naming the message
    # type, whose value carries surfaceId plus the payload.
    return {"updateDataModel": {"surfaceId": surface_id, "path": path, "contents": payload}}


def _surface_id_of(messages: Sequence[Mapping[str, Any]], fallback: str | None = None) -> str | None:
    """Pull the surfaceId out of an envelope stream without assuming a message order."""
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        for body in message.values():
            if isinstance(body, Mapping):
                candidate = body.get("surfaceId") or body.get("surface_id")
                if isinstance(candidate, str) and candidate:
                    return candidate
    return fallback


def agent_function_response(
    name: str,
    *,
    surface_id: str | None = None,
    call_id: str | None = None,
    result: Mapping[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the ``agentFunctionResponse`` envelope that closes a callAgentFunction.

    A2UI v1.0 added the bidirectional function-call quartet (``callRendererFunction`` /
    ``callAgentFunction`` / ``rendererFunctionResponse`` / ``agentFunctionResponse``),
    verified against the runtime catalog. The envelope shape - one top-level key naming
    the message type - is confirmed.

    UNVERIFIED: the precise field spelling inside the body. We emit ``callId`` alongside
    ``functionCallId``, and ``name`` alongside ``functionName``, because the two
    spellings appear in different places in the published material and a renderer
    reading either will find what it wants. Emitting both is cheap; guessing wrong is
    a dead chip.
    """
    body: dict[str, Any] = {"name": name, "functionName": name}
    if surface_id:
        body["surfaceId"] = surface_id
    if call_id:
        body["callId"] = call_id
        body["functionCallId"] = call_id
    if error is not None:
        body["error"] = dict(error)
        body["success"] = False
    else:
        body["result"] = dict(result or {})
        body["success"] = True
    return {"agentFunctionResponse": body}


# ======================================================================================
# Handlers
# ======================================================================================


async def _themes_surface(
    *, selected_theme: str | None, selected_genre: str | None, surface_id: str
) -> list[dict[str, Any]]:
    """Re-render the themes surface with a new selection. Builders only."""
    surfaces = _surfaces_module()
    try:
        from ..sonic.corridors import list_corridors
        from ..sonic.themes import list_themes
    except Exception as exc:
        raise AgentFunctionError(
            "catalog_unavailable",
            "The theme and corridor catalogue could not be loaded.",
            detail=str(exc),
        ) from exc

    themes = list_themes()
    corridors = list_corridors()
    messages = surfaces.build_themes_surface(
        themes,
        corridors,
        selected_theme=selected_theme,
        selected_genre=selected_genre,
        surface_id=surface_id,
    )
    return [dict(message) for message in messages]


async def handle_select_theme(args: SelectThemeArgs) -> list[dict[str, Any]]:
    """User tapped a theme chip.

    We re-emit the whole themes surface under the *same* surfaceId rather than patching
    the data model by hand. A2UI v1.0's single-message instantiation makes a re-render
    cheap, the builder owns which chip renders as selected, and we get the follow-up for
    free without writing a component dict.
    """
    surface_id = args.surface_id or DEFAULT_THEMES_SURFACE
    messages = await _themes_surface(
        selected_theme=args.theme_id,
        selected_genre=args.genre_id,
        surface_id=surface_id,
    )
    # Belt and braces: a renderer that only listens for data-model deltas still learns
    # about the selection.
    messages.append(
        _data_model_message(
            surface_id,
            {"selectedThemeId": args.theme_id, "selectedGenreId": args.genre_id},
            path="/selection",
        )
    )
    return messages


async def handle_select_genre(args: SelectGenreArgs) -> list[dict[str, Any]]:
    """User moved the genre corridor. Same treatment as a theme tap."""
    surface_id = args.surface_id or DEFAULT_THEMES_SURFACE
    messages = await _themes_surface(
        selected_theme=args.theme_id,
        selected_genre=args.genre_id,
        surface_id=surface_id,
    )
    messages.append(
        _data_model_message(
            surface_id,
            {"selectedThemeId": args.theme_id, "selectedGenreId": args.genre_id},
            path="/selection",
        )
    )
    return messages


async def handle_rate_track(args: RateTrackArgs) -> list[dict[str, Any]]:
    """User loved or skipped a track.

    There is no builder for "one heart turned red", and re-forging the whole playlist
    because somebody tapped a heart would be obnoxious. So this is the one handler that
    emits a bare ``updateDataModel`` - via :func:`_data_model_message`, which prefers
    the typed protocol models over any literal.

    The verdict is also handed to the almanac when that store advertises a hook for it.
    No hook, no crash: the UI still updates and the taste signal is simply not persisted
    on this deployment.
    """
    surface_id = args.surface_id or DEFAULT_PLAYLIST_SURFACE

    persisted = False
    try:
        from ..container import get_container

        almanac = get_container().almanac()
        recorder = getattr(almanac, "record_feedback", None) or getattr(almanac, "record_rating", None)
        if callable(recorder):
            outcome = recorder(
                user_id=args.user_id,
                playlist_id=args.playlist_id,
                track_id=args.track_id,
                verdict=args.verdict,
            )
            if hasattr(outcome, "__await__"):
                await outcome
            persisted = True
    except Exception as exc:
        # Taste persistence is a nicety. Losing it must not lose the tap.
        logger.info("rateTrack: feedback not persisted (%s)", exc)

    messages = [
        _data_model_message(
            surface_id,
            {
                "playlistId": args.playlist_id,
                "trackId": args.track_id,
                "verdict": args.verdict,
                "persisted": persisted,
            },
            path=f"/tracks/{args.track_id}/feedback",
        )
    ]
    return messages


async def handle_reforge(args: ReforgeArgs) -> list[dict[str, Any]]:
    """User asked for another pass. Returns a brand-new playlist surface.

    This mirrors the ``forge_playlist`` tool exactly - same container, same builder -
    because the renderer asking for a re-forge and a model asking for a forge should
    produce byte-identical UI. That is the whole point of one catalog and one set of
    builders.
    """
    surfaces = _surfaces_module()
    try:
        from ..container import get_container
        from ..contracts import Coordinates, ForgeRequest
    except Exception as exc:
        raise AgentFunctionError(
            "forge_unavailable",
            "The playlist forge is not available on this deployment.",
            detail=str(exc),
        ) from exc

    coordinates = Coordinates(
        latitude=args.lat,
        longitude=args.lon,
        label=args.label,
    )
    request = ForgeRequest(
        coordinates=coordinates,
        theme_id=args.theme_id,
        genre_id=args.genre_id or "any",
        length=args.length,
        lastfm_user=args.lastfm_user,
        seed=args.seed,
    )
    try:
        result = await get_container().forge().forge(request)
    except Exception as exc:
        raise AgentFunctionError(
            "forge_failed",
            "BAROGROOVE could not re-forge that playlist.",
            detail=str(exc),
        ) from exc

    surface_id = args.surface_id or DEFAULT_PLAYLIST_SURFACE
    messages = surfaces.build_playlist_surface(result.playlist, surface_id=surface_id)
    return [dict(message) for message in messages]


# ======================================================================================
# The registry
# ======================================================================================


@dataclass(frozen=True, slots=True)
class AgentFunction:
    """One entry in the shared ``callAgentFunction`` registry."""

    name: str
    description: str
    model: type[BaseModel]
    handler: Callable[[Any], Awaitable[list[dict[str, Any]]]]
    aliases: tuple[str, ...] = field(default=())

    @property
    def argument_schema(self) -> dict[str, Any]:
        """JSON Schema for the payload, by alias - the camelCase the renderer sends."""
        return self.model.model_json_schema(mode="validation", by_alias=True)

    def validate(self, arguments: Mapping[str, Any] | None) -> BaseModel:
        """Coerce a raw payload into the typed model.

        Raises:
            AgentFunctionError: with code ``invalid_arguments`` on any validation
                failure, so callers never have to catch pydantic directly.
        """
        try:
            return self.model.model_validate(dict(arguments or {}))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}" for err in exc.errors()
            )
            raise AgentFunctionError(
                "invalid_arguments",
                f"Arguments for '{self.name}' failed validation.",
                detail=problems,
            ) from exc


_FUNCTIONS: Final[tuple[AgentFunction, ...]] = (
    AgentFunction(
        name="selectTheme",
        description="Renderer reports that the user chose a theme chip. Re-renders the themes surface.",
        model=SelectThemeArgs,
        handler=handle_select_theme,  # type: ignore[arg-type]
        aliases=("barogroove.selectTheme", "select_theme", "onThemeSelected"),
    ),
    AgentFunction(
        name="selectGenre",
        description="Renderer reports a genre-corridor change. Re-renders the themes surface.",
        model=SelectGenreArgs,
        handler=handle_select_genre,  # type: ignore[arg-type]
        aliases=("barogroove.selectGenre", "select_genre", "onGenreSelected"),
    ),
    AgentFunction(
        name="rateTrack",
        description="Renderer reports a love/skip verdict on a track. Patches the surface data model.",
        model=RateTrackArgs,
        handler=handle_rate_track,  # type: ignore[arg-type]
        aliases=("barogroove.rateTrack", "rate_track", "loveTrack", "skipTrack"),
    ),
    AgentFunction(
        name="reforge",
        description="Renderer asks for another pass at the playlist. Returns a fresh playlist surface.",
        model=ReforgeArgs,
        handler=handle_reforge,  # type: ignore[arg-type]
        aliases=("barogroove.reforge", "re_forge", "forgeAgain"),
    ),
)

#: Canonical name -> function. Aliases resolve through :func:`resolve`, not this dict,
#: so the manifest advertises exactly four functions rather than fourteen spellings.
REGISTRY: Final[dict[str, AgentFunction]] = {fn.name: fn for fn in _FUNCTIONS}

FUNCTION_NAMES: Final[tuple[str, ...]] = tuple(REGISTRY)

#: Alias index. The A2UI catalog is another worker's file and we cannot see which
#: spelling it declares; accepting the obvious variants costs one dict and removes an
#: entire class of integration failure.
_ALIAS_INDEX: Final[dict[str, AgentFunction]] = {}
for _fn in _FUNCTIONS:
    _ALIAS_INDEX[_fn.name.lower()] = _fn
    for _alias in _fn.aliases:
        _ALIAS_INDEX[_alias.lower()] = _fn


def resolve(name: str) -> AgentFunction:
    """Find a function by canonical name or declared alias, case-insensitively.

    Raises:
        AgentFunctionError: code ``unknown_function`` if nothing matches.
    """
    found = _ALIAS_INDEX.get((name or "").strip().lower())
    if found is None:
        raise AgentFunctionError(
            "unknown_function",
            f"'{name}' is not a function this agent exposes.",
            detail="Known functions: " + ", ".join(FUNCTION_NAMES),
        )
    return found


def argument_model(name: str) -> type[BaseModel]:
    """The pydantic model for a function's payload. Convenience for the REST endpoint."""
    return resolve(name).model


class DispatchResult(BaseModel):
    """What a dispatched agent function hands back to whichever transport called it."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    function: str
    surface_id: str | None = None
    call_id: str | None = None
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Follow-up agent-to-renderer A2UI envelopes, in order.",
    )
    response: dict[str, Any] = Field(
        default_factory=dict,
        description="The agentFunctionResponse envelope that closes the call.",
    )
    error: dict[str, Any] | None = None

    def stream(self) -> list[dict[str, Any]]:
        """Everything the renderer should consume, response last."""
        return [*self.messages, self.response]


async def dispatch(
    name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    call_id: str | None = None,
    surface_id: str | None = None,
) -> DispatchResult:
    """Validate, run, and package one ``callAgentFunction``.

    Never raises. Every failure - unknown function, bad payload, dead subsystem,
    unexpected exception in a handler - comes back as a ``DispatchResult`` with
    ``ok=False`` and an ``agentFunctionResponse`` carrying an error body. The renderer
    always gets a well-formed answer to its call, which is the entire contract.
    """
    try:
        function = resolve(name)
    except AgentFunctionError as exc:
        return DispatchResult(
            ok=False,
            function=name,
            surface_id=surface_id,
            call_id=call_id,
            error=exc.as_payload(),
            response=agent_function_response(
                name, surface_id=surface_id, call_id=call_id, error=exc.as_payload()
            ),
        )

    payload = dict(arguments or {})
    if surface_id and "surfaceId" not in payload and "surface_id" not in payload:
        payload["surfaceId"] = surface_id

    try:
        args = function.validate(payload)
    except AgentFunctionError as exc:
        return DispatchResult(
            ok=False,
            function=function.name,
            surface_id=surface_id,
            call_id=call_id,
            error=exc.as_payload(),
            response=agent_function_response(
                function.name, surface_id=surface_id, call_id=call_id, error=exc.as_payload()
            ),
        )

    effective_surface = getattr(args, "surface_id", None) or surface_id

    try:
        messages = await function.handler(args)
    except AgentFunctionError as exc:
        logger.warning("agent function %s degraded: %s", function.name, exc.message)
        return DispatchResult(
            ok=False,
            function=function.name,
            surface_id=effective_surface,
            call_id=call_id,
            error=exc.as_payload(),
            response=agent_function_response(
                function.name, surface_id=effective_surface, call_id=call_id, error=exc.as_payload()
            ),
        )
    except Exception as exc:  # noqa: BLE001 - the boundary; a traceback must not escape
        logger.exception("agent function %s raised", function.name)
        error = {
            "code": "handler_failed",
            "message": f"'{function.name}' could not be completed.",
            "detail": f"{type(exc).__name__}: {exc}",
        }
        return DispatchResult(
            ok=False,
            function=function.name,
            surface_id=effective_surface,
            call_id=call_id,
            error=error,
            response=agent_function_response(
                function.name, surface_id=effective_surface, call_id=call_id, error=error
            ),
        )

    clean = [dict(message) for message in messages if isinstance(message, Mapping)]
    resolved_surface = _surface_id_of(clean, effective_surface)
    return DispatchResult(
        ok=True,
        function=function.name,
        surface_id=resolved_surface,
        call_id=call_id,
        messages=clean,
        response=agent_function_response(
            function.name,
            surface_id=resolved_surface,
            call_id=call_id,
            result={"messageCount": len(clean), "surfaceId": resolved_surface},
        ),
    )
