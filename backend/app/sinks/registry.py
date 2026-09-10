"""Sink selection and the fallthrough policy.

The policy in one sentence: **the user always leaves with a playlist.**

``kind="auto"`` tries Spotify, and on any non-ok result falls through to M3U
while folding the Spotify failure into the returned message — so the user reads
"the app's 5-user Developer Mode allowance is full, here's your file" rather
than silently receiving a file and wondering what happened. The reason is the
product; hiding it would be the bug.
"""

from __future__ import annotations

from typing import Final, Sequence

from ..contracts import Playlist, PlaylistSink, SinkKind, SinkResult
from ..errors import SinkError
from .m3u import M3USink

__all__ = ["NoopSink", "choose_sink", "write_playlist", "default_sinks", "FALLTHROUGH_ORDER"]

#: Preference order under ``kind="auto"``. M3U is last and unconditional; it is
#: the floor, not a peer.
FALLTHROUGH_ORDER: Final[tuple[SinkKind, ...]] = ("spotify", "m3u")


class NoopSink:
    """``kind="none"`` — the caller wants a playlist object and nothing written.

    Used by preview endpoints and by tests. Reports ok=True because doing
    nothing successfully is not a failure.
    """

    kind: SinkKind = "none"

    async def available(self, user_id: str | None) -> bool:  # noqa: ARG002
        return True

    async def write(
        self, playlist: Playlist, *, user_id: str | None = None
    ) -> SinkResult:
        requested = len(playlist.tracks)
        return SinkResult(
            kind=self.kind,
            ok=True,
            matched=0,
            requested=requested,
            message="No sink requested; playlist generated but not written anywhere.",
        )


def default_sinks() -> list[PlaylistSink]:
    """The M3U-only set. Callers that can construct a ``SpotifySink`` (i.e. that
    have a token vault to hand) prepend it themselves — this module deliberately
    does not import ``spotify`` at module scope, so a misconfigured Spotify
    integration can never stop the fallback from loading."""
    return [M3USink(), NoopSink()]


def _by_kind(sinks: Sequence[PlaylistSink], kind: SinkKind) -> PlaylistSink | None:
    for sink in sinks:
        if getattr(sink, "kind", None) == kind:
            return sink
    return None


def _m3u_of(sinks: Sequence[PlaylistSink]) -> PlaylistSink:
    """The M3U sink, synthesised if the caller forgot to include one.

    Synthesising is correct rather than lazy: ``M3USink`` is pure and stateless,
    and a registry that cannot produce a fallback has no reason to exist.
    """
    return _by_kind(sinks, "m3u") or M3USink()


async def choose_sink(
    sinks: Sequence[PlaylistSink], kind: SinkKind, user_id: str | None
) -> PlaylistSink:
    """Pick the sink to *try first*.

    ``auto`` resolves to the first available sink in ``FALLTHROUGH_ORDER``.
    An explicit kind is honoured even when unavailable — the caller asked for it
    by name, and ``write_playlist`` will surface the resulting failure rather
    than quietly doing something else.
    """
    if kind == "none":
        return _by_kind(sinks, "none") or NoopSink()

    if kind != "auto":
        chosen = _by_kind(sinks, kind)
        if chosen is None:
            if kind == "m3u":
                return M3USink()
            raise SinkError(f"No sink registered for kind {kind!r}.")
        return chosen

    for candidate_kind in FALLTHROUGH_ORDER:
        sink = _by_kind(sinks, candidate_kind)
        if sink is None:
            continue
        try:
            if await sink.available(user_id):
                return sink
        except Exception:
            # An availability probe that throws is, definitionally, unavailable.
            continue

    return _m3u_of(sinks)


async def write_playlist(
    sinks: Sequence[PlaylistSink],
    playlist: Playlist,
    *,
    kind: SinkKind = "auto",
    user_id: str | None = None,
) -> SinkResult:
    """Write ``playlist``, falling through to M3U when the preferred sink fails."""
    if kind == "none":
        return await (_by_kind(sinks, "none") or NoopSink()).write(playlist, user_id=user_id)

    if kind == "m3u":
        return await _m3u_of(sinks).write(playlist, user_id=user_id)

    if kind == "spotify":
        # Explicit request: try it, and still fall through — the user wanted a
        # Spotify playlist, but they wanted *a playlist* more.
        return await _try_then_fallback(sinks, playlist, "spotify", user_id)

    # auto
    for candidate_kind in FALLTHROUGH_ORDER:
        if candidate_kind == "m3u":
            break
        sink = _by_kind(sinks, candidate_kind)
        if sink is None:
            continue
        try:
            if not await sink.available(user_id):
                continue
        except Exception:
            continue
        return await _try_then_fallback(sinks, playlist, candidate_kind, user_id)

    return await _m3u_of(sinks).write(playlist, user_id=user_id)


async def _try_then_fallback(
    sinks: Sequence[PlaylistSink],
    playlist: Playlist,
    kind: SinkKind,
    user_id: str | None,
) -> SinkResult:
    sink = _by_kind(sinks, kind)
    reason: str

    if sink is None:
        reason = f"The {kind} sink is not enabled on this deployment."
    else:
        try:
            result = await sink.write(playlist, user_id=user_id)
        except Exception as exc:
            # A sink that raises has broken its contract (implementations MUST
            # degrade). We absorb it rather than propagate — the user's playlist
            # is not the right casualty of someone else's bug.
            reason = (
                f"The {kind} sink raised {type(exc).__name__} instead of degrading "
                "cleanly; that is a bug on our side."
            )
        else:
            if result.ok:
                return result
            reason = result.message or f"The {kind} sink reported failure without a reason."

    fallback = await _m3u_of(sinks).write(playlist, user_id=user_id)
    return _fold_reason(fallback, reason)


def _fold_reason(result: SinkResult, reason: str) -> SinkResult:
    """Prefix the fallback's message with why the user got a file.

    The reason goes *first*: it is the surprising part, and the M3U message is
    reassurance that follows it.
    """
    reason = reason.strip()
    if not reason:
        return result
    combined = f"{reason.rstrip('.')}. {result.message}".strip()
    return result.model_copy(update={"message": combined})
