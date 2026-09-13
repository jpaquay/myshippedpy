"""One door for "operate BAROGROOVE by conversation" (plan item 11).

The assistant overlay needs to invoke five capabilities by name, and they do
not live on one dispatch path:

===================================  ====================================
``select_theme`` ``select_genre``    ``callAgentFunction`` registry
``rate_track``   ``reforge``         (:mod:`backend.app.mcp.functions`)
``forge_playlist``                   MCP **tool**
                                     (:mod:`backend.app.mcp.manifest` /
                                     :mod:`backend.app.mcp.server`)
===================================  ====================================

An earlier worker found this the hard way: ``forge_playlist`` is not an A2UI
agent function and never was. Rather than teach the Flutter app about two
protocols, this module presents one verb -- :func:`perform` -- resolves the
name against whichever declaration owns it, and applies the *same* write gate
to both. The client sends a name and arguments; it does not need to know which
side of the house answered.

The gate is :func:`backend.app.mcp.confirm.require_confirmation`, and it runs
here **before** anything is executed, for every write, on every call. It is
also applied independently inside ``functions.dispatch`` and on the MCP tool
wrappers, so removing this module would not open a hole -- defence in depth is
the point, not an accident.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from .confirm import (
    ConfirmationInvalid,
    ConfirmationRequired,
    function_writes,
    require_confirmation,
)

logger = logging.getLogger("barogroove.mcp.gateway")

__all__ = ["GatewayResult", "capabilities", "perform"]


class GatewayResult:
    """What one conversational invocation produced."""

    __slots__ = ("status", "function", "writes", "receipt", "messages", "error", "confirmation")

    def __init__(
        self,
        *,
        status: str,
        function: str,
        writes: bool,
        receipt: str = "",
        messages: list[dict[str, Any]] | None = None,
        error: dict[str, Any] | None = None,
        confirmation: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.function = function
        self.writes = writes
        self.receipt = receipt
        self.messages = messages or []
        self.error = error
        self.confirmation = confirmation

    def as_payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "status": self.status,
            "function": self.function,
            "writes": self.writes,
        }
        if self.receipt:
            body["receipt"] = self.receipt
        if self.messages:
            body["messages"] = self.messages
        if self.confirmation is not None:
            body["confirmation"] = self.confirmation
            body["message"] = self.confirmation.pop("_message", "")
        if self.error is not None:
            body["error"] = self.error
        return body


def _agent_function(name: str) -> Any | None:
    try:
        from .functions import resolve

        return resolve(name)
    except Exception:
        return None


def _tool(name: str) -> Any | None:
    try:
        from .manifest import tool_spec

        return tool_spec(name)
    except Exception:
        return None


def capabilities() -> list[dict[str, Any]]:
    """Everything the assistant may invoke, with the ``writes`` flag on each.

    Served to the renderer by ``GET /api/advisor/tools``. This is the reason
    there is no list of write-function names in Dart: the classification is
    declared in Python next to the thing it classifies, and travels.
    """
    out: list[dict[str, Any]] = []

    try:
        from .manifest import tool_specs

        for spec in tool_specs():
            out.append(
                {
                    "name": spec.name,
                    "title": spec.title,
                    "description": spec.description.strip().splitlines()[0]
                    if spec.description.strip()
                    else "",
                    "kind": "tool",
                    "writes": spec.writes,
                    "arguments": spec.input_schema,
                }
            )
    except Exception:  # pragma: no cover - manifest is optional at runtime
        logger.debug("tool manifest unavailable for the capability list")

    try:
        from .functions import REGISTRY

        for fn in REGISTRY.values():
            out.append(
                {
                    "name": fn.name,
                    "title": fn.description,
                    "description": fn.description,
                    "kind": "agentFunction",
                    "writes": fn.writes,
                    "aliases": list(fn.aliases),
                    "arguments": fn.argument_schema,
                }
            )
    except Exception:  # pragma: no cover
        logger.debug("agent function registry unavailable for the capability list")

    return out


def _structured(result: Any) -> dict[str, Any]:
    """Pull the structured payload out of whatever the SDK wrapped it in."""
    if isinstance(result, dict):
        return result
    for attr in ("structuredContent", "structured_content"):
        value = getattr(result, attr, None)
        if isinstance(value, dict):
            return value
    return {}


def _tool_receipt(name: str, payload: Mapping[str, Any]) -> str:
    """One plain sentence for the collapsed confirmation card (spec 6.5)."""
    if payload.get("ok") is False:
        err = payload.get("error") or {}
        return str(err.get("message") or f"{name} failed.")

    if name == "forge_playlist":
        tracks = payload.get("track_count") or payload.get("trackCount")
        title = payload.get("title") or payload.get("playlist_title")
        if tracks and title:
            return f"Forged “{title}” — {tracks} tracks."
        if tracks:
            return f"Forged a playlist of {tracks} tracks."
        return "Forged a playlist."
    if name == "save_playlist":
        return "Saved."

    degraded = payload.get("degraded") or []
    if degraded:
        return f"{name} completed, degraded: {', '.join(str(d) for d in degraded)}."
    return f"{name} completed."


async def perform(
    name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    principal: str,
    confirmation_token: str | None = None,
    surface_id: str | None = None,
    call_id: str | None = None,
) -> GatewayResult:
    """Invoke [name]. Never raises; every outcome is a :class:`GatewayResult`.

    Three outcomes matter:

    ``done``
        It ran. ``receipt`` is one sentence for the collapsed card.
    ``confirmation_required``
        It is a write and no valid ticket came with the call. **Nothing ran.**
        ``confirmation`` carries a fresh single-use ticket plus the arguments
        the server would have used, so the renderer can show them, let the user
        edit them, and call again.
    ``error``
        Anything else, in plain language.
    """
    args = dict(arguments or {})
    writes = function_writes(name)

    fn = _agent_function(name)
    spec = None if fn is not None else _tool(name)

    if fn is None and spec is None:
        return GatewayResult(
            status="error",
            function=name,
            writes=writes,
            error={
                "code": "unknown_function",
                "message": f"BAROGROOVE has no capability called '{name}'.",
            },
        )

    # ------------------------------------------------------------------
    # Agent functions: the gate lives inside the shared dispatcher, so the
    # token is forwarded rather than spent here. Exactly one redemption per
    # call, and the refusal is identical whichever transport reached it.
    # ------------------------------------------------------------------
    if fn is not None:
        from .functions import dispatch

        result = await dispatch(
            name,
            args,
            call_id=call_id,
            surface_id=surface_id,
            confirmation_token=confirmation_token,
            principal=principal,
        )
        if result.ok:
            return GatewayResult(
                status="done",
                function=fn.name,
                writes=fn.writes,
                receipt=_agent_receipt(fn.name, args),
                messages=result.messages,
            )

        err = dict(result.error or {})
        if err.get("code") == "confirmation_required":
            payload = dict(err.get("confirmation") or {})
            payload["_message"] = str(err.get("message") or "")
            payload["argument_schema"] = fn.argument_schema
            return GatewayResult(
                status="confirmation_required",
                function=fn.name,
                writes=True,
                confirmation=payload,
            )
        return GatewayResult(
            status="error",
            function=fn.name,
            writes=fn.writes,
            error=err,
        )

    # ------------------------------------------------------------------
    # MCP tools: `forge_playlist` and `save_playlist` are not agent
    # functions, so this path carries the gate itself. Before argument
    # coercion, before the container is touched, before any I/O.
    # ------------------------------------------------------------------
    assert spec is not None  # narrowed above
    try:
        require_confirmation(
            spec.name,
            arguments=args,
            token=confirmation_token,
            principal=principal,
            title=spec.title,
        )
    except ConfirmationRequired as need:
        payload = need.ticket.as_payload(title=spec.title)
        payload["_message"] = need.message
        payload["argument_schema"] = spec.input_schema
        return GatewayResult(
            status="confirmation_required",
            function=spec.name,
            writes=True,
            confirmation=payload,
        )
    except ConfirmationInvalid as bad:
        return GatewayResult(
            status="error",
            function=spec.name,
            writes=True,
            error={"code": bad.code, "message": bad.message},
        )

    return await _run_tool(spec, args)


def _agent_receipt(name: str, args: Mapping[str, Any]) -> str:
    if name == "rateTrack":
        verdict = str(args.get("verdict") or "rated")
        return f"Recorded: {verdict}."
    if name == "reforge":
        return "Reforged the set."
    if name == "selectTheme":
        return f"Theme set to {args.get('themeId')}."
    if name == "selectGenre":
        return f"Genre corridor set to {args.get('genreId')}."
    return f"{name} done."


async def _run_tool(spec: Any, args: dict[str, Any]) -> GatewayResult:
    try:
        model = spec.input_model.model_validate(args)
    except Exception as exc:
        return GatewayResult(
            status="error",
            function=spec.name,
            writes=spec.writes,
            error={
                "code": "invalid_arguments",
                "message": f"Those arguments do not fit '{spec.name}'.",
                "detail": str(exc)[:400],
            },
        )

    try:
        from . import server as _server

        runner = getattr(_server, f"_run_{spec.name}")
    except Exception as exc:
        return GatewayResult(
            status="error",
            function=spec.name,
            writes=spec.writes,
            error={
                "code": "tool_unavailable",
                "message": f"'{spec.name}' is not available in this deployment.",
                "detail": type(exc).__name__,
            },
        )

    try:
        raw = await runner(model)
    except Exception as exc:  # noqa: BLE001 - the boundary
        logger.exception("gateway tool %s raised", spec.name)
        return GatewayResult(
            status="error",
            function=spec.name,
            writes=spec.writes,
            error={
                "code": "tool_failed",
                "message": f"'{spec.name}' could not be completed.",
                "detail": type(exc).__name__,
            },
        )

    payload = _structured(raw)
    if payload.get("ok") is False:
        err = payload.get("error") or {}
        return GatewayResult(
            status="error",
            function=spec.name,
            writes=spec.writes,
            error={
                "code": str(err.get("code") or "tool_failed"),
                "message": str(err.get("message") or f"'{spec.name}' failed."),
            },
        )

    return GatewayResult(
        status="done",
        function=spec.name,
        writes=spec.writes,
        receipt=_tool_receipt(spec.name, payload),
        messages=list(payload.get("a2ui") or []),
    )
