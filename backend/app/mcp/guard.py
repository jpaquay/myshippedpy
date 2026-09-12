"""Authentication in front of the MCP transport.

WHY AN ASGI WRAPPER AND NOT A FASTAPI DEPENDENCY
================================================

``/mcp`` is not a FastAPI route. It is a mounted ASGI application owned by the
MCP SDK, which manages its own sessions and streaming. FastAPI's ``Depends``
never runs for traffic inside that mount, so the usual ``current_user``
dependency simply would not fire. The guard therefore has to sit at the ASGI
layer, where every byte addressed to ``/mcp`` must pass.

WHAT IT DOES
============

1. Pulls the bearer token off the request.
2. Verifies it with the same verifier the REST API uses -- one code path, so a
   token that is good here is good there, and a revocation applies to both.
3. Binds the resulting :class:`AuthUser` as the acting principal for the
   duration of the call, via :mod:`backend.app.mcp.principal`.
4. Refuses with a JSON-RPC-shaped 401 when the token is missing or bad.

The tools then read the principal from the context instead of from their own
arguments. That is the whole point: the caller no longer gets a vote in who
they are.

THE ANONYMOUS TIER
==================

``mcp_require_auth`` defaults to ``True``: no token, no ``/mcp``, including the
``initialize`` and ``tools/list`` handshake. A private server that will not
describe itself to strangers is the correct posture for something holding
other people's OAuth tokens.

It can be turned off *only* in the local environment, gated the same way as the
insecure dev tokens. Even then the guard binds no principal, so every
user-scoped tool keeps refusing through
:func:`~backend.app.mcp.principal.require_principal`. Disabling auth locally
buys you ``list_themes`` and ``get_sky_vector`` for a demo. It does not buy you
somebody's Spotify account.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.app.firebase.auth import (
    AuthError,
    dev_tokens_enabled,
    extract_bearer_token,
    verify_bearer_token,
)
from backend.app.mcp.principal import principal_scope

logger = logging.getLogger(__name__)

__all__ = ["MCPAuthGuard", "anonymous_mcp_allowed"]

# JSON-RPC reserved the -32000..-32099 block for implementation-defined server
# errors. Agent clients surface `message`, so it has to explain the fix.
_JSONRPC_UNAUTHENTICATED = -32001


def anonymous_mcp_allowed(settings: Any) -> bool:
    """True when ``/mcp`` may be reached without a token.

    Deliberately conjunctive, and deliberately reusing
    :func:`dev_tokens_enabled` so that "this deployment tolerates unauthenticated
    access" can never become true in a non-local environment by flipping one
    variable. Someone would have to change both, in code, on purpose.
    """
    requires_auth = bool(getattr(settings, "mcp_require_auth", True))
    if requires_auth:
        return False
    # The flag is off. Only honour it where insecure dev tokens are also legal.
    return dev_tokens_enabled(settings)


async def _refuse(send: Any, *, status: int, message: str) -> None:
    """Emit a JSON-RPC error envelope with an HTTP status to match.

    Both halves matter: agent runtimes branch on the HTTP status, while the
    model behind them reads ``error.message``. A bare 401 with an empty body
    tends to surface to a user as "the tool broke".
    """
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": _JSONRPC_UNAUTHENTICATED, "message": message},
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                # Tells a conforming client which scheme to retry with.
                (b"www-authenticate", b'Bearer realm="barogroove-mcp"'),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _authorization_header(scope: dict[str, Any]) -> str | None:
    """Case-insensitive lookup. ASGI header names are raw lowercase bytes."""
    for raw_name, raw_value in scope.get("headers") or []:
        if raw_name.lower() == b"authorization":
            try:
                return raw_value.decode("latin-1")
            except Exception:  # noqa: BLE001 - a header we cannot decode is a header we reject
                return None
    return None


class MCPAuthGuard:
    """ASGI middleware binding a verified principal around the MCP transport."""

    def __init__(self, inner: Any, settings_provider: Any) -> None:
        self._inner = inner
        self._settings_provider = settings_provider

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        # Lifespan and websocket frames carry no credentials and start no tool
        # call. Pass them through untouched rather than inventing a policy.
        if scope.get("type") != "http":
            await self._inner(scope, receive, send)
            return

        settings = self._settings_provider()
        token = extract_bearer_token(_authorization_header(scope))

        if token is None:
            if anonymous_mcp_allowed(settings):
                # No principal bound. User-scoped tools will refuse themselves.
                logger.debug("unauthenticated /mcp call permitted (local, auth disabled)")
                with principal_scope(None):
                    await self._inner(scope, receive, send)
                return
            await _refuse(
                send,
                status=401,
                message=(
                    "BAROGROOVE's MCP endpoint requires authentication. Send a Firebase "
                    "ID token as 'Authorization: Bearer <token>'."
                ),
            )
            return

        try:
            user = await verify_bearer_token(token, settings)
        except AuthError as err:
            # Log the reason, return a generic message. A verifier that explains
            # precisely why a token failed is an oracle for forging a better one.
            logger.warning("rejected /mcp bearer token: %s", err)
            await _refuse(
                send,
                status=401,
                message="The bearer token presented to BAROGROOVE's MCP endpoint is not valid.",
            )
            return
        except Exception:  # noqa: BLE001
            logger.exception("unexpected failure verifying an /mcp bearer token")
            await _refuse(
                send,
                status=503,
                message="BAROGROOVE could not verify credentials right now.",
            )
            return

        with principal_scope(user):
            await self._inner(scope, receive, send)
