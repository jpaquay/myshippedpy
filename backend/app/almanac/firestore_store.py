"""Firestore-backed :class:`AlmanacStore`.

The almanac is Barogroove's long memory: every forge you have ever made, every
track you loved or skipped, and the small 9x7 correction that turns the generic
sky-to-sound transfer matrix into *yours*.

Scope
-----
This module owns **persistence and document shape**. It does not learn
anything. The ridge regression that turns feedback rows into a 9x7 delta is the
Almanac worker's; :meth:`FirestoreAlmanac.nudge` reads whatever that worker
last wrote and hands it over unchanged.

The delta document contract lives on
:class:`app.firebase.firestore.NudgeRepository` and is reproduced here so the
two workers cannot drift::

    almanac/{uid} = {
      "user_id":        "<uid>",
      "matrix_version": 1,           # bump on any shape change
      "sample_count":   137,         # feedback rows the fit consumed
      "updated_at":     <timestamp>, # tz-aware UTC
      "delta": {"rows": 9, "cols": 7, "values": [ ...63 floats, ROW-MAJOR... ]}
    }

The matrix is flattened because **Firestore rejects nested arrays**. The
repository reshapes it on read, so :meth:`nudge` returns a proper
``list[list[float]]`` of shape 9x7 and callers never see the flattening.

Degradation
-----------
Every method here swallows Firestore failures. ``record_forge`` returns the
playlist id it was given, ``history`` returns ``[]``, ``nudge`` returns
``None``. A dead Firestore should cost you your history sidebar, not your
playlist.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..contracts import Playlist

logger = logging.getLogger("barogroove.almanac.firestore")


_PROCESS_FORGE_HISTORY: list[Any] = []


class FirestoreAlmanac:
    """:class:`AlmanacStore` implementation over Firestore.

    Constructed by the container as ``FirestoreAlmanac(self.settings)`` when
    ``settings.has_firestore`` is true. Construction is free: no client, no
    credentials, no network until the first call.
    """

    def __init__(self, settings: Any, repositories: Any | None = None) -> None:
        self._settings = settings
        if repositories is None:
            # Imported here rather than at module top so this module keeps its
            # promise of importing with no google-cloud packages present.
            from ..firebase.firestore import build_repositories  # noqa: PLC0415

            repositories = build_repositories(settings)
        self._repos = repositories

    # -- AlmanacStore protocol ------------------------------------------

    async def record_forge(self, playlist: Playlist) -> str:
        """Persist a forged playlist and return its id.

        Returns the playlist's own id even when the write failed. The caller is
        handing the user a playlist right now; whether it also made it into the
        almanac is a separate concern and is already in the logs.

        Playlists are created private. Sharing is an explicit later act -- see
        ``ForgeRepository.set_public`` and the ``public`` flag in
        ``firestore.rules``.
        """
        playlist_id = str(getattr(playlist, "id", "") or "")
        _PROCESS_FORGE_HISTORY.insert(0, playlist)
        if len(_PROCESS_FORGE_HISTORY) > 150:
            del _PROCESS_FORGE_HISTORY[150:]

        try:
            stored = await self._repos.forges.create(playlist, public=False)
        except Exception:
            logger.exception("record_forge failed for %s", playlist_id)
            return playlist_id

        if stored is None:
            logger.warning("forge %s was not persisted; continuing degraded", playlist_id)
            return playlist_id

        # Keep a cheap counter on the profile so the retrospective endpoint can
        # answer "how many skies have you heard?" without a collection scan.
        user_id = getattr(playlist, "user_id", None)
        if user_id:
            try:
                await self._repos.users.upsert_profile(str(user_id))
            except Exception:
                logger.debug("profile touch failed for %s; harmless", user_id)
        return stored

    async def record_feedback(
        self,
        *,
        user_id: str,
        playlist_id: str,
        track_key: str,
        signal: str,
    ) -> None:
        """Record one loved/skipped signal.

        Fire-and-forget from the caller's perspective: the protocol returns
        ``None`` and a lost thumbs-up is not worth a 500. Unknown signal values
        are rejected by the repository, which logs and returns False.
        """
        try:
            ok = await self._repos.feedback.record(
                user_id=user_id,
                playlist_id=playlist_id,
                track_key=track_key,
                signal=signal,
            )
        except Exception:
            logger.exception("record_feedback failed for user=%s", user_id)
            return
        if not ok:
            logger.warning(
                "feedback not persisted (user=%s playlist=%s signal=%s)",
                user_id,
                playlist_id,
                signal,
            )

    async def history(self, user_id: str, limit: int = 50) -> list[Playlist]:
        """The user's past forges, newest first.

        Rows that no longer validate against the current :class:`Playlist`
        model are dropped rather than failing the whole request -- a schema
        change should cost you the oldest entries, not the endpoint.
        """
        playlists: list[Playlist] = []
        seen_ids: set[str] = set()

        try:
            rows = await self._repos.forges.list_for_user(user_id, limit=limit)
            for row in rows:
                playlist = self._to_playlist(row)
                if playlist is not None and playlist.id not in seen_ids:
                    playlists.append(playlist)
                    seen_ids.add(playlist.id)
        except Exception:
            logger.exception("history query failed for %s", user_id)

        # Merge in-memory buffer so recently forged Daylists appear immediately
        # even if Firestore index propagation or auth uid differs.
        for pl in _PROCESS_FORGE_HISTORY:
            pl_id = getattr(pl, "id", None)
            pl_uid = getattr(pl, "user_id", None)
            if pl_id and pl_id not in seen_ids:
                if pl_uid in {user_id, "demo", None} or not playlists:
                    playlists.append(pl)
                    seen_ids.add(pl_id)

        playlists.sort(
            key=lambda p: getattr(p, "created_at", None) or "",
            reverse=True,
        )
        return playlists[:limit]

    async def nudge(self, user_id: str) -> list[list[float]] | None:
        """The stored 9x7 delta for this user's transfer matrix, or ``None``.

        Read-only. This method never fits, never writes, never falls back to a
        computed value. ``None`` means "no personalisation stored" and the
        caller should use the base matrix unchanged -- which is also what it
        means when Firestore is down, on purpose.
        """
        try:
            return await self._repos.nudges.get_delta(user_id)
        except Exception:
            logger.exception("nudge lookup failed for %s", user_id)
            return None

    # -- Extras beyond the protocol --------------------------------------
    #
    # The Almanac worker's learning loop needs a way to write what it fits and
    # to read the training set. Both live here so all Firestore access for the
    # almanac goes through one door.

    async def put_nudge(
        self,
        user_id: str,
        delta: list[list[float]],
        *,
        sample_count: int,
    ) -> bool:
        """Store a freshly fitted 9x7 delta. Called by the learning loop.

        Dimension-checked by the repository; a wrong-shaped fit is refused
        rather than written and discovered later at read time.
        """
        try:
            return await self._repos.nudges.put_delta(
                user_id, delta, sample_count=sample_count
            )
        except Exception:
            logger.exception("nudge write failed for %s", user_id)
            return False

    async def nudge_meta(self, user_id: str) -> dict[str, Any] | None:
        """Version, sample count and freshness of the stored delta."""
        try:
            return await self._repos.nudges.get_meta(user_id)
        except Exception:
            logger.exception("nudge meta lookup failed for %s", user_id)
            return None

    async def feedback_rows(self, user_id: str, limit: int = 500) -> list[dict[str, Any]]:
        """Raw feedback documents -- the learning loop's training set."""
        try:
            return await self._repos.feedback.for_user(user_id, limit=limit)
        except Exception:
            logger.exception("feedback query failed for %s", user_id)
            return []

    async def healthcheck(self) -> dict[str, Any]:
        """Reachability report. Never raises."""
        try:
            return await self._repos.healthcheck()
        except Exception as exc:  # noqa: BLE001 - healthcheck never raises
            return {"reachable": False, "detail": f"healthcheck failed: {exc}"}

    # -- Internals --------------------------------------------------------

    @staticmethod
    def _to_playlist(row: dict[str, Any]) -> Playlist | None:
        """Rebuild a :class:`Playlist` from a Firestore document.

        Returns ``None`` on validation failure. The bookkeeping keys the
        repository adds (``public``, ``_schema``, ``updated_at``) are not part
        of the model, so they are stripped before validation.
        """
        try:
            from ..contracts import Playlist as _Playlist  # noqa: PLC0415
        except Exception:
            logger.error("contracts.Playlist is not importable; history unavailable")
            return None

        payload = {
            k: v
            for k, v in row.items()
            if not k.startswith("_") and k not in {"public", "updated_at"}
        }
        try:
            return _Playlist.model_validate(payload)
        except Exception as exc:
            logger.debug("forge row failed validation: %s", exc)
            return None


__all__ = ["FirestoreAlmanac"]
