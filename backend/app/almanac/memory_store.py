"""In-process Almanac. The default store in local dev and in every test.

``container.py`` prefers the Firestore implementation and falls back to this
one whenever Firestore is unconfigured — which is most of the time during
development and all of the time under test. That makes this the reference
implementation of :class:`~..contracts.AlmanacStore`, not a stub. If the
behaviour here and the behaviour in Firestore diverge, the tests pass and the
product is broken, so this file does the real work: real ordering, real
snapshotting of feedback context, and a real ridge fit in ``nudge``.

Constructible with no arguments, by contract.
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Literal

from ..contracts import Playlist
from .learning import DEFAULT_LAMBDA, MIN_SAMPLES, fit_nudge
from .models import FeedbackEvent, ForgeRecord, NudgeDocument

#: Bucket for forges with no signed-in user. They still get recorded — the
#: history is useful for demos and for the "you, before you had an account"
#: migration — but they are kept apart from any real user's taste.
ANONYMOUS_USER: str = "anonymous"

#: Soft cap on retained forges per user. The Almanac is meant to compound, but
#: an in-process store is not a database; past this we drop the oldest. Chosen
#: to be far larger than any realistic dev session.
MAX_FORGES_PER_USER: int = 500

#: Soft cap on retained feedback events per user, same reasoning. Ridge with a
#: 90-day half-life gets nothing from the two-thousand-and-first skip.
MAX_EVENTS_PER_USER: int = 2000


def _owner(user_id: str | None) -> str:
    return user_id or ANONYMOUS_USER


class MemoryAlmanac:
    """Async, in-process implementation of the ``AlmanacStore`` protocol."""

    def __init__(self) -> None:
        # Playlists are kept whole (the protocol hands them back) *and*
        # flattened (the learner and retrospective read records). Storing both
        # costs memory we have and saves a lossy round-trip we do not want.
        self._playlists: dict[str, Playlist] = {}
        self._records: dict[str, ForgeRecord] = {}
        self._by_user: dict[str, list[str]] = {}
        self._events: dict[str, list[FeedbackEvent]] = {}

        # Fitting is cheap but not free, and `nudge` is on the forge hot path.
        # Cache keyed by the event count that produced it: any new feedback
        # changes the count and invalidates naturally.
        self._nudge_cache: dict[str, tuple[int, NudgeDocument | None]] = {}

        self._lock_obj: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    # -- concurrency -------------------------------------------------------

    def _lock(self) -> asyncio.Lock:
        """Return a lock bound to the running loop, recreating it if the loop
        changed.

        A single store instance can outlive an event loop — pytest-asyncio
        builds a fresh loop per test, and the container caches singletons. A
        lock bound to a dead loop raises on await, which is a confusing failure
        for something this peripheral. Rebinding is safe here because a loop
        swap implies nothing was mid-await.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._lock_obj is None or self._lock_loop is not loop:
            self._lock_obj = asyncio.Lock()
            self._lock_loop = loop
        return self._lock_obj

    # -- AlmanacStore ------------------------------------------------------

    async def record_forge(self, playlist: Playlist) -> str:
        """Persist a forged playlist. Returns its id."""
        record = ForgeRecord.from_playlist(playlist)
        owner = _owner(playlist.user_id)
        async with self._lock():
            previous = self._playlists.get(playlist.id)
            self._playlists[playlist.id] = playlist
            self._records[playlist.id] = record

            # An id can change hands — an anonymous forge claimed after
            # sign-in, or, in a test, two fixtures that happen to agree on a
            # name. Detach it from the old owner before attaching it to the
            # new one, or the forge vanishes from both histories.
            if previous is not None:
                prior_owner = _owner(previous.user_id)
                if prior_owner != owner:
                    prior_ids = self._by_user.get(prior_owner)
                    if prior_ids and playlist.id in prior_ids:
                        prior_ids.remove(playlist.id)
                    self._nudge_cache.pop(prior_owner, None)

            ids = self._by_user.setdefault(owner, [])
            if playlist.id not in ids:
                ids.append(playlist.id)
                if len(ids) > MAX_FORGES_PER_USER:
                    for stale in ids[:-MAX_FORGES_PER_USER]:
                        self._playlists.pop(stale, None)
                        self._records.pop(stale, None)
                    del ids[:-MAX_FORGES_PER_USER]
            self._nudge_cache.pop(owner, None)
        return playlist.id

    async def record_feedback(
        self,
        *,
        user_id: str,
        playlist_id: str,
        track_key: str,
        signal: Literal["loved", "skipped"],
    ) -> None:
        """Record a love or a skip, snapshotting the sky it happened under.

        The snapshot is the point. Storing the bare (user, playlist, track,
        signal) tuple and re-joining at training time means training against
        whatever the forge record has become, not against what the user was
        actually reacting to. Unknown playlist ids are still recorded — with an
        empty context — so the raw signal survives even if it cannot train.
        """
        owner = _owner(user_id)
        async with self._lock():
            record = self._records.get(playlist_id)
            if record is not None:
                event = FeedbackEvent.from_forge(
                    record, user_id=owner, track_key=track_key, signal=signal
                )
            else:
                event = FeedbackEvent(
                    user_id=owner,
                    playlist_id=playlist_id,
                    track_key=track_key,
                    signal=signal,
                )
            bucket = self._events.setdefault(owner, [])
            bucket.append(event)
            if len(bucket) > MAX_EVENTS_PER_USER:
                del bucket[:-MAX_EVENTS_PER_USER]
            self._nudge_cache.pop(owner, None)

    async def history(self, user_id: str, limit: int = 50) -> list[Playlist]:
        """Most recent forges first.

        Ties on ``created_at`` — common in tests and in demo seeds — break on
        insertion order reversed, so "newest first" stays stable and total.
        """
        owner = _owner(user_id)
        async with self._lock():
            ids = list(self._by_user.get(owner, ()))
            playlists = [self._playlists[i] for i in ids if i in self._playlists]
        if limit is not None and limit < 0:
            limit = 0
        ordered = sorted(
            enumerate(playlists),
            key=lambda pair: (pair[1].created_at, pair[0]),
            reverse=True,
        )
        out = [p for _, p in ordered]
        return out[:limit] if limit is not None else out

    async def nudge(self, user_id: str) -> list[list[float]] | None:
        """The user's 9x7 delta, or None when there is not enough evidence."""
        doc = await self.nudge_document(user_id)
        return doc.as_matrix() if doc is not None else None

    # -- extras (not part of the protocol) ---------------------------------

    async def nudge_document(
        self,
        user_id: str,
        *,
        lam: float = DEFAULT_LAMBDA,
        min_samples: int = MIN_SAMPLES,
    ) -> NudgeDocument | None:
        """The full fitted document, including diagnostics.

        Routes and dashboards want the metadata; the transfer only wants the
        matrix. Both read the same fit.
        """
        owner = _owner(user_id)
        async with self._lock():
            events = list(self._events.get(owner, ()))
            cached = self._nudge_cache.get(owner)
            if (
                cached is not None
                and cached[0] == len(events)
                and lam == DEFAULT_LAMBDA
                and min_samples == MIN_SAMPLES
            ):
                return cached[1]
            records = [
                self._records[i]
                for i in self._by_user.get(owner, ())
                if i in self._records
            ]

        doc = fit_nudge(records, events, lam=lam, min_samples=min_samples)
        if lam == DEFAULT_LAMBDA and min_samples == MIN_SAMPLES:
            async with self._lock():
                self._nudge_cache[owner] = (len(events), doc)
        return doc

    async def records(self, user_id: str) -> list[ForgeRecord]:
        """Flattened forges, oldest first — the shape the learner wants."""
        owner = _owner(user_id)
        async with self._lock():
            recs = [
                self._records[i]
                for i in self._by_user.get(owner, ())
                if i in self._records
            ]
        return sorted(recs, key=lambda r: r.created_at)

    async def feedback(self, user_id: str) -> list[FeedbackEvent]:
        """All recorded signals for a user, oldest first."""
        owner = _owner(user_id)
        async with self._lock():
            events = list(self._events.get(owner, ()))
        return sorted(events, key=lambda e: e.created_at)

    async def users(self) -> list[str]:
        async with self._lock():
            return sorted(self._by_user)

    async def clear(self) -> None:
        """Drop everything. Tests and demo resets."""
        async with self._lock():
            self._playlists.clear()
            self._records.clear()
            self._by_user.clear()
            self._events.clear()
            self._nudge_cache.clear()

    # -- seeding -----------------------------------------------------------

    def seed(self, playlists: Iterable[Playlist]) -> "MemoryAlmanac":
        """Load history synchronously. Returns self, so it chains.

        Synchronous on purpose: seeding happens at import time in demos and at
        fixture-construction time in tests, neither of which has a running
        loop. It touches the same structures as ``record_forge`` but skips the
        lock, which is correct precisely because there is no loop to contend
        with. Do not call it once the store is live.
        """
        for playlist in playlists:
            record = ForgeRecord.from_playlist(playlist)
            owner = _owner(playlist.user_id)
            if playlist.id not in self._playlists:
                self._by_user.setdefault(owner, []).append(playlist.id)
            self._playlists[playlist.id] = playlist
            self._records[playlist.id] = record
            self._nudge_cache.pop(owner, None)
        return self

    def seed_feedback(self, events: Iterable[FeedbackEvent]) -> "MemoryAlmanac":
        """Load feedback with explicit timestamps and context.

        ``record_feedback`` stamps ``created_at`` from the clock, which is
        right in production and useless for a test that needs a six-week-old
        skip. This is the way to build a history with shape.
        """
        for event in events:
            self._events.setdefault(event.user_id, []).append(event)
            self._nudge_cache.pop(event.user_id, None)
        return self

    def seed_records(self, records: Iterable[ForgeRecord]) -> "MemoryAlmanac":
        """Load flattened forges directly, for fixtures that never built a
        ``Playlist``. History will not return these — there is no playlist to
        return — but the learner and the retrospective will see them."""
        for record in records:
            owner = _owner(record.user_id)
            if record.playlist_id not in self._records:
                self._by_user.setdefault(owner, []).append(record.playlist_id)
            self._records[record.playlist_id] = record
            self._nudge_cache.pop(owner, None)
        return self

    # -- introspection -----------------------------------------------------

    def __len__(self) -> int:
        return len(self._playlists)

    def __repr__(self) -> str:
        users = len(self._by_user)
        events = sum(len(v) for v in self._events.values())
        return (
            f"MemoryAlmanac(forges={len(self._playlists)}, "
            f"users={users}, signals={events})"
        )


__all__ = ["MemoryAlmanac", "ANONYMOUS_USER", "MAX_FORGES_PER_USER", "MAX_EVENTS_PER_USER"]
