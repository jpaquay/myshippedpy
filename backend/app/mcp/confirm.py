"""The write gate: read and select freely, confirm before anything that writes.

WHY THIS IS A SERVER-SIDE MODULE AND NOT A UI RULE
==================================================

The product policy (plan item 11, ``docs/UX_IA_SPEC.md`` 6.5) is short:

===================================  ============================================
``select_theme`` / ``select_genre``  act immediately, no confirmation
``forge_playlist`` / ``reforge`` /   a confirmation step, every time
``rate_track``
===================================  ============================================

A confirmation card drawn by the Flutter app is a *courtesy*, not a control.
It protects a user who is paying attention from a mistake; it protects nobody
from a buggy renderer, a stale build, a second client, a hand-rolled ``curl``
or an agent runtime speaking MCP directly. So the refusal lives here, on the
server, on the path every transport shares, and the UI's job is only to make
the refusal pleasant instead of surprising.

HOW IT WORKS
============

Two round trips, always, for a write:

1. The caller invokes the function with no ticket. The gate refuses, mints a
   single-use :class:`ConfirmationTicket` bound to *this* function and *this*
   principal, and hands it back with the arguments it would have used. Nothing
   ran.
2. The caller invokes again with the ticket. The gate redeems it -- once -- and
   the call proceeds. The arguments may have changed in between, because 6.5
   requires them to be editable on the card; the ticket authorises *the act*,
   not a frozen payload.

WHAT A CLIENT THAT SKIPS THE UI GETS
====================================

``confirmation_required``, and no write. There is no argument, header or flag
that turns the gate off, and the ticket cannot be constructed client-side: it
is a :func:`secrets.token_urlsafe` value that only exists in this process's
store. Replaying a spent ticket fails (single use). Using one minted for a
different function fails (bound). Using someone else's fails (bound to the
principal resolved by :mod:`backend.app.mcp.guard`, not to anything the caller
sends). Sitting on one fails after :data:`TICKET_TTL_SECONDS`.

WHAT IT DOES NOT CLAIM
======================

It does not prove a *human* consented -- no server can, from a byte stream. A
client that deliberately calls twice in a row gets its write. What the gate
guarantees is that no single call can both propose and perform a write, which
is precisely the failure mode that matters in practice: a model or a renderer
executing a destructive tool as a side effect of a conversational turn.

Relationship to :mod:`backend.app.mcp.guard`: the guard answers *who is
calling* and binds the principal; this module answers *may this particular
call write*. It reads the principal the guard bound rather than trusting a
caller-supplied identity, so the two enforce through each other rather than
around each other.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "ConfirmationTicket",
    "ConfirmationRequired",
    "ConfirmationInvalid",
    "TICKET_TTL_SECONDS",
    "acting_principal",
    "function_writes",
    "issue",
    "redeem",
    "require_confirmation",
    "reset_tickets",
    "outstanding",
]

#: How long a confirmation stays spendable. Long enough to read the card and
#: edit an argument, short enough that an abandoned proposal cannot be
#: resurrected an hour later by something that found the token in a log.
TICKET_TTL_SECONDS: Final[float] = 300.0

#: Hard cap on outstanding tickets, so a caller cannot mint its way through
#: memory by proposing writes it never confirms.
_MAX_OUTSTANDING: Final[int] = 256


@dataclass(frozen=True, slots=True)
class ConfirmationTicket:
    """A single-use permission to perform one write, for one principal."""

    token: str
    function: str
    principal: str
    issued_at: float
    expires_at: float

    #: What the server *would* have run. Echoed to the client so the card can
    #: show every argument. Not authoritative on redemption: 6.5 lets the user
    #: edit them before confirming.
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def expired(self, *, now: float | None = None) -> bool:
        return (now if now is not None else time.monotonic()) >= self.expires_at

    def as_payload(self, *, title: str = "", detail: str = "") -> dict[str, Any]:
        """The wire shape the renderer turns into an inline action card."""
        return {
            "token": self.token,
            "function": self.function,
            "title": title or self.function,
            "detail": detail,
            "arguments": dict(self.arguments),
            "expires_in_seconds": max(0.0, round(self.expires_at - time.monotonic(), 1)),
        }


class ConfirmationRequired(Exception):
    """Raised instead of writing. Carries the ticket that would let it through."""

    code: Final[str] = "confirmation_required"

    def __init__(
        self,
        ticket: ConfirmationTicket,
        *,
        title: str = "",
        detail: str = "",
        message: str | None = None,
    ) -> None:
        self.ticket = ticket
        self.title = title
        self.detail = detail
        self.message = message or (
            f"'{ticket.function}' changes your library, so it needs to be "
            f"confirmed before it runs. Nothing has happened yet."
        )
        super().__init__(self.message)

    def as_payload(self) -> dict[str, Any]:
        return {
            "status": self.code,
            "function": self.ticket.function,
            "writes": True,
            "message": self.message,
            "confirmation": self.ticket.as_payload(title=self.title, detail=self.detail),
        }


class ConfirmationInvalid(Exception):
    """The ticket was absent, spent, expired, or minted for something else."""

    code: Final[str] = "confirmation_invalid"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
#
# Process-local on purpose. A ticket is valid for seconds, is single-use, and
# is only ever redeemed by the same client that was just refused -- the
# properties that would make a shared store worth its cost (durability, fan-out
# across replicas) are properties a confirmation should NOT have. Behind
# several replicas a user who is load-balanced elsewhere mid-confirmation is
# told the confirmation expired and asked again, which is the correct failure
# direction: it errs toward asking twice, never toward writing unasked.
_TICKETS: dict[str, ConfirmationTicket] = {}


def reset_tickets() -> None:
    """Drop every outstanding ticket. Tests, and process shutdown."""
    _TICKETS.clear()


def outstanding() -> int:
    """How many unspent tickets exist. Diagnostics only."""
    return len(_TICKETS)


def _evict_expired(*, now: float) -> None:
    for token in [t for t, tk in _TICKETS.items() if tk.expires_at <= now]:
        _TICKETS.pop(token, None)


def issue(
    function: str,
    *,
    principal: str,
    arguments: Mapping[str, Any] | None = None,
) -> ConfirmationTicket:
    """Mint a single-use ticket for one write by one principal."""
    now = time.monotonic()
    _evict_expired(now=now)

    if len(_TICKETS) >= _MAX_OUTSTANDING:
        # Oldest first. An abandoned proposal is worth less than a live one.
        for token in sorted(_TICKETS, key=lambda t: _TICKETS[t].issued_at)[:32]:
            _TICKETS.pop(token, None)

    ticket = ConfirmationTicket(
        token=secrets.token_urlsafe(24),
        function=function,
        principal=principal,
        issued_at=now,
        expires_at=now + TICKET_TTL_SECONDS,
        arguments=dict(arguments or {}),
    )
    _TICKETS[ticket.token] = ticket
    return ticket


def redeem(token: str, *, function: str, principal: str) -> ConfirmationTicket:
    """Spend a ticket, or explain why it cannot be spent.

    Raises:
        ConfirmationInvalid: unknown, expired, already spent, minted for a
            different function, or minted for a different principal. The
            message is written for a user, not for a log.
    """
    now = time.monotonic()
    _evict_expired(now=now)

    ticket = _TICKETS.pop(token, None)  # single use: gone either way
    if ticket is None:
        raise ConfirmationInvalid(
            "That confirmation is no longer valid. Nothing was changed — ask again."
        )
    if ticket.expired(now=now):
        raise ConfirmationInvalid(
            "That confirmation expired. Nothing was changed — ask again."
        )
    if ticket.function != function:
        raise ConfirmationInvalid(
            f"That confirmation was for '{ticket.function}', not '{function}'. "
            f"Nothing was changed."
        )
    if ticket.principal != principal:
        raise ConfirmationInvalid(
            "That confirmation belongs to a different session. Nothing was changed."
        )
    return ticket


# --------------------------------------------------------------------------- #
# Who is calling, and what writes
# --------------------------------------------------------------------------- #


def acting_principal(fallback: str = "anonymous") -> str:
    """The identity the MCP guard bound for this call, or [fallback].

    Deliberately NOT read from the request body. Binding a ticket to something
    the caller supplies would let a caller redeem anyone's ticket by claiming
    to be them, which is the one thing the guard exists to prevent.
    """
    try:
        from .principal import current_principal

        who = current_principal()
    except Exception:
        return fallback
    if who is None:
        return fallback
    uid = getattr(who, "uid", None)
    return str(uid) if uid else fallback


def function_writes(name: str) -> bool:
    """Does invoking ``name`` write?

    Resolved from the DECLARATIONS, in this order, never from a list kept here:

    1. :data:`backend.app.mcp.manifest.TOOL_SPECS` -- ``ToolSpec.writes``,
       which is the inverse of the ``readOnlyHint`` already published to every
       MCP client. ``forge_playlist`` and ``save_playlist`` land here.
    2. The ``callAgentFunction`` registry in :mod:`backend.app.mcp.functions`
       -- ``AgentFunction.writes``. ``rateTrack`` and ``reforge`` land here.
    3. The A2UI catalog's ``WRITE_FUNCTION_IDS``, for the action-id vocabulary
       (``barogroove.trackFeedback`` and friends).

    Anything unrecognised is reported as a write. A capability nobody has
    classified is not a capability we should run unasked.
    """
    try:
        from .manifest import tool_spec

        return tool_spec(name).writes
    except Exception:
        pass

    try:
        from .functions import resolve

        return resolve(name).writes
    except Exception:
        pass

    try:
        from ..a2ui.catalog import function_writes as catalog_writes

        return catalog_writes(name)
    except Exception:
        pass

    return True


def require_confirmation(
    function: str,
    *,
    arguments: Mapping[str, Any] | None = None,
    token: str | None = None,
    principal: str | None = None,
    title: str = "",
    detail: str = "",
) -> ConfirmationTicket | None:
    """The gate. Call this immediately before doing anything.

    Returns ``None`` for a read/select -- nothing to confirm, carry on. For a
    write it either returns the redeemed ticket (proceed) or raises.

    Raises:
        ConfirmationRequired: no ticket was supplied. A fresh one is attached.
        ConfirmationInvalid: a ticket was supplied and is not spendable.
    """
    if not function_writes(function):
        return None

    who = principal if principal is not None else acting_principal()

    if not token:
        raise ConfirmationRequired(
            issue(function, principal=who, arguments=arguments),
            title=title,
            detail=detail,
        )

    return redeem(token, function=function, principal=who)
