"""Who is calling the MCP tools.

THE PROBLEM THIS SOLVES
=======================

MCP tools are invoked by an *agent*, not by a browser. There is no cookie, no
session, no form post -- just a JSON-RPC frame carrying whatever arguments the
caller decided to send. If a tool reads the acting user out of its own
arguments, then the caller chooses who they are, and any authentication in
front of the endpoint is decorative.

That matters here because ``save_playlist`` writes to a real person's Spotify
account using a refresh token *we* hold. A tool that accepts ``user_id`` as a
parameter is a textbook confused deputy: the backend has the authority, the
caller supplies the target, and nobody checks that the caller is entitled to
name that target.

So: the acting principal is derived from the verified bearer token on the HTTP
request, carried in a context variable, and read by the tools. It is never a
tool argument. The corresponding fields have been deleted from the input
schemas -- and because those models are ``extra="forbid"``, a caller that still
sends ``user_id`` now gets a loud validation error instead of a silent
substitution.

FAIL CLOSED
===========

:func:`require_principal` raises when nothing is bound. This is deliberate and
load-bearing. ``ContextVar`` propagation is reliable for tasks spawned from the
bound context, but the MCP SDK owns its own task structure and may change it
across versions. If propagation ever breaks, we want every user-scoped tool to
start refusing -- noisily, in a way that shows up immediately -- rather than to
quietly fall back to "no user" and act with ambient authority.

An outage is a bug report. A silent authority downgrade is an incident.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.app.firebase.auth import AuthUser

__all__ = [
    "PrincipalError",
    "bind_principal",
    "current_principal",
    "principal_scope",
    "require_principal",
]


# Default ``None`` -- absence is the safe state, and every read path treats it
# as "refuse" rather than "anonymous".
_PRINCIPAL: ContextVar["AuthUser | None"] = ContextVar("bg_mcp_principal", default=None)


class PrincipalError(RuntimeError):
    """No authenticated principal is bound to this call.

    Raised by :func:`require_principal`. The MCP layer turns this into a
    JSON-RPC error rather than a 500: it is a refusal, not a crash.
    """


def bind_principal(user: "AuthUser") -> Token:
    """Bind ``user`` as the acting principal. Returns a token for reset."""
    return _PRINCIPAL.set(user)


def current_principal() -> "AuthUser | None":
    """The acting principal, or ``None``.

    For code that legitimately tolerates anonymity -- ``list_themes`` needs no
    identity. Anything touching user data wants :func:`require_principal`.
    """
    return _PRINCIPAL.get()


def require_principal() -> "AuthUser":
    """The acting principal, or raise.

    Every tool that reads user history, spends a user's third-party quota, or
    writes to a user's account must call this and use the ``uid`` it returns.
    """
    user = _PRINCIPAL.get()
    if user is None:
        raise PrincipalError(
            "This tool acts on a specific listener's data and no authenticated "
            "principal is bound to the call. Present a Firebase ID token as "
            "'Authorization: Bearer <token>' on the MCP request."
        )
    return user


@contextlib.contextmanager
def principal_scope(user: "AuthUser | None") -> Iterator[None]:
    """Bind ``user`` for the duration of the block, then restore.

    Restores the previous value rather than clearing, so nesting is safe and a
    raising body cannot leak a principal into whatever runs next on this task.
    """
    token = _PRINCIPAL.set(user)
    try:
        yield
    finally:
        _PRINCIPAL.reset(token)
